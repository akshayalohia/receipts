// Custom 3D renders: idea and/or photo -> concept image -> 3D mesh -> fast preview + measured price.
// Ported from the render kit (/opt/data/profiles/ceo/render-kit). Server-only. Needs FAL_KEY.
// Jobs are stateless: the id carries everything (base64url JSON), measurements are cached in KV.
import { fal } from "@fal-ai/client";
import { NodeIO } from "@gltf-transform/core";
import { KHRMeshQuantization } from "@gltf-transform/extensions";
import { dedup, prune, quantize, simplify, weld } from "@gltf-transform/functions";
import { MeshoptSimplifier } from "meshoptimizer";
import { getJSON, putJSON } from "./_lib.js";

fal.config({ credentials: process.env.FAL_KEY });

export const MODELS = {
  textToImage: "fal-ai/flux/schnell",
  imageEdit: "fal-ai/flux-pro/kontext",
  imageTo3d: process.env.RENDER_3D_MODEL || "fal-ai/hunyuan3d-v21",
};

// Steer every concept toward a good single-colour print: one object, chunky, no floor/shadow.
const PRINT_STYLE =
  "single isolated object, full body, centered, floating on a pure white background, no shadow, no floor, " +
  "studio product photo, matte grey clay figurine, chunky sturdy proportions, no thin fragile parts, " +
  "3D printable collectible";
const PHOTO_TO_FIGURINE =
  "Turn this into a matte grey clay collectible figurine of the same subject, keeping its recognisable " +
  "features, full body, chunky sturdy proportions, isolated on a pure white background, no shadow, no floor";

// ---------- job ids ----------
export const encodeJob = (j) => Buffer.from(JSON.stringify(j)).toString("base64url");
export function decodeJob(id) {
  if (id === "demo") return { demo: true, r: "demo", c: "/examples/dog.png", p: "my golden retriever wearing a graduation cap", m: "demo" };
  try {
    const j = JSON.parse(Buffer.from(String(id), "base64url").toString("utf8"));
    return typeof j?.r === "string" && typeof j?.c === "string" && typeof j?.m === "string" ? j : null;
  } catch {
    return null;
  }
}

