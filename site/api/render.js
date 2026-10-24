// /api/render: one function (Vercel Hobby caps a deployment at 12 functions).
//   POST /api/render            multipart prompt?/photo?  -> { id, conceptUrl }   (new render)
//   POST /api/render/edit       { id, instruction }       -> { id, conceptUrl }   (re-sculpt)
//   GET  /api/render/<id>                                 -> { state, glbUrl?, prices? ... }
// vercel.json rewrites /api/render/:id -> /api/render?id=:id
import { fal } from "@fal-ai/client";
import { json, error } from "./_lib.js";
import { decodeJob, editConcept, encodeJob, makeConcept, MODELS, start3d, uploadPhoto, spendGuard, jobStatus, makePreview, allPrices, cachedGeom, saveGeom, SIZES, exaReference, getReference, saveReference } from "./_render.js";

const idOf = (request) => new URL(request.url).searchParams.get("id") || "";

export async function POST(request) {
  return idOf(request) === "edit" ? edit(request) : create(request);
}

export async function GET(request) {
  return status(request);
}

async function create(request) {
  if (!process.env.FAL_KEY) return error(503, "The 3D studio is warming up. Pick a preset for now, or try again in a few minutes.");
  let prompt = "", photo = null;
  try {
    const form = await request.formData();
    prompt = String(form.get("prompt") || "").trim();
    const f = form.get("photo");
    if (f && typeof f === "object" && f.size > 0) photo = f;
  } catch {
    return error(400, "Send a description and/or a photo.");
  }
  if (!prompt && !photo) return error(400, "Describe what you want, or upload a photo.");
  const blocked = await spendGuard(request);
  if (blocked) return error(429, blocked);
  try {
    // Exa lookup runs in parallel with the photo upload, so it adds ~1 s at most.
    const [photoUrl, reference] = await Promise.all([photo ? uploadPhoto(photo) : undefined, exaReference(prompt)]);
    const conceptUrl = await makeConcept({ prompt, photoUrl, reference });
    const r = await start3d(conceptUrl);
    await saveReference(r, reference).catch(() => {});
    return json({ id: encodeJob({ r, c: conceptUrl, p: prompt || undefined, m: MODELS.imageTo3d }), conceptUrl, reference });
  } catch (e) {
    const msg = String(e?.message || e);
    console.error("render failed", msg);
    if (/safety|nsfw|content/i.test(msg)) return error(422, "We can't print that one. Try a different idea.");
    if (/photo must/.test(msg)) return error(400, msg);
    return error(502, "Render failed, please try again.");
  }
}

async function edit(request) {
  if (!process.env.FAL_KEY) return error(503, "Edits are offline for a few minutes.");
  const body = await request.json().catch(() => null);
  const job = body?.id ? decodeJob(String(body.id)) : null;
  const instruction = String(body?.instruction || "").trim().slice(0, 300);
  if (!job || !instruction) return error(400, "need id and instruction");
  const blocked = await spendGuard(request);
  if (blocked) return error(429, blocked);
  try {
    const src = job.demo ? new URL(job.c, request.url).toString() : job.c;
    const reference = await exaReference(instruction);
    const conceptUrl = await editConcept(src, instruction, reference);
    const r = await start3d(conceptUrl);
    // Keep the original research if the edit itself named nothing new.
    const kept = reference || (await getReference(job).catch(() => null));
    await saveReference(r, kept).catch(() => {});
    const p = [job.p, instruction].filter(Boolean).join(" / ").slice(0, 600);
    return json({ id: encodeJob({ r, c: conceptUrl, p, m: MODELS.imageTo3d }), conceptUrl, reference: kept });
  } catch (e) {
    const blockedMsg = /safety|nsfw|content/i.test(String(e?.message));
    return error(blockedMsg ? 422 : 502, blockedMsg ? "We can't print that change." : "Edit failed, please try again.");
  }
}

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

async function status(request) {
  const id = idOf(request);
  const job = decodeJob(id);
  if (!job) return error(404, "unknown render");
  const reference = job.demo ? null : await getReference(job).catch(() => null);
  const base = { conceptUrl: job.c, prompt: job.p ?? null, reference };
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
