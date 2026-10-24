# Micro Factory: setup on an Apple Silicon Mac

Everything runs in Docker on the Mac (factory API + MCP, six Hermes bots, Cloudflare tunnel).
The iPhone app talks to the tunnel URL. Commands run from the repo root unless a step says otherwise.

## 1. Docker
1. Install OrbStack and open it once (it starts the Docker engine):
   ```sh
   brew install --cask orbstack
   open -a OrbStack
   docker version
   ```

## 2. Keys
1. Create the env file (Compose reads `backend/deploy/.env`):
   ```sh
   cd backend/deploy
   cp .env.example .env
   ```
2. Make four random secrets and paste them into `.env` as `APP_SHARED_SECRET`, `ADMIN_KEY`, `MCP_TOKEN`, `HERMES_API_KEY`:
   ```sh
   for k in APP_SHARED_SECRET ADMIN_KEY MCP_TOKEN HERMES_API_KEY; do echo "$k=$(openssl rand -hex 16)"; done
   ```
3. Fill in the service keys (an empty key keeps that part mocked; `FACTORY_MOCK=1` mocks everything):
   | Key | Where it comes from |
   |---|---|
   | `MESHY_API_KEY` | https://www.meshy.ai: account > API keys |
   | `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
   | `WHOP_API_KEY`, `WHOP_COMPANY_ID`, `WHOP_PRODUCT_ID`, `WHOP_WEBHOOK_SECRET` | step 6 |
   | `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID` | https://elevenlabs.io/app/settings/api-keys, then step 7 |
   | `PRINTER_IP`, `PRINTER_SERIAL`, `PRINTER_ACCESS_CODE` | step 5 |
   | `ANTHROPIC_API_KEY` (or another provider) | step 4 |
   | `CF_TUNNEL_TOKEN` (optional, fixed URL) | https://one.dash.cloudflare.com > Networks > Tunnels |
4. Keep `FACTORY_MOCK=1` for the first start. Set `FACTORY_MOCK=0` once the printer and Whop are set up.
   With `FACTORY_MOCK=0`, everything that has a key is real.

## 3. Start
1. Build and start (the first build downloads OrcaSlicer and builds Hermes, so it takes a while):
   ```sh
   cd backend/deploy
   docker compose up -d --build
   docker compose ps
   ```
2. Read the tunnel URL (a random `https://….trycloudflare.com`; it changes on every restart unless `CF_TUNNEL_TOKEN` is set):
   ```sh
   docker compose logs cloudflared | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
   curl https://<tunnel-host>/health        # {"ok":true,"mock":true,"printer_state":"IDLE"}
   ```
3. After editing `.env` later, apply it with `docker compose up -d` (this recreates the changed containers).