// ---------- spend guards ----------
const WINDOW_MS = 60 * 60 * 1000;
const hits = new Map();
export function clientIp(req) {
  return (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || req.headers.get("x-real-ip") || "unknown";
}
/** null when allowed, else a message. Per-IP (per warm instance) + global daily cap in KV. */
export async function spendGuard(req) {
  const max = Number(process.env.RENDER_MAX_PER_HOUR || 8);
  const ip = clientIp(req);
  const now = Date.now();
  const list = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  if (list.length >= max) return `Too many renders from you. Try again in ${Math.ceil((WINDOW_MS - (now - list[0])) / 60000)} min.`;
  const day = new Date().toISOString().slice(0, 10);
  const key = `render-count:${day}`;
  const n = Number((await getJSON(process.env, key)) || 0);
  if (n >= Number(process.env.RENDER_DAILY_MAX || 300)) return "We've hit today's render limit. Pick a preset below, or try again tomorrow.";
  list.push(now);
  hits.set(ip, list);
  await putJSON(process.env, key, n + 1, 2 * 86400);
  return null;
}

// ---------- fal calls ----------
const firstImage = (data) => {
  const url = data?.images?.[0]?.url;
  if (!url) throw new Error("image model returned no image");
  if (data?.has_nsfw_concepts?.[0]) throw new Error("blocked by safety filter");
  return url;
};

export async function makeConcept({ prompt, photoUrl }) {
  const p = (prompt || "").trim().slice(0, 500);
  if (photoUrl) {
    const { data } = await fal.subscribe(MODELS.imageEdit, {
      input: { image_url: photoUrl, prompt: p ? `${PHOTO_TO_FIGURINE}. ${p}` : PHOTO_TO_FIGURINE, safety_tolerance: "2", output_format: "png" },
    });
    return firstImage(data);
  }
  if (!p) throw new Error("need a prompt or a photo");
  const { data } = await fal.subscribe(MODELS.textToImage, {
    input: { prompt: `${p}. ${PRINT_STYLE}`, image_size: "square_hd", num_inference_steps: 4, enable_safety_checker: true },
  });
  return firstImage(data);
}

export async function editConcept(conceptUrl, instruction) {
  const { data } = await fal.subscribe(MODELS.imageEdit, {
    input: { image_url: conceptUrl, prompt: `${instruction.trim().slice(0, 300)}. Keep it a ${PRINT_STYLE}`, safety_tolerance: "2", output_format: "png" },
  });
  return firstImage(data);
}

export async function start3d(conceptUrl) {
  const input = { input_image_url: conceptUrl };
  if (MODELS.imageTo3d.includes("hunyuan3d-v21")) Object.assign(input, { textured_mesh: false, num_inference_steps: 30, octree_resolution: 256 });
  const { request_id } = await fal.queue.submit(MODELS.imageTo3d, { input });
  return request_id;
}

export async function jobStatus(job) {
  const s = await fal.queue.status(job.m, { requestId: job.r, logs: false });
  if (s.status === "IN_QUEUE") return { state: "queued", position: s.queue_position };
  if (s.status === "IN_PROGRESS") return { state: "building" };
  if (s.status === "COMPLETED") {
    const { data } = await fal.queue.result(job.m, { requestId: job.r });
    const glbUrl = data?.model_glb?.url || data?.model_mesh?.url;
    return glbUrl ? { state: "done", glbUrl } : { state: "failed", error: "no mesh in result" };
  }
  return { state: "failed", error: `unexpected status ${s.status}` };
}

export async function uploadPhoto(file) {
  if (!/^image\/(png|jpe?g|webp|heic|heif)$/.test(file.type)) throw new Error("photo must be png, jpg, webp or heic");
  if (file.size > 4 * 1024 * 1024) throw new Error("photo must be under 4 MB");
  return fal.storage.upload(file);
}

// ---------- preview mesh + measurements ----------
const io = () => new NodeIO().registerExtensions([KHRMeshQuantization]);

function triCount(doc) {
  let n = 0;
  for (const m of doc.getRoot().listMeshes())
    for (const p of m.listPrimitives()) n += (p.getIndices()?.getCount() ?? p.getAttribute("POSITION").getCount()) / 3;
  return n;
}

/** Image-to-3D turns drop shadows into a ground slab: a bottom band much wider than the body. Cut it. */
function trimGroundSlab(p) {
  const pos = p.getAttribute("POSITION");
  if (!pos) return null;
  const arr = pos.getArray();
  const n = pos.getCount();
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < n; i++) { const y = arr[i * 3 + 1]; if (y < lo) lo = y; if (y > hi) hi = y; }
  const H = hi - lo;
  if (!(H > 0)) return null;
  const ext = (a, b) => {
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity, c = 0;
    for (let i = 0; i < n; i++) {
      const y = arr[i * 3 + 1];
      if (y < a || y >= b) continue;
      const x = arr[i * 3], z = arr[i * 3 + 2]; c++;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (z < z0) z0 = z; if (z > z1) z1 = z;
    }
    return c > 10 ? Math.max(x1 - x0, z1 - z0) : 0;
  };
  const body = Math.max(ext(lo + 0.08 * H, lo + 0.35 * H), 1e-9);
  if (ext(lo, lo + 0.01 * H) <= 1.6 * body) return null;
  let cut = null;
  for (let i = 1; i < 15; i++) if (ext(lo + i * 0.01 * H, lo + (i + 1) * 0.01 * H) <= 1.25 * body) { cut = lo + (i + 0.5) * 0.01 * H; break; }
  if (cut === null) return null;
  const idx = p.getIndices();
  const src = idx ? idx.getArray() : Uint32Array.from({ length: n }, (_, i) => i);
  const keep = [];
  for (let t = 0; t < src.length; t += 3) {
    const a = src[t], b = src[t + 1], c = src[t + 2];
    if (arr[a * 3 + 1] < cut && arr[b * 3 + 1] < cut && arr[c * 3 + 1] < cut) continue;
    keep.push(a, b, c);
  }
  return new Uint32Array(keep);
}

