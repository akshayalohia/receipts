# App, voice, agent backend & sponsor integrations (2026-10-24)

## Picks
| Decision | Pick | Runner-up |
|---|---|---|
| 1 App | **Lovable mobile-first web app / PWA** (Lovable Cloud/Supabase) | Capacitor wrapper of the same code (post-hackathon); Expo rebuild only if native features are needed |
| 2 Voice | **OpenAI GPT-Live-1, client delegation → Hermes** | gpt-realtime-2 with a `send_to_agent` function; Gemini 3.8 Live if cost matters |
| 3 Backend | **Thin FastAPI + Hermes API server + Kanban fleet + one FastMCP "factory" server** | App calls Hermes directly (no, it would expose keys and leave no webhook home) |
| 4 Whop | **Checkout config per quote + embedded Checkout element + `payment.succeeded` webhook** | Hosted `purchase_url` redirect |
| 5 Exa | **Exa MCP for agents + REST `/search`/`/contents` in tools** | Exa Agent API for lead lists |
| 6 Terac | **Include one async human task (design QA / customer interview)** as a demo moment | Skip |

## 1. Lovable app
- New Lovable projects (since May 13 2026) run on **TanStack Start** (SSR). Older ones run React+Vite. Backend is Lovable Cloud (Supabase-based) or your own Supabase. **No native/React Native output.** FAQ says use a PWA or a Capacitor wrapper built outside Lovable. Capacitor native plugins don't work inside the published Lovable app.
- Camera: `<input type="file" accept="image/*" capture="environment">` → Supabase Storage. Works in iOS/Android browsers with no permissions code. Use `getUserMedia` only for a live viewfinder (needs HTTPS).
- 3D preview: **`<model-viewer>`** (GLB, orbit, AR via Quick Look/Scene Viewer). One tag, easy for Lovable to generate. react-three-fiber only if you need custom editing.
- Live print video: HLS (`hls.js`) or WebRTC/WHEP from the Pi (that's the printer worker's topic). Chat: a Supabase `messages` table + Realtime subscription. Agent replies are written by the backend.

## 2. Realtime voice (Oct 2026)
| Option | Price | Browser WebRTC | Tools/handoff | Notes |
|---|---|---|---|---|
| **GPT-Live-1** (Sep 10 2026) | $0.05/min voice + backend billed separately | Yes (server mints session) | Built-in **delegation**. "Client delegation" connects *any* agent | Full duplex. +30 pp Full-Duplex-Bench vs realtime-2.1 (OpenAI claim) |
| gpt-realtime-2 | audio $32/$64 per 1M tokens ≈ $0.05–0.08/min+ | Yes, ephemeral `client_secrets` | Function calling | Cost grows each turn |
| Gemini 3.8 Live | ~$0.005/min in, $0.018/min out | WebSocket + ephemeral tokens | Async function calling | Cheapest. Google says #1 on Artificial Analysis S2S (Extended Thinking) |
| ElevenLabs Agents | $0.08/min + LLM | Widget/SDK | Client/server tools | Best voices, extra hop |
| LiveKit Agents | $0.01/min session + models (~$0.048 example) | Yes | Full code control | You run an agent worker. Too much for 10 h |
| Vapi | $0.05/min + providers ≈ $0.08–0.13 | Web SDK | Tools | Phone-centric |
- Latency: no independent ms numbers found; speech-to-speech models skip STT→LLM→TTS (inferred fastest).
- **Pattern:** the voice model handles the conversation and delegates/calls `send_to_agent(text, order_id)`. FastAPI forwards that to Hermes `/v1/runs` and returns the result for the voice model to speak. Hermes shouldn't speak directly: its turns take seconds–minutes, so the voice layer fills the wait and mirrors the transcript into chat.
- Gotcha: GPT-Live is 6 weeks old. Keep a text-chat fallback. Mobile Safari needs a user tap before audio plays.

## 3. Hermes Agent backend
- **API server** (`API_SERVER_ENABLED=true`, `:8642`): OpenAI-compatible `/v1/chat/completions`, `/v1/responses`, plus **`POST /v1/runs`** → `run_id`, with `GET /v1/runs/{id}/events` (SSE tool progress + deltas, 10 s keepalives) and an `Idempotency-Key` header. Pass `session_id` = order id for continuity.
- **Fleet = profiles** (`hermes profile create sales --clone`). Each has its own model, SOUL.md, skills, `.env`. One multiplexing gateway (default on) serves `/p/<profile>/v1/...`, each with its own `API_SERVER_KEY`.
- Roles: `intake` (designer + orchestrator, frontier model, customer-facing), `sales` (quote → Whop), `production` (slice/print/monitor), `support`, `growth` (Exa), `finance` (Whop MCP). Workers use cheaper models (Kanban docs recommend this split).
- **Coordination = Kanban** (`~/.hermes/kanban.db`, shared across profiles). The orchestrator calls `kanban_create` and the dispatcher spawns the assignee. Create is idempotent (`--idempotency-key`). Gotcha: the dispatcher ticks every **60 s**. Nudge it with dashboard REST `POST /api/plugins/kanban/dispatch` (localhost only, unauthenticated: never expose it). Customer chat goes straight to `intake` via `/v1/runs`. Kanban is for back-office handoffs.
- **Cron**: daily growth/finance jobs.
- **Custom tools: FastMCP server** (streamable HTTP, e.g. `:9000/mcp`) exposing `generate_3d`, `slice`, `print_start/status`, `camera_url`, `create_quote`, `update_order`. Each profile lists it under `mcp_servers` and uses per-server tool whitelists (production gets printer tools, sales gets quotes). Beats a Hermes plugin (`ctx.register_tool`): standalone-testable, shared by all profiles.
- **Architecture:** Lovable app ⇄ Supabase (auth, `orders`, `messages`, storage, Realtime) ⇄ **FastAPI** on the laptop via Cloudflare Tunnel. FastAPI routes: `/chat` → Hermes runs, writing SSE output to `messages`; `/voice/session`; `/webhooks/whop`. FastAPI ⇄ Hermes ⇄ FastMCP ⇄ Pi/printer. The browser never holds the Hermes, Whop or OpenAI keys.

