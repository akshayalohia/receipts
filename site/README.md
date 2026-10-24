# Receipts site

Astro static pages (`src/`, built to `dist/`) plus Vercel Node functions (`api/`) backed by Upstash Redis.

## Deploy on Vercel

1. Vercel → Add New → Project → import the GitHub repo.
2. **Root Directory: `site`**. Framework preset Astro; build, output and function settings come from `vercel.json` (`npm run build`, `dist`, `maxDuration` 10).
3. Storage → Marketplace → **Upstash for Redis** → create and connect it to the project. This injects `KV_REST_API_URL` and `KV_REST_API_TOKEN`.
4. Settings → Environment Variables (Production + Preview):

| name | what it is |
|---|---|
| `WHOP_API_KEY` | Whop company API key (secret). Used by `/api/stats`. Unset → stats are zeros. |
| `WHOP_COMPANY_ID` | Whop company id (`biz_...`) for the payments query. |
| `ADMIN_TOKEN` | Long random secret. Bearer token for `PUT /api/claim/*`, `POST /api/events`, `GET /api/admin/upload/*`. Unset → those return 503. |
| `PLAN_TWEET` | Whop plan id for Tweet Trophy. |
| `PLAN_MILESTONE` | Whop plan id for Milestone Plaque. |
| `PLAN_FULLCOLOUR` | Whop plan id for Full-Colour Receipt. |
| `PLAN_TEAM` | Whop plan id for Team Pack. |
| `CHALLENGE_ENDS_AT` | ISO end time for the countdown. Default `2026-10-24T23:00:00-04:00`. |
| `GOAL_CENTS` | Revenue goal in cents. Default `200000`. |
| `KV_REST_API_URL` | Upstash Redis REST URL (set by the integration; `UPSTASH_REDIS_REST_URL` also accepted). |
| `KV_REST_API_TOKEN` | Upstash Redis REST token (set by the integration; `UPSTASH_REDIS_REST_TOKEN` also accepted). |

5. Deploy. `/c/<slug>` is rewritten to `api/og-claim.js`, which serves the claim page with that claim's og:image/og:title.

Uploads are capped at 4 MB (Vercel request bodies max out at 4.5 MB).

## Local dev

```sh
npm install
npm run dev          # pages only, http://localhost:4321 (no /api)
npx vercel dev       # pages + /api; needs the Vercel CLI and a linked project
```

Without `KV_REST_API_URL`/`KV_REST_API_TOKEN` the functions use an in-memory store and log a warning (data is lost on restart).

## Test

```sh
npm test             # node --test test/api/
npm run build        # static pages to dist/
```