/** Bounding box (glTF Y-up) and |signed volume| in model units, from every primitive (node transforms ignored: AI GLBs are one mesh). */
function measure(doc) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  let vol = 0;
  for (const m of doc.getRoot().listMeshes()) {
    for (const p of m.listPrimitives()) {
      const pos = p.getAttribute("POSITION");
      if (!pos) continue;
      const n = pos.getCount();
      const v = [0, 0, 0];
      const P = new Float64Array(n * 3);
      for (let i = 0; i < n; i++) {
        pos.getElement(i, v); // dequantised by gltf-transform
        P[i * 3] = v[0]; P[i * 3 + 1] = v[1]; P[i * 3 + 2] = v[2];
        for (let k = 0; k < 3; k++) { if (v[k] < lo[k]) lo[k] = v[k]; if (v[k] > hi[k]) hi[k] = v[k]; }
      }
      const idx = p.getIndices();
      const src = idx ? idx.getArray() : Uint32Array.from({ length: n }, (_, i) => i);
      for (let t = 0; t < src.length; t += 3) {
        const a = src[t] * 3, b = src[t + 1] * 3, c = src[t + 2] * 3;
        vol += (P[a] * (P[b + 1] * P[c + 2] - P[b + 2] * P[c + 1]) - P[a + 1] * (P[b] * P[c + 2] - P[b + 2] * P[c]) + P[a + 2] * (P[b] * P[c + 1] - P[b + 1] * P[c])) / 6;
      }
    }
  }
  const size = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]];
  return { size, volume: Math.abs(vol) };
}

export async function makePreview(raw) {
  const t0 = Date.now();
  await MeshoptSimplifier.ready;
  const doc = await io().readBinary(raw);
  const trisIn = triCount(doc);
  for (const t of doc.getRoot().listTextures()) t.dispose();
  let trimmedSlab = false;
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const p of mesh.listPrimitives()) {
      for (const sem of p.listSemantics()) if (sem !== "POSITION" && sem !== "NORMAL") p.setAttribute(sem, null);
      const keep = trimGroundSlab(p);
      if (keep) {
        p.setIndices(doc.createAccessor().setType("SCALAR").setArray(keep).setBuffer(doc.getRoot().listBuffers()[0]));
        trimmedSlab = true;
      }
    }
  }
  const ratio = Math.min(1, Number(process.env.PREVIEW_TRIS || 80000) / Math.max(trisIn, 1));
  await doc.transform(weld(), simplify({ simplifier: MeshoptSimplifier, ratio, error: 0.002 }), dedup(), prune());
  const geom = measure(doc); // before quantize: exact float positions
  await doc.transform(quantize({ quantizePosition: 14, quantizeNormal: 10 }));
  const glb = await io().writeBinary(doc);
  return { glb, geom, trimmedSlab, trisIn: Math.round(trisIn), trisOut: Math.round(triCount(doc)), ms: Date.now() - t0 };
}

// ---------- pricing ----------
// Cost-plus: estimate what one print costs us (Slant 3D-style PETG FDM + shipping + the render itself),
// add PRICE_MARKUP on top, then gross up for Whop's fee so the markup survives it. Every constant is env-tunable.
// Heights are the figure itself (the plinth adds a few mm under it). Slant 3D's max build height is 220 mm.
export const SIZES = [
  { id: "40", label: "Mini", heightMm: 40 },
  { id: "50", label: "Small", heightMm: 50 },
  { id: "65", label: "Desk", heightMm: 65 },
  { id: "80", label: "Classic", heightMm: 80 },
  { id: "100", label: "Shelf", heightMm: 100 },
  { id: "150", label: "Statement", heightMm: 150 },
  { id: "200", label: "Showpiece", heightMm: 200 },
];
export const DEFAULT_SIZE = "80";
// Old ids from the S/M/L era: old links and paid orders (metadata size "S", height_mm 75) must keep resolving.
const LEGACY_SIZES = {
  S: { id: "S", label: "Desk", heightMm: 75 },
  M: { id: "M", label: "Shelf", heightMm: 100 },
  L: { id: "L", label: "Statement", heightMm: 150 },
};
/** Size record for a current or legacy id, else null. */
export function resolveSize(id) {
  const k = String(id ?? "");
  return SIZES.find((s) => s.id === k) || (Object.hasOwn(LEGACY_SIZES, k) ? LEGACY_SIZES[k] : null);
}
export const BASES = ["round", "square", "none"];
export const COLOURS = { black: "#1d1d1f", white: "#f2f1ed", grey: "#9a9a9a", red: "#c3302c", blue: "#2554c7", green: "#2d8550", gold: "#c9a24b" };

