import { error, requireAdmin, getJSON, base64ToBytes, pathParam } from "../../_lib.js";

const ID_RE = /^[a-z0-9]{12}$/;

export async function handleGet(request, env) {
  const denied = requireAdmin(request, env);
  if (denied) return denied;
  const id = pathParam(request, "/api/admin/upload/", "id");
  if (!ID_RE.test(id)) return error(400, "invalid upload id");
  const rec = await getJSON(env, `upload:${id}`);
  if (!rec || !rec.b64) return error(404, "not found");
  const bytes = base64ToBytes(rec.b64);
  return new Response(bytes, {
    status: 200,
    headers: {
      "content-type": rec.content_type || "application/octet-stream",
      "cache-control": "no-store",
      "content-length": String(bytes.length),
    },
  });
}

export function GET(request) {
  return handleGet(request, process.env);
}
