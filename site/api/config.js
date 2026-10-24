import { PRODUCTS, json, endsAt, goalCents } from "./_lib.js";

export function handleGet(request, env) {
  const e = env || {};
  return json(
    {
      plans: {
        tweet: e.PLAN_TWEET || null,
        milestone: e.PLAN_MILESTONE || null,
        fullcolour: e.PLAN_FULLCOLOUR || null,
        team: e.PLAN_TEAM || null,
      },
      products: PRODUCTS,
      ends_at: endsAt(e),
      goal_cents: goalCents(e),
    },
    200,
    { "cache-control": "public, max-age=60" },
  );
}

export function GET(request) {
  return handleGet(request, process.env);
}
