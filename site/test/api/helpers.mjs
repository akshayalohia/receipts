// Test helpers: in-memory Redis stub (same interface as api/_lib.js store) and fetch stub. No dependencies.

export class MemoryRedis {
  constructor() {
    this.map = new Map();
    this.sets = [];
  }
  async get(key) {
    const v = this.map.get(key);
    return typeof v === "string" ? v : null;
  }
  async set(key, value, ttlSeconds) {
    this.map.set(key, String(value));
    this.sets.push({ key, ttlSeconds });
  }
  async lpushTrim(key, value, max) {
    const list = Array.isArray(this.map.get(key)) ? this.map.get(key) : [];
    list.unshift(String(value));
    list.length = Math.min(list.length, max);
    this.map.set(key, list);
  }
  async lrange(key, start, stop) {
    const list = Array.isArray(this.map.get(key)) ? this.map.get(key) : [];
    return list.slice(start, stop < 0 ? list.length + stop + 1 : stop + 1);
  }
}

export const ADMIN = "test-admin-token-123";

export function makeEnv(extra = {}) {
  return { STORE: new MemoryRedis(), ADMIN_TOKEN: ADMIN, ...extra };
}

export function req(url, { method = "GET", headers = {}, body } = {}) {
  return new Request(new URL(url, "https://receipts.test").toString(), { method, headers, body });
}

export function bearer(token = ADMIN) {
  return { authorization: `Bearer ${token}` };
}

/** Replace globalThis.fetch with handler(url, init) => Response. Returns restore fn + call log. */
export function stubFetch(handler) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url ?? String(input);
    calls.push({ url, init });
    return handler(url, init);
  };
  return { calls, restore: () => (globalThis.fetch = original) };
}

export function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

export const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 1, 2, 3]);
