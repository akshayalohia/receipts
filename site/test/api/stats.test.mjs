import { test } from "node:test";
import assert from "node:assert/strict";
import { req, makeEnv, stubFetch, jsonResponse } from "./helpers.mjs";
import * as stats from "../../api/stats.js";

const WHOP_ENV = { WHOP_API_KEY: "whop_sk_secret", WHOP_COMPANY_ID: "biz_123" };
const get = (env) => stats.handleGet(req("/api/stats"), env);

test("GET /api/stats: no key -> zeros, cache 15s, no fetch", async () => {
  const stub = stubFetch(() => { throw new Error("should not fetch"); });
  try {
    const res = await get(makeEnv());
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("cache-control"), "public, max-age=15");
    assert.deepEqual(await res.json(), {
      revenue_cents: 0, orders: 0, founding_left: 100,
      ends_at: "2026-10-24T18:45:00-04:00", goal_cents: 200000,
    });
    assert.equal(stub.calls.length, 0);
  } finally {
    stub.restore();
  }
});

test("GET /api/stats: page-number pagination, paid filter, dollars->cents, Redis cache", async () => {
  const pages = {
    1: {
      data: [
        { id: "pay_1", status: "paid", final_amount: 29.0 },
        { id: "pay_2", status: "paid", substatus: "succeeded", total: 49 },
        { id: "pay_3", status: "open", final_amount: 89 },
        { id: "pay_4", status: "refunded", final_amount: 29 },
      ],
      pagination: { current_page: 1, total_pages: 2 },
    },
    2: {
      data: [
        { id: "pay_5", status: "succeeded", amount: 249.0 },
        { id: "pay_6", status: "draft", substatus: "succeeded", final_amount: 0.1 },
      ],
      pagination: { current_page: 2, total_pages: 2 },
    },
  };
  const stub = stubFetch((url, init) => {
    const u = new URL(url);
    assert.equal(u.origin + u.pathname, "https://api.whop.com/api/v1/payments");
    assert.equal(u.searchParams.get("account_id"), "biz_123");
    assert.equal(init.headers.authorization, "Bearer whop_sk_secret");
    return jsonResponse(pages[u.searchParams.get("page")]);
  });
  const env = makeEnv(WHOP_ENV);
  try {
    const res = await get(env);
    const text = await res.text();
    assert.ok(!text.includes("whop_sk_secret"));
    const body = JSON.parse(text);
    assert.equal(body.orders, 4);
    assert.equal(body.revenue_cents, 2900 + 4900 + 24900 + 10);
    assert.equal(body.founding_left, 96);
    assert.equal(stub.calls.length, 2);

    // Cached in key "stats" with EX 60: second call does not hit Whop.
    assert.ok(env.STORE.map.has("stats"));
    assert.equal(env.STORE.sets.find((s) => s.key === "stats").ttlSeconds, 60);
    const again = await (await get(env)).json();
    assert.equal(again.revenue_cents, body.revenue_cents);
    assert.equal(stub.calls.length, 2);
  } finally {
    stub.restore();
  }
});

test("GET /api/stats: cursor pagination via page_info, stops at 20 pages", async () => {
  let n = 0;
  const stub = stubFetch((url) => {
    n += 1;
    const after = new URL(url).searchParams.get("after");
    if (n > 1) assert.equal(after, `c${n - 1}`);
    return jsonResponse({
      data: [{ id: `pay_${n}`, status: "paid", final_amount: 1.5 }],
      page_info: { has_next_page: true, end_cursor: `c${n}` },
    });
  });
  try {
    const body = await (await get(makeEnv(WHOP_ENV))).json();
    assert.equal(stub.calls.length, 20);
    assert.equal(body.orders, 20);
    assert.equal(body.revenue_cents, 3000);
  } finally {
    stub.restore();
  }
});

test("GET /api/stats: founding_left floors at 0; Whop error -> stale cache or zeros", async () => {
  const many = Array.from({ length: 130 }, (_, i) => ({ id: `pay_${i}`, status: "paid", final_amount: 29 }));
  let fail = false;
  const stub = stubFetch(() => (fail ? new Response("boom whop_sk_secret", { status: 500 }) : jsonResponse({ data: many })));
  const env = makeEnv(WHOP_ENV);
  try {
    const body = await (await get(env)).json();
    assert.equal(body.orders, 130);
    assert.equal(body.founding_left, 0);

    // Expire cache, then fail upstream: stale numbers served, nothing leaked.
    const cached = JSON.parse(env.STORE.map.get("stats"));
    cached.at = 0;
    env.STORE.map.set("stats", JSON.stringify(cached));
    fail = true;
    const res = await get(env);
    const text = await res.text();
    assert.equal(res.status, 200);
    assert.ok(!text.includes("whop_sk_secret"));
    assert.equal(JSON.parse(text).orders, 130);

    const fresh = await (await get(makeEnv(WHOP_ENV))).json();
    assert.equal(fresh.orders, 0);
  } finally {
    stub.restore();
  }
});
