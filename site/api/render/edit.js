// POST /api/render/edit { id, instruction } -> { id, conceptUrl } (a new render job, ~30 s)
import { json, error } from "../_lib.js";
import { decodeJob, editConcept, encodeJob, MODELS, start3d, spendGuard } from "../_render.js";

export async function POST(request) {
  if (!process.env.FAL_KEY) return error(503, "Edits are offline for a few minutes.");
  const body = await request.json().catch(() => null);
  const job = body?.id ? decodeJob(String(body.id)) : null;
  const instruction = String(body?.instruction || "").trim().slice(0, 300);
  if (!job || !instruction) return error(400, "need id and instruction");
  const blocked = await spendGuard(request);
  if (blocked) return error(429, blocked);
  try {
    const src = job.demo ? new URL(job.c, request.url).toString() : job.c;
    const conceptUrl = await editConcept(src, instruction);
    const r = await start3d(conceptUrl);
    const p = [job.p, instruction].filter(Boolean).join(" / ").slice(0, 600);
    return json({ id: encodeJob({ r, c: conceptUrl, p, m: MODELS.imageTo3d }), conceptUrl });
  } catch (e) {
    const blockedMsg = /safety|nsfw|content/i.test(String(e?.message));
    return error(blockedMsg ? 422 : 502, blockedMsg ? "We can't print that change." : "Edit failed, please try again.");
  }
}
