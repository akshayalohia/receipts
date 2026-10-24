import { test } from "node:test";
import assert from "node:assert/strict";
import { req, makeEnv, bearer, PNG_BYTES } from "./helpers.mjs";
import * as upload from "../../api/upload.js";
import * as adminUpload from "../../api/admin/upload/[id].js";
import * as claim from "../../api/claim/[slug].js";
import * as og from "../../api/claim/[slug]/og.png.js";
import * as events from "../../api/events.js";

function form(bytes, type, name = "f.png") {
  const fd = new FormData();
  if (bytes) fd.append("file", new File([bytes], name, { type }));
  return fd;
}

test("POST /api/upload -> Redis -> GET /api/admin/upload/<id> round-trip", async () => {
  const env = makeEnv();
  const res = await upload.handlePost(req("/api/upload", { method: "POST", body: form(PNG_BYTES, "image/png") }), env);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("cache-control"), "no-store");
  const { upload_id } = await res.json();
  assert.match(upload_id, /^[a-z0-9]{12}$/);
  const put = env.STORE.sets.find((p) => p.key === `upload:${upload_id}`);
  assert.equal(put.ttlSeconds, 30 * 24 * 60 * 60);
  const stored = JSON.parse(env.STORE.map.get(`upload:${upload_id}`));
  assert.equal(stored.content_type, "image/png");

  const path = `/api/admin/upload/${upload_id}`;
  const get = (url, e = env, headers = bearer()) => adminUpload.handleGet(req(url, { headers }), e);

  // Auth
  assert.equal((await get(path, env, {})).status, 401);
  assert.equal((await get(path, env, bearer("wrong"))).status, 401);
  assert.equal((await get(path, { STORE: env.STORE })).status, 503);

  const ok = await get(path);
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("content-type"), "image/png");
  assert.equal(ok.headers.get("cache-control"), "no-store");
  assert.deepEqual(new Uint8Array(await ok.arrayBuffer()), PNG_BYTES);

  // id via ?id= (Vercel dynamic-segment query) also works
  assert.equal((await get(`/api/admin/upload-x?id=${upload_id}`)).status, 200);

  assert.equal((await get("/api/admin/upload/zzzzzzzzzzzz")).status, 404);
  assert.equal((await get("/api/admin/upload/..%2Fetc")).status, 400);
});

test("POST /api/upload validation: missing, wrong type, spoofed type, too big (4 MB)", async () => {
  const env = makeEnv();
  const post = (body, headers) => upload.handlePost(req("/api/upload", { method: "POST", body, headers }), env);
  assert.equal(upload.MAX_BYTES, 4 * 1024 * 1024);
  assert.equal((await post(form(null))).status, 400);
  assert.equal((await post(form(new TextEncoder().encode("GIF89a..."), "image/gif", "a.gif"))).status, 415);
  assert.equal((await post(form(new TextEncoder().encode("<svg/>"), "image/png"))).status, 415);
  const big = new Uint8Array(4 * 1024 * 1024 + 1);
  big.set(PNG_BYTES);
  const tooBig = await post(form(big, "image/png"));
  assert.equal(tooBig.status, 413);
  assert.match((await tooBig.json()).error, /4 MB/);
  const justFits = new Uint8Array(4 * 1024 * 1024);
  justFits.set(PNG_BYTES);
  assert.equal((await post(form(justFits, "image/png"))).status, 200);
  env.STORE.map.clear();
  const notForm = await post("{}", { "content-type": "application/json" });
  assert.equal(notForm.status, 400);
  assert.equal(env.STORE.map.size, 0);
});

const CLAIM = {
  handle: "jack",
  product: "tweet",
  tweet_url: "https://x.com/jack/status/20",
  text: "just setting up my twttr",
  likes: "12000",
  date: "March 21, 2006",
  colour: "gold",
  price_cents: 2900,
  og_image_b64: Buffer.from(PNG_BYTES).toString("base64"),
};

test("PUT/GET /api/claim/<slug> round-trip + og.png", async () => {
  const env = makeEnv();
  const put = (body, headers = bearer(), slug = "jack-first") =>
    claim.handlePut(req(`/api/claim/${encodeURIComponent(slug)}`, {
      method: "PUT", headers: { ...headers, "content-type": "application/json" },
      body: typeof body === "string" ? body : JSON.stringify(body),
    }), env);
  const getClaim = (slug) => claim.handleGet(req(`/api/claim/${slug}`), env);
  const getOg = (slug) => og.handleGet(req(`/api/claim/${slug}/og.png`), env);

  assert.equal((await put(CLAIM, {})).status, 401);
  assert.equal((await put(CLAIM, bearer("nope"))).status, 401);
  assert.equal((await put("{not json")).status, 400);
  assert.equal((await put({ ...CLAIM, product: "fullcolour" })).status, 400);
  assert.equal((await put({ ...CLAIM, colour: "pink" })).status, 400);
  assert.equal((await put({ ...CLAIM, price_cents: "29" })).status, 400);
  assert.equal((await put(CLAIM, bearer(), "bad slug!")).status, 400);

  // 404 before stored
  assert.equal((await getClaim("jack-first")).status, 404);
  assert.equal((await getOg("jack-first")).status, 404);

  const ok = await put({ ...CLAIM, slug: "ignored-other" });
  assert.equal(ok.status, 200);
  assert.deepEqual(await ok.json(), { ok: true, slug: "jack-first" });

  const got = await getClaim("jack-first");
  assert.equal(got.status, 200);
  assert.match(got.headers.get("content-type"), /application\/json/);
  const body = await got.json();
  const { og_image_b64, ...rest } = CLAIM;
  assert.deepEqual(body, { slug: "jack-first", ...rest });

  const img = await getOg("jack-first");
  assert.equal(img.status, 200);
  assert.equal(img.headers.get("content-type"), "image/png");
  assert.deepEqual(new Uint8Array(await img.arrayBuffer()), PNG_BYTES);

  // Claim without og image -> og.png 404
  const { og_image_b64: _drop, ...noImg } = CLAIM;
  assert.equal((await put(noImg, bearer(), "plain")).status, 200);
  assert.equal((await getOg("plain")).status, 404);
});

test("POST/GET /api/events: auth, validation, newest-first, cap 200, text 280", async () => {
  const env = makeEnv();
  const post = (body, headers = bearer(), e = env) =>
    events.handlePost(req("/api/events", {
      method: "POST", headers: { ...headers, "content-type": "application/json" }, body: JSON.stringify(body),
    }), e);

  assert.equal((await post({ agent: "a", text: "t" }, {})).status, 401);
  assert.equal((await post({}, bearer(), { STORE: env.STORE })).status, 503);
  assert.equal((await post({ text: "t" })).status, 400);
  assert.equal((await post({ agent: "a" })).status, 400);

  const empty = await events.handleGet(req("/api/events"), env);
  assert.equal(empty.headers.get("cache-control"), "no-store");
  assert.deepEqual(await empty.json(), []);

  const r1 = await post({ agent: "scout", text: "x".repeat(400), kind: "post" });
  assert.equal(r1.status, 200);
  const e1 = (await r1.json()).event;
  assert.equal(e1.text.length, 280);
  assert.equal(e1.kind, "post");
  assert.ok(!Number.isNaN(Date.parse(e1.ts)));

  for (let i = 0; i < 205; i++) await post({ agent: "bot", text: `msg ${i}` });
  const list = await (await events.handleGet(req("/api/events"), env)).json();
  assert.equal(list.length, 200);
  assert.equal(list[0].text, "msg 204");
  assert.equal(list[199].text, "msg 5");
});
