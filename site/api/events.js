import { json, error, requireAdmin, store } from "./_lib.js";

export const MAX_EVENTS = 200;
const MAX_TEXT = 280;

export async function handleGet(request, env) {
  const raw = await store(env).lrange("events", 0, MAX_EVENTS - 1);
  const list = [];
  for (const s of raw) {
    try {
      list.push(JSON.parse(s));
    } catch {
      // skip malformed entries
    }
  }
  return json(list);
}

export async function handlePost(request, env) {
  const denied = requireAdmin(request, env);
  if (denied) return denied;
  let body;
  try {
    body = await request.json();
  } catch {
    return error(400, "invalid JSON");
  }
  if (!body || typeof body !== "object") return error(400, "body must be a JSON object");
  const agent = typeof body.agent === "string" ? body.agent.trim().slice(0, 64) : "";
  const text = typeof body.text === "string" ? body.text.trim().slice(0, MAX_TEXT) : "";
  if (!agent) return error(400, "agent required");
  if (!text) return error(400, "text required");
  const event = { ts: new Date().toISOString(), agent, text };
  if (typeof body.kind === "string" && body.kind.trim()) event.kind = body.kind.trim().slice(0, 32);

  // Newest-first Redis list: LPUSH + LTRIM 0 199 in one transaction (no read-modify-write race).
  await store(env).lpushTrim("events", JSON.stringify(event), MAX_EVENTS);
  return json({ ok: true, event });
}

export function GET(request) {
  return handleGet(request, process.env);
}

export function POST(request) {
  return handlePost(request, process.env);
}
