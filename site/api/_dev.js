// Private owner dashboard data for /dev. Reached via POST /api/stats { password }.
// Everything comes from Whop payments (amounts, fees, metadata) plus our KV (events, render counts).
// Costs are estimates unless a supplier cost is known; the response says which.
import { json, error, timingSafeEqual, store, getJSON, endsAt, goalCents, PRODUCTS, FOUNDING_TOTAL } from "./_lib.js";
import { fetchWhopPayments, isPaid, moneyCents, paymentCents } from "./stats.js";

const DEFAULT_PASSWORD = "terek is best";
const CACHE_MS = 8_000;
const FAIL_WINDOW_MS = 10 * 60_000;
const FAIL_MAX = 12;

// Estimated supplier cost (print + ship) for fixed products, cents. Custom orders carry their own
// est_cost_cents from the pricing function. Override per product with DEV_COST_<KEY>_CENTS.
const DEFAULT_COST_CENTS = { tweet: 1100, milestone: 1300, fullcolour: 3500, team: 6500, custom: 1000 };

const fails = new Map();
let cache = null;

const norm = (s) => String(s || "").trim().toLowerCase().replace(/\s+/g, " ");
const num = (env, k, d) => {
  const v = env[k];
  return v != null && v !== "" && Number.isFinite(Number(v)) ? Number(v) : d;
};

function clientIp(request) {
  return (request.headers.get("x-forwarded-for") || "").split(",")[0].trim() || "local";
}

function checkPassword(request, env, given) {
  const ip = clientIp(request);
  const now = Date.now();
  const recent = (fails.get(ip) || []).filter((t) => now - t < FAIL_WINDOW_MS);
  if (recent.length >= FAIL_MAX) return error(429, "Too many tries. Wait a few minutes.");
  const want = norm(env.DEV_PASSWORD || DEFAULT_PASSWORD);
  if (!timingSafeEqual(norm(given), want)) {
    recent.push(now);
    fails.set(ip, recent);
    return error(401, "Wrong password.");
  }
  fails.delete(ip);
  return null;
}

function productKey(p) {
  const m = p.metadata || {};
  if (m.product) return String(m.product);
  const title = `${p.line_items?.[0]?.plan_title || ""}`.toLowerCase();
  for (const pr of PRODUCTS) if (title.includes(pr.name.toLowerCase().split(" ")[0])) return pr.key;
  return "unknown";
}

function productName(key, p) {
  const fixed = PRODUCTS.find((x) => x.key === key);
  if (fixed) return fixed.name;
  if (key === "custom") return "Custom 3D figure";
  return p.line_items?.[0]?.plan_title || key;
}

function statusOf(p) {
  if (isPaid(p)) {
    const refunded = moneyCents(p.refunded_amount) || 0;
    const gross = moneyCents(p.total) ?? paymentCents(p);
    if (refunded > 0 && refunded >= gross) return "refunded";
    if (refunded > 0) return "part_refunded";
    if (p.dispute_created_at) return "disputed";
    return "paid";
  }
  return String(p.substatus || p.status || "unknown").toLowerCase();
}

function shapeOrder(p, env) {
  const m = p.metadata || {};
  const key = productKey(p);
  const status = statusOf(p);
  const paid = isPaid(p);
  const gross = moneyCents(p.total) ?? paymentCents(p);
  const refunded = moneyCents(p.refunded_amount) || 0;
  const afterFees = moneyCents(p.amount_after_fees);
  const feeActual = paid && afterFees != null && gross > 0;
  const fee = !paid ? 0 : feeActual ? Math.max(0, gross - afterFees) : Math.round(gross * 0.03) + 30;
  const metaCost = Number(m.est_cost_cents);
  const costSource = Number.isFinite(metaCost) && metaCost > 0 ? "pricing model" : "product default";
  const cost = !paid || status === "refunded" ? 0 : costSource === "pricing model" ? Math.round(metaCost) : num(env, `DEV_COST_${key.toUpperCase()}_CENTS`, DEFAULT_COST_CENTS[key] ?? 1000);
  const net = paid ? gross - refunded - fee : 0;
  const addr = p.shipping_address || {};
  return {
    id: p.id,
    ref: m.order_ref || null,
    status,
    created_at: p.created_at || null,
    paid_at: p.paid_at || null,
    product: key,
    product_name: productName(key, p),
    plan_title: p.line_items?.[0]?.plan_title || null,
    gross_cents: paid ? gross : 0,
    attempted_cents: gross,
    refunded_cents: refunded,
    fee_cents: fee,
    fee_actual: feeActual,
    cost_cents: cost,
    cost_source: costSource,
    profit_cents: net - cost,
    size: m.size || null,
    height_mm: m.height_mm ? Number(m.height_mm) : null,
    colour: m.colour || null,
    base: m.base || null,
    volume_cm3: m.est_volume_cm3 ? Number(m.est_volume_cm3) : null,
    concept: m.concept || null,
    glb: m.glb || null,
    render_id: m.render_id || null,
    tweet_url: m.tweet_url || null,
    tweet_text: m.tweet_text || null,
    likes: m.likes || null,
    number: m.number || null,
    label: m.label || null,
    name: m.name || null,
    team: m.team || null,
    claim_slug: m.claim_slug || null,
    gift: m.gift_from ? { from: m.gift_from, note: m.gift_note || "" } : null,
    source: m.source || "direct",
    failure: p.failure_message || null,
    customer: {
      name: m.ship_name || addr.name || p.billing_address?.name || p.user?.name || null,
      email: m.ship_email || p.customer_email || null,
      city: m.ship_city || addr.city || null,
      state: m.ship_state || addr.state || null,
    },
  };
}