const num = (k, d) => (Number.isFinite(Number(process.env[k])) && process.env[k] !== "" && process.env[k] != null ? Number(process.env[k]) : d);

/** Shipping by figure height. PRINT_SHIPPING_USD, if set, overrides the tiers with one flat rate. */
function shippingUsd(H) {
  if (process.env.PRINT_SHIPPING_USD) return num("PRINT_SHIPPING_USD", 7);
  if (H <= 100) return num("PRINT_SHIP_S", 5.5);
  if (H <= 150) return num("PRINT_SHIP_M", 7);
  return num("PRINT_SHIP_L", 9);
}

export function priceFor(geom, sizeId, base) {
  const size = resolveSize(sizeId) || resolveSize(DEFAULT_SIZE);
  const H = size.heightMm;
  const [w, h, d] = geom.size;
  const s = H / Math.max(h, 1e-9);
  const bbox = w * h * d * s ** 3; // mm^3
  // AI meshes are rarely watertight: clamp the signed volume to a sane share of the bounding box.
  let vol = Math.min(Math.max(geom.volume * s ** 3, 0.08 * bbox), 0.7 * bbox);
  if (base !== "none") {
    const foot = Math.max(w, d) * s * 0.75;
    const bh = Math.max(H * 0.06, 4);
    vol += base === "square" ? (foot + 8) ** 2 * bh : Math.PI * (foot / 2 + 4) ** 2 * bh;
  }
  const cm3 = vol / 1000;
  const grams = cm3 * num("PRINT_DENSITY_G_CM3", 1.27) * num("PRINT_FILL_FRACTION", 0.4); // walls + ~15% infill
  // All money below in integer cents so the breakdown adds up exactly.
  const cents = (usd) => Math.round(usd * 100);
  const print = cents(num("PRINT_SETUP_USD", 2.5) + grams * num("PRINT_USD_PER_GRAM", 0.05));
  const ship = cents(shippingUsd(H));
  const render = cents(num("RENDER_COST_USD", 0.25));
  const cost = print + ship + render;
  const markup = num("PRICE_MARKUP", 0.9);
  const feePct = num("WHOP_FEE_PCT", 0.03);
  const feeFixed = cents(num("WHOP_FEE_FIXED_USD", 0.3));
  // price = cost*(1+m) + fees, fees = pct*price + fixed  =>  price = (cost*(1+m) + fixed) / (1 - pct)
  const target = Math.max(cents(num("PRICE_MIN_USD", 12)), (cost * (1 + markup) + feeFixed) / (1 - feePct));
  // Charm price: the next whole dollar minus a cent ($17.99), never below the target.
  const price_cents = Math.ceil((Math.ceil(target) + 1) / 100) * 100 - 1;
  const fees = Math.round(price_cents * feePct) + feeFixed;
  return {
    size: size.id, label: size.label, heightMm: H, base,
    volume_cm3: Math.round(cm3), grams: Math.round(grams),
    est_print_cents: print, est_ship_cents: ship, est_render_cents: render, est_fees_cents: fees,
    est_cost_cents: cost + fees, margin_cents: price_cents - cost - fees,
    price_cents,
  };
}

export function allPrices(geom) {
  const out = {};
  for (const s of SIZES) for (const b of BASES) out[`${s.id}:${b}`] = priceFor(geom, s.id, b).price_cents;
  return out;
}

const geomKey = (job) => `render-geom:${job.r}`;
export async function cachedGeom(job) {
  return getJSON(process.env, geomKey(job));
}
export async function saveGeom(job, value) {
  await putJSON(process.env, geomKey(job), value, 30 * 86400);
}
