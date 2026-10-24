// POST /api/checkout { id, size, base, colour } -> { plan, price_cents, quote }
// Recomputes the price server-side from the measured mesh, then makes a one-time hidden Whop plan
// for exactly that price. The browser mounts Whop's embedded checkout with the returned plan id.
// Custom orders are recorded with full metadata; they are NOT auto-sent to a supplier.
import { json, error } from "./_lib.js";
import { decodeJob, cachedGeom, priceFor, SIZES, BASES, COLOURS } from "./_render.js";

export async function POST(request) {
  const env = process.env;
  if (!env.WHOP_API_KEY || !env.WHOP_COMPANY_ID || !env.WHOP_PRODUCT_ID) return error(503, "checkout not configured");
  const b = await request.json().catch(() => null);
  const job = b?.id ? decodeJob(String(b.id)) : null;
  if (!job) return error(400, "unknown render");
  const size = SIZES.some((s) => s.id === b.size) ? b.size : "M";
  const base = BASES.includes(b.base) ? b.base : "round";
  const colour = Object.hasOwn(COLOURS, b.colour) ? b.colour : "grey";
  const cached = await cachedGeom(job);
  if (!cached) return error(409, "That model isn't ready yet. Wait for it to finish, then try again.");
  const q = priceFor(cached.geom, size, base);
  const title = `Custom 3D print ${q.heightMm}mm`.slice(0, 30);
  const res = await fetch("https://api.whop.com/api/v1/plans", {
    method: "POST",
    headers: { authorization: `Bearer ${env.WHOP_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({
      company_id: env.WHOP_COMPANY_ID,
      product_id: env.WHOP_PRODUCT_ID,
      plan_type: "one_time",
      release_method: "buy_now",
      visibility: "hidden",
      initial_price: q.price_cents / 100,
      currency: "usd",
      title,
      description: `Custom figure, ${q.heightMm} mm, ${colour} PETG, ${base} base`,
    }),
  });
  const plan = await res.json().catch(() => ({}));
  if (!res.ok || !plan?.id) {
    console.error("whop plan create failed", res.status, JSON.stringify(plan).slice(0, 300));
    return error(502, "Checkout failed to start. Try again in a moment.");
  }
  return json({
    plan: plan.id,
    price_cents: q.price_cents,
    quote: { ...q, colour, render_id: String(b.id).slice(0, 480), glb: cached.rawGlbUrl, concept: job.c },
  });
}