function bump(map, k, cents) {
  const e = map[k] || (map[k] = { orders: 0, revenue_cents: 0 });
  e.orders += 1;
  e.revenue_cents += cents;
}

async function renderCounts(env) {
  const days = [];
  for (let i = 0; i < 3; i++) {
    const d = new Date(Date.now() - i * 86400_000).toISOString().slice(0, 10);
    let n = 0;
    try {
      n = Number((await getJSON(env, `render-count:${d}`)) || 0);
    } catch {
      n = 0;
    }
    days.push({ day: d, renders: n });
  }
  return days;
}

async function recentEvents(env) {
  try {
    const raw = await store(env).lrange("events", 0, 39);
    return raw.map((s) => { try { return JSON.parse(s); } catch { return null; } }).filter(Boolean);
  } catch {
    return [];
  }
}

export async function buildDashboard(env) {
  const configured = Boolean(env.WHOP_API_KEY && env.WHOP_COMPANY_ID);
  const [payments, renders, events] = await Promise.all([
    configured ? fetchWhopPayments(env) : Promise.resolve([]),
    renderCounts(env),
    recentEvents(env),
  ]);
  const orders = payments.map((p) => shapeOrder(p, env));
  orders.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));

  const t = { gross_cents: 0, refunded_cents: 0, fees_cents: 0, production_cents: 0, orders_paid: 0, orders_refunded: 0, attempts_other: 0, fees_all_actual: true };
  const byProduct = {}, bySource = {}, byStatus = {};
  for (const o of orders) {
    byStatus[o.status] = (byStatus[o.status] || 0) + 1;
    if (!o.gross_cents) { t.attempts_other += 1; continue; }
    t.orders_paid += 1;
    if (o.status === "refunded") t.orders_refunded += 1;
    t.gross_cents += o.gross_cents;
    t.refunded_cents += o.refunded_cents;
    t.fees_cents += o.fee_cents;
    t.production_cents += o.cost_cents;
    if (!o.fee_actual) t.fees_all_actual = false;
    const kept = o.gross_cents - o.refunded_cents;
    bump(byProduct, o.product_name, kept);
    bump(bySource, o.source, kept);
  }
  const renderCostCents = num(env, "RENDER_COST_CENTS", 25);
  const rendersToday = renders[0]?.renders || 0;
  const rendersTotal = renders.reduce((s, d) => s + d.renders, 0);
  const render_cents = rendersTotal * renderCostCents;
  const revenue = t.gross_cents - t.refunded_cents; // same number /live shows
  const net = revenue - t.fees_cents;
  const profit = net - t.production_cents - render_cents;
  const kept = t.orders_paid - t.orders_refunded;

  return {
    generated_at: new Date().toISOString(),
    whop_configured: configured,
    ends_at: endsAt(env),
    goal_cents: goalCents(env),
    founding_left: Math.max(0, FOUNDING_TOTAL - t.orders_paid),
    totals: {
      revenue_cents: revenue,
      gross_cents: t.gross_cents,
      refunded_cents: t.refunded_cents,
      fees_cents: t.fees_cents,
      fees_all_actual: t.fees_all_actual,
      net_cents: net,
      production_cents: t.production_cents,
      render_cents,
      render_cost_each_cents: renderCostCents,
      costs_cents: t.fees_cents + t.production_cents + render_cents,
      profit_cents: profit,
      margin: revenue > 0 ? profit / revenue : null,
      orders_paid: t.orders_paid,
      orders_refunded: t.orders_refunded,
      attempts_other: t.attempts_other,
      aov_cents: kept > 0 ? Math.round(revenue / kept) : 0,
      renders_today: rendersToday,
      renders_3d: rendersTotal,
      conversion: rendersTotal > 0 ? kept / rendersTotal : null,
    },
    by_product: byProduct,
    by_source: bySource,
    by_status: byStatus,
    renders,
    orders: orders.slice(0, 300),
    events,
  };
}

export async function handleDev(request, env) {
  const body = await request.json().catch(() => null);
  const denied = checkPassword(request, env || {}, body?.password);
  if (denied) return denied;
  try {
    if (!cache || Date.now() - cache.at > CACHE_MS) cache = { at: Date.now(), data: await buildDashboard(env || {}) };
    return json(cache.data, 200, { "cache-control": "no-store, private" });
  } catch (e) {
    console.error("dev dashboard failed", String(e?.message || e));
    if (cache) return json({ ...cache.data, stale: true }, 200, { "cache-control": "no-store, private" });
    return error(502, "Couldn't reach Whop. Retrying.");
  }
}
