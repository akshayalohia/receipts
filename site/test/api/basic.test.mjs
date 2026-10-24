import { test } from "node:test";
import assert from "node:assert/strict";
import { req, makeEnv, stubFetch, jsonResponse } from "./helpers.mjs";
import { timingSafeEqual, requireAdmin, randomId } from "../../api/_lib.js";
import * as config from "../../api/config.js";
import * as tweet from "../../api/tweet.js";

test("timingSafeEqual", () => {
  assert.equal(timingSafeEqual("abc", "abc"), true);
  assert.equal(timingSafeEqual("abc", "abd"), false);
  assert.equal(timingSafeEqual("abc", "abcd"), false);
  assert.equal(timingSafeEqual("", "x"), false);
});

test("requireAdmin: 503 unset, 401 missing/wrong, null when ok", async () => {
  const r = (h) => new Request("https://x.test/", { headers: h });
  assert.equal(requireAdmin(r({}), {}).status, 503);
  assert.equal(requireAdmin(r({}), { ADMIN_TOKEN: "s3cret" }).status, 401);
  assert.equal(requireAdmin(r({ authorization: "Bearer nope" }), { ADMIN_TOKEN: "s3cret" }).status, 401);
  assert.equal(requireAdmin(r({ authorization: "s3cret" }), { ADMIN_TOKEN: "s3cret" }).status, 401);
  assert.equal(requireAdmin(r({ authorization: "Bearer s3cret" }), { ADMIN_TOKEN: "s3cret" }), null);
  const body = await requireAdmin(r({ authorization: "Bearer nope" }), { ADMIN_TOKEN: "s3cret" }).text();
  assert.ok(!body.includes("s3cret"), "never echo secret");
});

test("randomId is 12 chars [a-z0-9]", () => {
  const ids = new Set();
  for (let i = 0; i < 200; i++) {
    const id = randomId(12);
    assert.match(id, /^[a-z0-9]{12}$/);
    ids.add(id);
  }
  assert.equal(ids.size, 200);
});

test("GET /api/config: plans, products, defaults, cache 60s", async () => {
  const env = makeEnv({ PLAN_TWEET: "plan_t", PLAN_TEAM: "plan_x", WHOP_API_KEY: "sk_secret" });
  const res = await config.handleGet(req("/api/config"), env);
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type"), /application\/json/);
  assert.equal(res.headers.get("cache-control"), "public, max-age=60");
  const text = await res.text();
  assert.ok(!text.includes("sk_secret"));
  const body = JSON.parse(text);
  assert.deepEqual(body.plans, { tweet: "plan_t", milestone: null, fullcolour: null, team: "plan_x" });
  assert.deepEqual(body.products.map((p) => [p.key, p.price_cents]), [
    ["tweet", 2099], ["milestone", 2799], ["fullcolour", 8900], ["team", 15899],
  ]);
  assert.equal(body.ends_at, "2026-10-24T23:00:00-04:00");
  assert.equal(body.goal_cents, 200000);
});

test("GET /api/config: env overrides; exported GET reads process.env", async () => {
  const env = makeEnv({ CHALLENGE_ENDS_AT: "2026-10-25T00:00:00Z", GOAL_CENTS: "123400" });
  const body = await (await config.handleGet(req("/api/config"), env)).json();
  assert.equal(body.ends_at, "2026-10-25T00:00:00Z");
  assert.equal(body.goal_cents, 123400);

  const prev = process.env.PLAN_MILESTONE;
  process.env.PLAN_MILESTONE = "plan_env_m";
  try {
    const viaGet = await (await config.GET(req("/api/config"))).json();
    assert.equal(viaGet.plans.milestone, "plan_env_m");
  } finally {
    if (prev === undefined) delete process.env.PLAN_MILESTONE;
    else process.env.PLAN_MILESTONE = prev;
  }
});

test("GET /api/tweet: rejects bad hosts and paths with 400 (no fetch)", async () => {
  const stub = stubFetch(() => { throw new Error("should not fetch"); });
  try {
    for (const u of [
      "",
      "not a url",
      "https://evil.com/jack/status/20",
      "https://x.com.evil.com/jack/status/20",
      "https://www.facebook.com/x.com/jack/status/20",
      "javascript:alert(1)",
      "https://x.com/jack",
      "https://user:pw@x.com/jack/status/20",
    ]) {
      const res = await tweet.GET(req("/api/tweet?url=" + encodeURIComponent(u)));
      assert.equal(res.status, 400, u);
      assert.equal(res.headers.get("cache-control"), "no-store");
    }
    assert.equal(stub.calls.length, 0);
  } finally {
    stub.restore();
  }
});

test("GET /api/tweet: parses oEmbed html", async () => {
  const oembed = {
    url: "https://twitter.com/jack/status/20",
    author_name: "jack",
    author_url: "https://twitter.com/jack",
    html:
      '<blockquote class="twitter-tweet"><p lang="en" dir="ltr">just setting up my twttr &amp; more<br>line two <a href="https://t.co/abc">pic.twitter.com/abc</a></p>&mdash; jack (@jack) <a href="https://twitter.com/jack/status/20?ref_src=twsrc%5Etfw">March 21, 2006</a></blockquote>\n',
    like_count: 999,
  };
  const stub = stubFetch(() => jsonResponse(oembed));
  try {
    for (const host of ["x.com", "twitter.com", "mobile.twitter.com"]) {
      const res = await tweet.GET(req(`/api/tweet?url=${encodeURIComponent(`https://${host}/jack/status/20?s=46`)}`));
      assert.equal(res.status, 200, host);
      const body = await res.json();
      assert.deepEqual(body, {
        ok: true,
        handle: "jack",
        author_name: "jack",
        text: "just setting up my twttr & more\nline two pic.twitter.com/abc",
        date: "March 21, 2006",
        url: "https://x.com/jack/status/20",
      });
      assert.ok(!("likes" in body) && !("like_count" in body));
    }
    const called = new URL(stub.calls[0].url);
    assert.equal(called.origin + called.pathname, "https://publish.twitter.com/oembed");
    assert.equal(called.searchParams.get("omit_script"), "1");
    assert.equal(called.searchParams.get("url"), "https://x.com/jack/status/20");
  } finally {
    stub.restore();
  }
});

test("GET /api/tweet: upstream 404 -> 404, upstream 500 -> 502", async () => {
  let status = 404;
  const stub = stubFetch(() => new Response("nope", { status }));
  try {
    const u = "/api/tweet?url=" + encodeURIComponent("https://x.com/jack/status/20");
    assert.equal((await tweet.GET(req(u))).status, 404);
    status = 500;
    assert.equal((await tweet.GET(req(u))).status, 502);
  } finally {
    stub.restore();
  }
});