## 4. Whop
- Flow:
  1. The `sales` agent's `create_quote` calls the Create Checkout Configuration API with an inline `plan` (one_time, `initial_price`) and `metadata {order_id}`. It returns `ch_…` + `purchase_url`.
  2. Save it to `orders`. The app renders `@whop/elements-react` `<Checkout checkoutConfiguration="ch_…" returnUrl=…>`. No key in the browser.
  3. Whop POSTs **`payment.succeeded`** (Standard Webhooks: `webhook-id/-timestamp/-signature`, `ws_` secret) to FastAPI. FastAPI verifies it, marks the order paid, and runs `kanban create --assignee production --idempotency-key pay_…`.
- **Fulfil only from the webhook.** `onComplete`/`returnUrl?status=` can be spoofed or replayed. Use the sandbox + test cards for the demo.
- Whop MCP `https://mcp.whop.com/mcp`: browser OAuth, two-step `mcp_confirmation_token` for writes. Fine for the `finance` bot's reads/reports. Use the REST API key in FastMCP for the money path. A docs MCP is at `docs.whop.com/mcp`.
- Fees: 2.7% + $0.30 domestic card, +1.5% international, +1% FX. ACH 1.5% (max $5). Payouts: next-day ACH $2.50, instant 4% + $2.50. Disputes $15.

## 5. Exa
- Pricing (pay-as-you-go, $10 free/month): Search $4–7/1k, Contents $1/1k pages, Answer $5/1k, Deep $12–15/1k, Monitors $15/1k, Agent $0.012–$1/run (list-building/enrichment). Websets exists for large lead datasets (pricing not verified).
- MCP: hosted `https://mcp.exa.ai/mcp` (no key needed to start) or `npx exa-mcp-server`.
- Uses: `/search` with `includeDomains` Printables/Thingiverse/MakerWorld before generating (check licences); `/answer` "iPhone 16 Pro dimensions"; competitor pricing (sales); Agent/Websets B2B leads (growth).

## 6. Terac
- MCP at `https://terac.com/api/mcp` (API key or OAuth). Tools: `terac_get_context`, `terac_request_feasibility`, `terac_create_opportunity`, `terac_launch_draft_opportunity`, `terac_get_submissions`, `terac_approve/reject_submission`.
- Price = participant payout you set + platform fee, charged only on approved submissions.
- **Pricing is done by a human, typically ~1 h**, so it can't sit in the live order loop.
- Realistic uses: an expert QA review of a design, or recruiting 3–5 customer interviews (growth bot). Its site lists "physical-evidence tasks", but local print removal/delivery is unverified.
- Worth it: Terac is the host, and showing "the agent hires a human when blocked" fits the zero-human brief. Launch the request early in the day.

## Hackathon risks
- Bad wifi breaks voice and the tunnel. Have a text fallback and a pre-recorded print feed.
- GPT-Live/Whop Elements are new SDKs. Pin versions.
- Kanban's 60 s tick: nudge dispatch.
- Lovable TanStack SSR: put the `<model-viewer>`/Whop element in client-only components.

Out of scope (one line): 3D generation, slicing, Pi streaming and Bambu control belong to other topics.

## Sources
- docs.lovable.dev/introduction/faq · /tips-tricks/external-deployment-hosting · /tips-tricks/npm-packages · /features/cloud
- openai.com/index/introducing-gpt-live-1-in-the-api · developers.openai.com/api/docs/guides/live · /models/gpt-realtime-2 · /guides/voice-webrtc
- ai.google.dev/gemini-api/docs/pricing · blog.google (Gemini 3.8 Live, Sep 15 2026) · ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens
- elevenlabs.io/blog/weve-lowered-api-agents-pricing-and-introduced-pay-as-you-go · livekit.com/pricing · micdrop.dev/blog/vapi-pricing · costperoutput.com/openai-realtime-api-pricing
- docs.whop.com/developer/guides/{accept-payments,embed-checkout,webhooks,ai_and_mcp} · /api-reference/beta/checkout-configurations/create-a-checkout-configuration · /payments-and-billing/fees/fees
- exa.ai/docs/admin/pricing · exa.ai/docs/get-started/exa-mcp
- terac.com/mcp · terac.com/docs/researchers/mcp · terac.com/docs/researchers/finance/pricing · terac.com/events/hackathon/nyc
- Local: ~/.hermes/hermes-agent/website/docs/user-guide/{features/api-server.md, features/kanban.md, features/mcp.md, features/plugins.md, features/cron.md, messaging/webhooks.md, profiles.md, multi-profile-gateways.md}
