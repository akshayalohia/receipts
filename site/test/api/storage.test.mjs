import { test } from "node:test";
import assert from "node:assert/strict";
import { stubFetch, jsonResponse, req, bearer, ADMIN } from "./helpers.mjs";
import { store } from "../../api/_lib.js";
import * as events from "../../api/events.js";

test("Upstash REST: GET/SET EX/LPUSH+LTRIM/LRANGE commands over fetch", async () => {
  const stub = stubFetch((url, init) => {
    const cmd = JSON.parse(init.body);
    if (url.endsWith("/multi-exec")) return jsonResponse([{ result: 1 }, { result: "OK" }]);
    if (cmd[0] === "GET") return jsonResponse({ result: '{"a":1}' });
    if (cmd[0] === "LRANGE") return jsonResponse({ result: ['{"text":"b"}', '{"text":"a"}'] });
    return jsonResponse({ result: "OK" });
  });
  try {
    const s = store({ KV_REST_API_URL: "https://redis.test/", KV_REST_API_TOKEN: "tok_secret" });
    assert.equal(await s.get("k"), '{"a":1}');
    await s.set("k", "v", 60);
    await s.lpushTrim("events", "e", 200);
    assert.deepEqual(await s.lrange("events", 0, 199), ['{"text":"b"}', '{"text":"a"}']);

    assert.equal(stub.calls[0].url, "https://redis.test/");
    assert.equal(stub.calls[0].init.method, "POST");
    assert.equal(stub.calls[0].init.headers.authorization, "Bearer tok_secret");
    assert.deepEqual(JSON.parse(stub.calls[0].init.body), ["GET", "k"]);
    assert.deepEqual(JSON.parse(stub.calls[1].init.body), ["SET", "k", "v", "EX", "60"]);
    assert.equal(stub.calls[2].url, "https://redis.test/multi-exec");
    assert.deepEqual(JSON.parse(stub.calls[2].init.body), [["LPUSH", "events", "e"], ["LTRIM", "events", "0", "199"]]);
    assert.deepEqual(JSON.parse(stub.calls[3].init.body), ["LRANGE", "events", "0", "199"]);
  } finally {
    stub.restore();
  }
});

test("Upstash REST: UPSTASH_REDIS_REST_* names accepted; redis error throws", async () => {
  const stub = stubFetch(() => jsonResponse({ error: "WRONGTYPE" }, 400));
  try {
    const s = store({ UPSTASH_REDIS_REST_URL: "https://up.test", UPSTASH_REDIS_REST_TOKEN: "t" });
    await assert.rejects(() => s.get("k"));
    assert.equal(stub.calls[0].url, "https://up.test/");
  } finally {
    stub.restore();
  }
});

test("no Redis env: in-memory fallback works end to end (events)", async () => {
  const env = { ADMIN_TOKEN: ADMIN };
  const stub = stubFetch(() => { throw new Error("should not fetch"); });
  const warn = console.warn;
  console.warn = () => {};
  try {
    const r = await events.handlePost(
      req("/api/events", { method: "POST", headers: { ...bearer(), "content-type": "application/json" }, body: JSON.stringify({ agent: "a", text: "mem" }) }),
      env,
    );
    assert.equal(r.status, 200);
    const list = await (await events.handleGet(req("/api/events"), env)).json();
    assert.equal(list[0].text, "mem");
    const s = store(env);
    await s.set("ttl", "x", 1);
    assert.equal(await s.get("ttl"), "x");
    assert.equal(stub.calls.length, 0);
  } finally {
    console.warn = warn;
    stub.restore();
  }
});
