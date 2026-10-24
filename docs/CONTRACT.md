# Receipts build contract (shared by all five parallel coder runs)

Read `RECEIPTS-PLAN.md` for the business. Five runs work at the same time in ONE worktree. Touch only the files your brief owns. No git commands that change state, no deploys, no contacting anyone.

## Products (single source of truth)
| key | name | price_cents | supplier |
|---|---|---|---|
| tweet | Tweet Trophy | 2900 | slant |
| milestone | Milestone Plaque | 4900 | slant |
| fullcolour | Full-Colour Receipt | 8900 | craftcloud |
| team | Team Pack | 24900 | slant (qty 10) |
Colours: black, white, red, blue, green, gold. US shipping only. Founding Edition: first 100 orders numbered 001–100.

## Site (Vercel, `site/`)
Astro static site in `site/` (Vercel Root Directory `site`, output `site/dist`), Vercel Node functions in `site/api/` (plain ESM JavaScript, no build step, Web-standard `GET`/`POST`/`PUT(request)` exports; config in `site/vercel.json`). Storage: Upstash Redis over its REST API (`KV_REST_API_URL` + `KV_REST_API_TOKEN`, from the Vercel Marketplace integration); the keys below ("KV `...`") are Redis keys, `events` is a Redis list (LPUSH + LTRIM). Uploads are capped at 4 MB on Vercel (overrides the 8 MB below). Secrets/env: `WHOP_API_KEY`, `WHOP_COMPANY_ID`, `ADMIN_TOKEN`, `PLAN_TWEET`, `PLAN_MILESTONE`, `PLAN_FULLCOLOUR`, `PLAN_TEAM`, `CHALLENGE_ENDS_AT` (ISO, default `2026-10-24T23:00:00-04:00`), `GOAL_CENTS` (default 200000).

### HTTP API (implemented by SITE-FN; consumed by SITE-UI and the Mac fleet)
- `GET /api/config` → `{plans:{tweet,milestone,fullcolour,team}, products:[{key,name,price_cents}], ends_at, goal_cents}`
- `GET /api/tweet?url=<x.com|twitter.com status url>` → `{ok, handle, author_name, text, date, url}` via `https://publish.twitter.com/oembed?url=...&omit_script=1` (strip HTML). Never returns like counts.
- `GET /api/stats` → `{revenue_cents, orders, founding_left, ends_at, goal_cents}`. From Whop `GET https://api.whop.com/api/v1/payments?company_id=...` (Bearer WHOP_API_KEY), status paid/succeeded only, cached 30 s in KV key `stats`. No key → zeros.
- `POST /api/upload` (multipart `file`, image ≤ 8 MB) → `{upload_id}`; stored in KV `upload:<id>` (base64 + content type), TTL 30 days.
- `GET /api/admin/upload/<id>` (Bearer ADMIN_TOKEN) → the image bytes.
- `GET /api/claim/<slug>` → claim JSON (public). `PUT /api/claim/<slug>` (Bearer ADMIN_TOKEN) body = claim JSON. KV `claim:<slug>`.
  Claim JSON: `{slug, handle, product:"tweet"|"milestone", tweet_url?, text?, likes?, number?, label?, name?, date?, colour, price_cents, og_image_b64?}`
- `GET /api/claim/<slug>/og.png` → the PNG from `og_image_b64` (404 if none).
- `POST /api/events` (Bearer ADMIN_TOKEN) body `{agent, text, kind?}` → appended to KV list `events` (keep last 200, each gets `ts`). `GET /api/events` → newest-first array.
- All JSON responses `content-type: application/json`; CORS not needed (same origin) except admin routes, which accept server-to-server calls.

### Checkout (SITE-UI)
Use `@whop/elements` (`loadWhop()`, `whop.checkout.create({plan, metadata, returnUrl})`) or the vanilla loader; see `docs/vendor/whop-embed-checkout.md`. Plan id comes from `/api/config` for the chosen product. `returnUrl` = `<origin>/order?ref=<order_ref>`.
**Metadata (strings only, ≤ 40 keys, each ≤ 500 chars).** Keys: `order_ref` (8-char random), `product`, `colour`, `tweet_url`, `tweet_text`, `likes`, `number`, `label`, `name`, `date`, `team`, `subline`, `upload_id`, `ship_name`, `ship_email`, `ship_line1`, `ship_line2`, `ship_city`, `ship_state`, `ship_zip`, `ship_country`, `claim_slug`, `gift_from`, `gift_note`, `source` (utm_source or "direct"). Omit empty keys.

## Print geometry (shared parameters; the browser preview and the backend generator must agree)
- Tweet Trophy: card slab 120 × 80 × 6 mm with 3 mm corner radius, on an angled stand (75°). Raised text 0.8 mm: author name (bold) + @handle, tweet text (max 280 chars, wrapped, auto-sized 4–7 mm cap height), bottom row "♥ <likes>" and date. Founding number "#NNN" small on the back.
- Milestone Plaque: slab 140 × 100 × 8 mm, raised 1 mm: big number (up to 10 chars), label under it, name/handle and date on a bottom line, thin raised border 2 mm in from the edge. Stand like above.
- Full-Colour Receipt: 150 × 100 × 4 mm panel with the screenshot as a full-colour texture on the front face, name on the base; base 150 × 30 × 15 mm.
- Team Pack: Milestone Plaque layout with `team` as the big line and `subline` under it.

## Backend on the Mac (Docker, `backend/`)
- `backend/receipts/` (BACKEND-ORDERS): python package. Public functions used by the fleet:
  `poll_whop() -> list[Order]` (new paid payments → orders, idempotent by `pay_` id, sqlite at `$RECEIPTS_DATA/receipts.db`),
  `generate(order) -> Path` (STL or 3MF; full colour → OBJ+MTL+PNG zip),
  `place(order) -> SupplierOrder` (Slant 3D v2 API for slant products, Craftcloud v5 for fullcolour; specs in `docs/vendor/*.json`),
  `sync_status() -> list[Order]`, `refund(order_id)`, `list_orders(status=None)`, `stats()`.
  CLI: `python -m receipts.worker` loops poll → generate → place → sync every 60 s. `RECEIPTS_MOCK=1` (default when keys missing) makes Whop/Slant/Craftcloud fake but runs everything else for real.
  Env: `WHOP_API_KEY`, `WHOP_COMPANY_ID`, `SLANT_API_KEY`, `SLANT_PLATFORM_ID`, `CRAFTCLOUD_API_KEY`, `SITE_URL`, `SITE_ADMIN_TOKEN`, `RECEIPTS_DATA`.
- `backend/fleet/` + `backend/marketing/` + `backend/mcp_server/` + `backend/deploy/` (FLEET): Hermes bot profiles, marketing tools, MCP server exposing receipts + marketing tools to the bots, and the isolated Docker Compose stack.