## 4. Fleet (Hermes bots)
1. Choose a provider in `.env`: `FLEET_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` (https://console.anthropic.com/settings/keys),
   or `openrouter` + `OPENROUTER_API_KEY`, `openai` + `OPENAI_API_KEY`, `nous` + `NOUS_API_KEY`.
2. Models (empty = defaults): `INTAKE_MODEL` (claude-opus-5-5), `SALES_MODEL`, `PRODUCTION_MODEL`, `GROWTH_MODEL`
   (claude-sonnet-4-6), `SUPPORT_MODEL`, `FINANCE_MODEL` (claude-haiku-4-5). Use ids your provider currently offers.
3. Restart and check that the six profiles exist, each with the `factory` MCP server:
   ```sh
   docker compose up -d hermes
   docker compose exec hermes env HERMES_HOME=/opt/data hermes profile list
   docker compose exec hermes env HERMES_HOME=/opt/data hermes -p intake mcp test factory
   ```

## 5. Printer (Bambu Lab A1)
1. On the printer screen, open the network (WLAN) settings and turn on **LAN Only Mode**, then **Developer Mode**.
   Menu names vary a little by firmware.
2. On the same screen, note the **IP address** and **Access Code**. The **serial number** is under Settings > Device (also on the label).
3. Insert a microSD card (LAN prints are uploaded to it). Put the Mac and the printer on the same network.
4. Put the values in `.env`, set `FACTORY_MOCK=0`, then apply and check:
   ```sh
   docker compose up -d factory
   curl https://<tunnel-host>/health        # printer_state should be IDLE, not OFFLINE
   ```

## 6. Whop
1. In the Whop dashboard, create a product (e.g. "Micro Factory"). Copy its `prod_…` id into `WHOP_PRODUCT_ID`.
   Your company id (`biz_…`, it is in the dashboard URL) goes in `WHOP_COMPANY_ID`.
2. In https://whop.com/dashboard/developer, create a server API key that can create plans and refund payments, and put it in `WHOP_API_KEY`.
   Each quote creates a one-time hidden plan (`plan_…`) on that product.
3. Register the webhook. The response shows `webhook_secret` (`ws_…`) **once**: copy all of it into `WHOP_WEBHOOK_SECRET`.
   ```sh
   curl -X POST https://api.whop.com/api/v1/webhooks \
     -H "Authorization: Bearer $WHOP_API_KEY" -H "Content-Type: application/json" \
     -d '{"url": "https://<tunnel-host>/webhooks/whop", "events": ["payment.succeeded"]}'
   docker compose up -d factory
   ```
   With a quick tunnel the URL changes on restart. Register the new URL each time, or set `CF_TUNNEL_TOKEN`.
4. For the app, create a second API key with **only** `iap:read` (it is safe to ship inside the app). It goes in the iOS `Config.plist` (step 8).

## 7. ElevenLabs (voice)
1. Create the agent exactly as in `backend/deploy/elevenlabs-agent.md`: private agent, system prompt, first message,
   and the client tool `send_to_agent`.
2. Put its `agent_…` id in `ELEVENLABS_AGENT_ID` and the API key in `ELEVENLABS_API_KEY`, then run `docker compose up -d factory`.

## 8. iOS app
1. Install the tools: Xcode from the App Store, then `brew install xcodegen`.
2. Edit `ios/Sources/MicroFactoryApp/Resources/Config.plist`:
   `API_BASE_URL` = `https://<tunnel-host>`, `APP_KEY` = your `APP_SHARED_SECRET`, `WHOP_COMPANY_ID` = `biz_…`, `WHOP_IAP_KEY` = the `iap:read` key.
3. Generate and open the project:
   ```sh
   cd ios
   xcodegen generate
   open MicroFactory.xcodeproj
   ```
4. Signing with a free Apple ID: Xcode > Settings > Accounts > add your Apple ID. Then, on the `MicroFactory` target > Signing & Capabilities,
   set Team = "(Personal Team)". If the bundle id `dev.microfactory.app` is taken, change it (in `project.yml` too).
5. Plug in the iPhone, pick it and the `MicroFactory` scheme, then Run. On the phone, turn on Developer Mode if asked,
   and trust the certificate under Settings > General > VPN & Device Management. Free installs expire after 7 days; run again to renew.
6. When the tunnel URL changes, there is no need to rebuild: long-press the "Micro Factory" wordmark on the Shop screen and set the new server URL.

## 9. First test print
1. Set the stock and the loaded spool, then mark the bed clear (the colour must be one of the stocked colours):
   ```sh
   export URL=https://<tunnel-host> ADMIN=<your ADMIN_KEY>
   curl -s -H "X-Admin-Key: $ADMIN" $URL/admin/state
   curl -s -X POST -H "X-Admin-Key: $ADMIN" -H "Content-Type: application/json" -d '{"colours": ["white", "black", "red", "blue"]}' $URL/admin/stock
   curl -s -X POST -H "X-Admin-Key: $ADMIN" -H "Content-Type: application/json" -d '{"colour": "white"}' $URL/admin/spool
   curl -s -X POST -H "X-Admin-Key: $ADMIN" $URL/admin/bed-cleared
   ```
2. In the app, order a **Name tag** in white, type a name, tap "Looks good", then Pay. The production bot starts the print after the Whop webhook arrives.
3. When it finishes, remove the part, then tell the shop the bed is clear (this lets the next job start):
   ```sh
   curl -s -H "X-Admin-Key: $ADMIN" "$URL/admin/human-tasks?status=open"
   curl -s -X POST -H "X-Admin-Key: $ADMIN" $URL/admin/bed-cleared
   ```
4. After swapping filament: `curl -s -X POST -H "X-Admin-Key: $ADMIN" -H "Content-Type: application/json" -d '{"colour": "black"}' $URL/admin/spool`

## 10. Troubleshooting
- Anything odd: `docker compose logs -f factory` (API, MCP, printer) and `docker compose logs -f hermes` (bots).
- App says the server is unreachable: `API_BASE_URL` must be the current https tunnel URL, and `APP_KEY` must equal `APP_SHARED_SECRET`.
- `/health` shows `printer_state: OFFLINE`: check LAN Only + Developer Mode, `PRINTER_IP`/`PRINTER_ACCESS_CODE`, `FACTORY_MOCK=0`, and that the printer and Mac share a network.
- Paid but the order stays `quoted`: `docker compose logs factory | grep webhooks` should show a 200. A 401 means `WHOP_WEBHOOK_SECRET` is not the exact `ws_…` value, or the webhook URL is an old tunnel URL.
- Chat replies "The shop agent is unavailable": check the provider key and model ids in `.env`, then `docker compose up -d hermes` and read its logs.
