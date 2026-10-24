// Shared helpers for the Receipts Vercel functions (plain ESM, no build step).
// Files starting with "_" are not routed by Vercel.

export const PRODUCTS = [
  { key: "tweet", name: "Tweet Trophy", price_cents: 2099 },
  { key: "milestone", name: "Milestone Plaque", price_cents: 2799 },
  { key: "fullcolour", name: "Full-Colour Receipt", price_cents: 8900 },
  { key: "team", name: "Team Pack", price_cents: 15899 },
];

export const COLOURS = ["black", "white", "red", "blue", "green", "gold"];

export const DEFAULT_ENDS_AT = "2026-10-24T23:00:00-04:00";
export const DEFAULT_GOAL_CENTS = 200000;
export const FOUNDING_TOTAL = 100;

export function endsAt(env) {
  return (env && env.CHALLENGE_ENDS_AT) || DEFAULT_ENDS_AT;
}

export function goalCents(env) {
  const n = Number(env && env.GOAL_CENTS);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : DEFAULT_GOAL_CENTS;
}

/** JSON response. Default Cache-Control is no-store. */
export function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
  });
}

export function error(status, message) {
  return json({ ok: false, error: message }, status);
}

/** Constant-time string comparison (does not short-circuit on content). */
export function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const ab = enc.encode(String(a));
  const bb = enc.encode(String(b));
  const len = Math.max(ab.length, bb.length);
  let diff = ab.length ^ bb.length;
  for (let i = 0; i < len; i++) {
    diff |= (ab[i] ?? 0) ^ (bb[i] ?? 0);
  }
  return diff === 0;
}

/**
 * Admin auth. Returns a Response to send back on failure, or null when authorised.
 * 503 if ADMIN_TOKEN is not configured, 401 if missing/wrong bearer token.
 */
export function requireAdmin(request, env) {
  const token = env && env.ADMIN_TOKEN;
  if (!token) return error(503, "admin not configured");
  const header = request.headers.get("authorization") || "";
  const m = /^Bearer\s+(.+)$/i.exec(header.trim());
  if (!m || !timingSafeEqual(m[1].trim(), token)) return error(401, "unauthorized");
  return null;
}

/** Path segment after `prefix` (e.g. "/api/claim/"), falling back to ?<name>=. */
export function pathParam(request, prefix, name) {
  const u = new URL(request.url);
  if (u.pathname.startsWith(prefix)) {
    const seg = u.pathname.slice(prefix.length).split("/")[0];
    if (seg) {
      try {
        return decodeURIComponent(seg);
      } catch {
        return "";
      }
    }
  }
  return u.searchParams.get(name) || "";
}

// ---------- Storage: Upstash Redis REST (plain fetch), in-memory fallback ----------

const memory = { map: new Map(), warned: false };

function memStore() {
  if (!memory.warned) {
    memory.warned = true;
    console.warn("[receipts] KV_REST_API_URL/KV_REST_API_TOKEN not set: using in-memory store (data is lost on restart)");
  }
  const m = memory.map;
  const live = (key) => {
    const e = m.get(key);
    if (!e) return null;
    if (e.exp && e.exp <= Date.now()) {
      m.delete(key);
      return null;
    }
    return e;
  };
  return {
    async get(key) {
      const e = live(key);
      return e && typeof e.v === "string" ? e.v : null;
    },
    async set(key, value, ttlSeconds) {
      m.set(key, { v: String(value), exp: ttlSeconds ? Date.now() + ttlSeconds * 1000 : 0 });
    },
    async lpushTrim(key, value, max) {
      const e = live(key);
      const list = e && Array.isArray(e.v) ? e.v : [];
      list.unshift(String(value));
      list.length = Math.min(list.length, max);
      m.set(key, { v: list, exp: 0 });
    },
    async lrange(key, start, stop) {
      const e = live(key);
      const list = e && Array.isArray(e.v) ? e.v : [];
      return list.slice(start, stop < 0 ? list.length + stop + 1 : stop + 1);
    },
  };
}

function restStore(url, token) {
  const base = url.replace(/\/+$/, "");
  const call = async (path, body) => {
    const res = await fetch(base + path, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data) throw new Error(`redis status ${res.status}`);
    return data;
  };
  const one = async (cmd) => {
    const data = await call("/", cmd);
    if (data.error) throw new Error("redis error");
    return data.result;
  };
  return {
    async get(key) {
      const r = await one(["GET", key]);
      return r == null ? null : String(r);
    },
    async set(key, value, ttlSeconds) {
      const cmd = ["SET", key, String(value)];
      if (ttlSeconds) cmd.push("EX", String(ttlSeconds));
      await one(cmd);
    },
    async lpushTrim(key, value, max) {
      const data = await call("/multi-exec", [
        ["LPUSH", key, String(value)],
        ["LTRIM", key, "0", String(max - 1)],
      ]);
      if (!Array.isArray(data) || data.some((r) => r && r.error)) throw new Error("redis error");
    },
    async lrange(key, start, stop) {
      const r = await one(["LRANGE", key, String(start), String(stop)]);
      return Array.isArray(r) ? r.map(String) : [];
    },
  };
}

/** Storage client for env. Tests can inject `env.STORE`. */
export function store(env) {
  const e = env || {};
  if (e.STORE) return e.STORE;
  const url = e.KV_REST_API_URL || e.UPSTASH_REDIS_REST_URL;
  const token = e.KV_REST_API_TOKEN || e.UPSTASH_REDIS_REST_TOKEN;
  return url && token ? restStore(url, token) : memStore();
}

export async function getJSON(env, key) {
  const raw = await store(env).get(key);
  if (raw == null) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function putJSON(env, key, value, ttlSeconds) {
  await store(env).set(key, JSON.stringify(value), ttlSeconds);
}

// ---------- misc ----------

export function randomId(len = 12) {
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  let out = "";
  // 252 = 7 * 36: reject higher values to avoid modulo bias.
  for (let i = 0; out.length < len; i++) {
    if (i >= bytes.length) {
      crypto.getRandomValues(bytes);
      i = 0;
    }
    if (bytes[i] < 252) out += alphabet[bytes[i] % 36];
  }
  return out;
}

export function bytesToBase64(bytes) {
  return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString("base64");
}

export function base64ToBytes(b64) {
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(b64) || b64.length % 4 === 1) throw new Error("bad base64");
  return new Uint8Array(Buffer.from(b64, "base64"));
}

export const SLUG_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/i;
