import { json, error, randomId, bytesToBase64, putJSON } from "./_lib.js";

// Vercel caps request bodies at 4.5 MB, so the file limit is 4 MB.
export const MAX_BYTES = 4 * 1024 * 1024;
const TOO_BIG = "file too large (max 4 MB)";
const TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
export const TTL_SECONDS = 30 * 24 * 60 * 60;

function sniffType(b) {
  if (b.length >= 8 && b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return "image/png";
  if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (
    b.length >= 12 &&
    b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x46 &&
    b[8] === 0x57 && b[9] === 0x45 && b[10] === 0x42 && b[11] === 0x50
  ) return "image/webp";
  return null;
}

export async function handlePost(request, env) {
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BYTES + 64 * 1024) return error(413, TOO_BIG);

  let form;
  try {
    form = await request.formData();
  } catch {
    return error(400, "expected multipart/form-data with a file field");
  }
  const file = form.get("file");
  if (!file || typeof file === "string" || typeof file.arrayBuffer !== "function") {
    return error(400, "missing file");
  }
  if (file.size > MAX_BYTES) return error(413, TOO_BIG);
  if (!file.size) return error(400, "empty file");
  const declaredType = String(file.type || "").toLowerCase();
  if (!TYPES.has(declaredType)) return error(415, "only png, jpeg or webp images");

  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length > MAX_BYTES) return error(413, TOO_BIG);
  const sniffed = sniffType(bytes);
  if (sniffed !== declaredType) return error(415, "file content is not a png, jpeg or webp image");

  const id = randomId(12);
  await putJSON(
    env,
    `upload:${id}`,
    { content_type: sniffed, b64: bytesToBase64(bytes), size: bytes.length, ts: new Date().toISOString() },
    TTL_SECONDS,
  );
  return json({ upload_id: id });
}

export function POST(request) {
  return handlePost(request, process.env);
}
