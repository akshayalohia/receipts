import { error, getJSON, base64ToBytes } from "../../_lib.js";
import { claimSlug } from "../[slug].js";

export async function handleGet(request, env) {
  const slug = claimSlug(request);
  if (!slug) return error(400, "invalid slug");
  const claim = await getJSON(env, `claim:${slug}`);
  if (!claim || !claim.og_image_b64) return error(404, "not found");
  let bytes;
  try {
    bytes = base64ToBytes(claim.og_image_b64);
  } catch {
    return error(404, "not found");
  }
  return new Response(bytes, {
    status: 200,
    headers: {
      "content-type": "image/png",
      "cache-control": "no-store",
      "content-length": String(bytes.length),
    },
  });
}

export function GET(request) {
  return handleGet(request, process.env);
}
