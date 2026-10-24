# Micro Factory backend (BE2: service, MCP server, fleet, deploy)

`service/` FastAPI app + SQLite + SSE + printer monitor + Whop + ElevenLabs token ·
`mcp_server/` FastMCP tools for the bots · `fleet/` six Hermes profiles + `bootstrap.sh` ·
`deploy/` compose stack. BE1's `factory` package is reached only through `service/pipeline.py`.

## Run locally (no Docker)
```sh
sh backend/run-local.sh                        # mock mode, API :8080, MCP :9000/mcp; keys default to "dev"
cd backend && FACTORY_MOCK=1 .venv/bin/python -m pytest -q   # whole suite, offline
```
One venv (`backend/.venv`, Python 3.12) holds the service and the `factory` library: all deps are in
`pyproject.toml` (`uv venv --python 3.12 .venv && uv pip install -r pyproject.toml --group dev`).
`tests/service` uses fakes; `tests/e2e` runs the real service + real `factory` (mocked Meshy, Whop,
printer, vision; real CadQuery, and real OrcaSlicer when `tools/orca/` exists). Hermes outside Docker: install it, then
`HERMES_HOME=~/.hermes-mf FLEET_DIR=$PWD/fleet HERMES_API_KEY=dev MCP_TOKEN=dev FACTORY_MCP_URL=http://127.0.0.1:9000/mcp sh fleet/bootstrap.sh`.
Docker: `cd deploy && cp .env.example .env && docker compose up -d --build`.

## Env vars
All in `deploy/.env.example`: SPEC's list plus `ADMIN_KEY`, `FLEET_PROVIDER`, `*_MODEL`,
provider keys, `EXA_API_KEY`/`TERAC_API_KEY`, `HERMES_REPO`, `HERMES_UID/GID`, `CF_TUNNEL_TOKEN`.

## How the pieces talk
- App → API (`X-App-Key` + `X-Device-Id`). A chat message → `POST {HERMES_API_BASE}/p/intake/v1/runs`
  (`session_id` = order id) → `GET /p/intake/v1/runs/{id}/events` → `agent_delta` SSE → stored agent message.
- Bots → MCP `:9000/mcp` (bearer `MCP_TOKEN`, `X-Hermes-Profile` names the bot) → `service/core.py`.
- API, MCP server and printer monitor run in one process and share one event bus, so tool
  calls (`publish_design`, `post_customer_update`) and printer events reach the SSE stream.
- `/accept` → `prepare_quote` (slice → price → Whop one-time variant) → `quote` event → sales bot woken.
- Whop `payment.succeeded` (Standard Webhooks verified) → `paid` → `queued` → production bot
  run (`Idempotency-Key` = payment id). FINISH → `done` + `bed_clear` task → production run.

## Deviations from SPEC
- Hermes auth is per profile under the multiplexer: each bot's key is `<HERMES_API_KEY>-<profile>`
  (bootstrap writes it). Events/status use the prefixed path `/p/<profile>/v1/runs/{id}/events`.
- Messages on orders past `quoted` (paid, printing, failed...) go to the **support** bot, not intake.
- Payment sets `paid` then immediately `queued` with `queue_position`.
- `/accept` returns 202 and quotes in the background; it calls `prepare_quote` directly
  (idempotent per design version), then wakes sales.
- The service clamps pricing policy ±20% itself before `factory.save_policy`.
- `snapshot()` returns a JPEG URL + server path (the A1 camera gives JPEG), not PNG.
- Tool failures come back as `{ok: false, error, traceback_tail}` so bots can retry CadQuery.
- Printer `FAILED` and `cancel_print` mark the order `failed` and open a `bed_clear` task.
- File URLs are `/files/{order}/{name}?sig=` (HMAC of order id + device id); relative if
  `PUBLIC_BASE_URL` is empty. No webhook secret → webhooks rejected (use `/dev/pay` in mock).
- Without `APP_SHARED_SECRET`, mock mode accepts any non-empty `X-App-Key`; non-mock rejects all.
- `/catalog` omits `custom` (the app adds "Something else"); `POST /orders` accepts it.
- Kanban "notes" are self-assigned `NOTE:` cards the bot completes when the dispatcher hands them back.
- `cloudflared` runs from the factory image (the official image has no shell for the token switch).

- Whop plan title is `Order <id>` (Whop caps plan titles at 30 chars); the full "Micro Factory order <id>"
  is the plan description. Plans are created `visibility: hidden`.

## Checked against docs (runs/integ/docs, 2026-10-24)
Whop create-plan / refund / webhook signing / iOS `purchase(planId)`, the ElevenLabs token endpoint,
OrcaSlicer v2.4.2 asset names, and a real slice of the A1 profiles. `fleet/bootstrap.sh` was run against
a scratch `HERMES_HOME` with the Hermes CLI (six profiles, factory MCP reachable from each).

## Not verified here
Live Whop/ElevenLabs calls, whether the iOS SDK can buy a `hidden` plan, the Hermes repo URL and image,
model ids, `message.delta` payload fields, cadquery arm64 wheels, Debian trixie package names, and an
actual `docker compose build`.
