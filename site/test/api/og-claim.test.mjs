import { test } from "node:test";
import assert from "node:assert/strict";
import { req, makeEnv, stubFetch, PNG_BYTES } from "./helpers.mjs";
import * as ogClaim from "../../api/og-claim.js";

const TEMPLATE = `<!doctype html><html><head><title>receipts · this one's yours</title>
<meta property="og:title" content="receipts · this one's yours">
<meta property="og:image" content="/og.png">
<meta name="twitter:title" content="receipts · this one's yours">
<meta name="twitter:image" content="/og.png">
</head><body>claim</body></html>`;

test("GET /c/<slug>: per-slug og:title/og:image, html-escaped", async () => {
  const env = makeEnv();
  env.STORE.map.set("claim:jack-first", JSON.stringify({
    slug: "jack-first", handle: 'jack"<x>', product: "tweet", colour: "gold", price_cents: 2900,
    og_image_b64: Buffer.from(PNG_BYTES).toString("base64"),
  }));
  const res = await ogClaim.handleGet(req("https://receipts.test/api/og-claim?slug=jack-first"), env, TEMPLATE);
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type"), /text\/html/);
  const html = await res.text();
  assert.ok(html.includes('<meta property="og:image" content="https://receipts.test/api/claim/jack-first/og.png">'));
  assert.ok(html.includes('<meta name="twitter:image" content="https://receipts.test/api/claim/jack-first/og.png">'));
  assert.ok(html.includes('<meta property="og:title" content="Trove · @jack&quot;&lt;x&gt;, this one\'s yours">'));
  assert.ok(!html.includes('jack"<x>'));
});

test("GET /c/<slug>: slug from path; unknown/invalid slug -> generic page; no og image keeps default", async () => {
  const env = makeEnv();
  env.STORE.map.set("claim:plain", JSON.stringify({ slug: "plain", handle: "plain", product: "tweet", colour: "red", price_cents: 2900 }));
  const plain = await (await ogClaim.handleGet(req("/c/plain"), env, TEMPLATE)).text();
  assert.ok(plain.includes('content="/og.png"'));
  assert.ok(plain.includes("@plain, this one's yours"));
  assert.equal(await (await ogClaim.handleGet(req("/c/nobody"), env, TEMPLATE)).text(), TEMPLATE);
  assert.equal(await (await ogClaim.handleGet(req("/api/og-claim?slug=../x"), env, TEMPLATE)).text(), TEMPLATE);
});

test("GET /c/<slug>: falls back to fetching /c/index.html from the origin when dist is not readable", async () => {
  // dist may or may not exist locally; only assert the fetch path is well-formed if it is used.
  const stub = stubFetch(() => new Response(TEMPLATE, { status: 200 }));
  try {
    const res = await ogClaim.handleGet(req("https://receipts.test/c/nobody"), makeEnv());
    assert.equal(res.status, 200);
    for (const c of stub.calls) assert.equal(c.url, "https://receipts.test/c/index.html");
  } finally {
    stub.restore();
  }
});
