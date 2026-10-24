import { json, endsAt, goalCents, getJSON, putJSON, FOUNDING_TOTAL } from "./_lib.js";

const WHOP_PAYMENTS = "https://api.whop.com/api/v1/payments";
const MAX_PAGES = 20;
const PER_PAGE = 100;
const CACHE_MS = 30_000;
const PAID = new Set(["paid", "succeeded"]);

export function isPaid(p) {
  const s = String(p.status || "").toLowerCase();
  const sub = String(p.substatus || "").toLowerCase();
  return PAID.has(s) || PAID.has(sub);
}

// Whop v1 (verified on a live payment, Oct 24 2026) returns money as objects:
// total: { currency: "usd", amount: "39.00", decimals: 2 }, refunded_amount: { amount: "0.00" }.
// Older shapes (plain dollar numbers, *_cents fields) are still accepted.
export function moneyCents(v) {
  if (v == null) return null;
  if (typeof v === "object") {
    const n = Number(v.amount);
    if (!Number.isFinite(n)) return null;
    const dec = Number.isFinite(Number(v.decimals)) ? Number(v.decimals) : 2;
    return Math.round(n * 10 ** dec * (100 / 10 ** dec));
  }
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}

export function paymentCents(p) {
  let gross = null;
  for (const k of ["final_amount_cents", "total_cents", "amount_cents"]) {
    const v = Number(p[k]);
    if (p[k] != null && Number.isFinite(v)) { gross = Math.round(v); break; }
  }
  if (gross == null) {
    for (const k of ["final_amount", "total", "amount"]) {
      const c = moneyCents(p[k]);
      if (c != null) { gross = c; break; }
    }
  }
  if (gross == null) return 0;
  const refunded = moneyCents(p.refunded_amount) || 0;
  return Math.max(0, gross - refunded);
}

function listFrom(body) {
  if (Array.isArray(body)) return body;
  if (body && Array.isArray(body.data)) return body.data;
  if (body && Array.isArray(body.payments)) return body.payments;
  return [];
}

/** Returns query params for the next page, or null when done. */
function nextPageParams(body, currentPage) {
  const pi = body && body.page_info;
  if (pi && (pi.has_next_page || pi.hasNextPage) && (pi.end_cursor || pi.endCursor)) {
    return { after: pi.end_cursor || pi.endCursor };
  }
  const pg = body && body.pagination;
  if (pg) {
    if (pg.next_cursor) return { cursor: pg.next_cursor };
    const cur = Number(pg.current_page ?? currentPage);
    const total = Number(pg.total_pages ?? pg.total_page);
    if (pg.next_page != null && pg.next_page !== false) return { page: String(pg.next_page) };
    if (Number.isFinite(total) && cur < total) return { page: String(cur + 1) };
  }
  return null;
}

/** Every Whop payment for the company (all statuses), newest first as Whop returns them. */
export async function fetchWhopPayments(env) {
  const all = [];
  let params = { page: "1" };
  for (let i = 0; i < MAX_PAGES && params; i++) {
    const u = new URL(WHOP_PAYMENTS);
    u.searchParams.set("account_id", env.WHOP_COMPANY_ID || ""); // Whop v1 rejects company_id here
    u.searchParams.set("per", String(PER_PAGE));
    u.searchParams.set("first", String(PER_PAGE));
    for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
    const res = await fetch(u.toString(), {
      headers: { authorization: `Bearer ${env.WHOP_API_KEY}`, accept: "application/json" },
    });
    if (!res.ok) throw new Error(`whop status ${res.status}`);
    const body = await res.json();
    const list = listFrom(body);
    for (const p of list) if (p) all.push(p);
    const currentPage = Number(params.page || i + 1);
    params = list.length ? nextPageParams(body, currentPage) : null;
  }
  return all;
}

export async function fetchWhopTotals(env) {
  let revenue_cents = 0;
  let orders = 0;
  for (const p of await fetchWhopPayments(env)) {
    if (!isPaid(p)) continue;
    orders += 1;
    revenue_cents += paymentCents(p);
  }
  return { revenue_cents, orders };
}

function shape(totals, env) {
  return {
    revenue_cents: totals.revenue_cents,
    orders: totals.orders,
    founding_left: Math.max(0, FOUNDING_TOTAL - totals.orders),
    ends_at: endsAt(env),
    goal_cents: goalCents(env),
  };
}

export async function handleGet(request, env) {
  const e = env || {};
  const headers = { "cache-control": "public, max-age=15" };
  if (!e.WHOP_API_KEY) return json(shape({ revenue_cents: 0, orders: 0 }, e), 200, headers);

  let cached = null;
  try {
    cached = await getJSON(e, "stats");
  } catch {
    cached = null; // storage down: fall through to Whop
  }
  if (cached && typeof cached.at === "number" && Date.now() - cached.at < CACHE_MS) {
    return json(shape(cached, e), 200, headers);
  }

  try {
    const totals = await fetchWhopTotals(e);
    // Freshness (30 s) is enforced via `at`; the key expires after 60 s so stale data can still be served on errors.
    await putJSON(e, "stats", { ...totals, at: Date.now() }, 60).catch(() => {});
    return json(shape(totals, e), 200, headers);
  } catch {
    // Do not echo upstream errors (could include request details). Serve stale or zeros.
    const fallback = cached || { revenue_cents: 0, orders: 0 };
    return json(shape(fallback, e), 200, headers);
  }
}

export function GET(request) {
  return handleGet(request, process.env);
}

// POST /api/stats { password } -> private owner dashboard (served by /dev). Lives here because
// Vercel Hobby caps a deployment at 12 functions. POST, so no CDN or browser caching.
export async function POST(request) {
  const { handleDev } = await import("./_dev.js");
  return handleDev(request, process.env);
}
