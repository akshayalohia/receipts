import { json, error, requireAdmin, getJSON, putJSON, COLOURS, SLUG_RE, pathParam } from "../_lib.js";

const CLAIM_PRODUCTS = new Set(["tweet", "milestone"]);
const STRING_FIELDS = ["handle", "tweet_url", "text", "likes", "number", "label", "name", "date"];
const MAX_OG_B64 = 2 * 1024 * 1024; // ~1.5 MB PNG

export function claimSlug(request) {
  const s = pathParam(request, "/api/claim/", "slug");
  return SLUG_RE.test(s) ? s : null;
}

export function validateClaim(body, slug) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { err: "body must be a JSON object" };
  if (!CLAIM_PRODUCTS.has(body.product)) return { err: "product must be tweet or milestone" };
  if (typeof body.handle !== "string" || !body.handle.trim()) return { err: "handle required" };
  if (!COLOURS.includes(body.colour)) return { err: "invalid colour" };
  if (!Number.isInteger(body.price_cents) || body.price_cents < 0) return { err: "price_cents must be a non-negative integer" };
  const claim = { slug, product: body.product, colour: body.colour, price_cents: body.price_cents };
  for (const k of STRING_FIELDS) {
    if (body[k] == null) continue;
    if (typeof body[k] !== "string" && typeof body[k] !== "number") return { err: `${k} must be a string` };
    claim[k] = String(body[k]).slice(0, k === "text" ? 280 : 200);
  }
  if (body.og_image_b64 != null) {
    if (typeof body.og_image_b64 !== "string" || body.og_image_b64.length > MAX_OG_B64 || !/^[A-Za-z0-9+/=\s]*$/.test(body.og_image_b64)) {
      return { err: "og_image_b64 must be base64 (max ~1.5 MB)" };
    }
    claim.og_image_b64 = body.og_image_b64.replace(/\s+/g, "");
  }
  return { claim };
}

export async function handleGet(request, env) {
  const slug = claimSlug(request);
  if (!slug) return error(400, "invalid slug");
  const claim = await getJSON(env, `claim:${slug}`);
  if (!claim) return error(404, "not found");
  // og_image_b64 is served at /api/claim/<slug>/og.png; omit the heavy blob here.
  const { og_image_b64, ...pub } = claim;
  return json(pub);
}

export async function handlePut(request, env) {
  const denied = requireAdmin(request, env);
  if (denied) return denied;
  const slug = claimSlug(request);
  if (!slug) return error(400, "invalid slug");
  let body;
  try {
    body = await request.json();
  } catch {
    return error(400, "invalid JSON");
  }
  const { claim, err } = validateClaim(body, slug);
  if (err) return error(400, err);
  await putJSON(env, `claim:${slug}`, claim);
  return json({ ok: true, slug });
}

export function GET(request) {
  return handleGet(request, process.env);
}

export function PUT(request) {
  return handlePut(request, process.env);
}
