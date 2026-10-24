// GET /api/render/<id> -> { state, glbUrl?, conceptUrl, prompt, prices?, sizes? }
// On the first "done" we build the fast preview GLB, measure it, and cache both (KV + CDN).
import { fal } from "@fal-ai/client";
import { json, error, pathParam } from "../_lib.js";
import { decodeJob, jobStatus, makePreview, allPrices, cachedGeom, saveGeom, SIZES } from "../_render.js";

const inflight = new Map();

async function finish(job, rawUrl, origin) {
  const hit = await cachedGeom(job);
  if (hit) return hit;
  let p = inflight.get(job.r);
  if (!p) {
    p = (async () => {
      const raw = new Uint8Array(await (await fetch(new URL(rawUrl, origin))).arrayBuffer());
      const pv = await makePreview(raw);
      console.log("preview", { r: job.r, trimmedSlab: pv.trimmedSlab, trisIn: pv.trisIn, trisOut: pv.trisOut, ms: pv.ms });
      const glbUrl = job.demo ? rawUrl : await fal.storage.upload(new Blob([pv.glb], { type: "model/gltf-binary" }));
      const value = { glbUrl, rawGlbUrl: rawUrl, geom: pv.geom };
      await saveGeom(job, value);
      return value;
    })();
    inflight.set(job.r, p);
    p.catch(() => inflight.delete(job.r));
  }
  return p;
}

export async function GET(request) {
  const id = pathParam(request, "/api/render/", "id");
  const job = decodeJob(id);
  if (!job) return error(404, "unknown render");
  const base = { conceptUrl: job.c, prompt: job.p ?? null };
  try {
    let rawUrl;
    if (job.demo) rawUrl = "/examples/dog.glb";
    else {
      const s = await jobStatus(job);
      if (s.state !== "done") return json({ ...s, ...base });
      rawUrl = s.glbUrl;
    }
    const f = await finish(job, rawUrl, new URL(request.url).origin);
    return json(
      { state: "done", ...base, glbUrl: f.glbUrl, rawGlbUrl: f.rawGlbUrl, sizes: SIZES, prices: allPrices(f.geom) },
      200,
      { "cache-control": "public, max-age=60, s-maxage=86400" },
    );
  } catch (e) {
    console.error("render status failed", String(e?.message || e));
    return json({ state: "failed", error: "status check failed", ...base }, 502);
  }
}
