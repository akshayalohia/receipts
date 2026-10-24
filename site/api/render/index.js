// POST /api/render  multipart: prompt?, photo?  -> { id, conceptUrl } in ~3-6 s.
// The 3D mesh keeps building on fal; poll GET /api/render/<id>.
import { json, error } from "../_lib.js";
import { encodeJob, makeConcept, MODELS, start3d, uploadPhoto, spendGuard } from "../_render.js";

export async function POST(request) {
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
    const photoUrl = photo ? await uploadPhoto(photo) : undefined;
    const conceptUrl = await makeConcept({ prompt, photoUrl });
    const r = await start3d(conceptUrl);
    return json({ id: encodeJob({ r, c: conceptUrl, p: prompt || undefined, m: MODELS.imageTo3d }), conceptUrl });
  } catch (e) {
    const msg = String(e?.message || e);
    console.error("render failed", msg);
    if (/safety|nsfw|content/i.test(msg)) return error(422, "We can't print that one. Try a different idea.");
    if (/photo must/.test(msg)) return error(400, msg);
    return error(502, "Render failed, please try again.");
  }
}
