# Receipts backend on the Mac (OrbStack)

Everything runs in three isolated containers: `receipts-worker` (orders), `mcp` (bot tools +
human post queue) and `hermes` (the 8 bots). No access to your home folder, no docker socket,
the only open port is `127.0.0.1:8787`.

1. **Install OrbStack:** `brew install orbstack` (or download from orbstack.dev), open it once.
   Check: `docker version` prints a Server section.
2. **Copy the repo** to the Mac, for example `~/receipts`, and `cd ~/receipts/backend/deploy`.
3. **Create `.env`:** `cp .env.example .env`, then fill in:
   | Key | Where to get it |
   |---|---|
   | `MCP_TOKEN` | `openssl rand -hex 32` |
   | `SITE_URL` | the Vercel URL of the site, e.g. `https://receipts.vercel.app` |
   | `SITE_ADMIN_TOKEN` | same value as `ADMIN_TOKEN` in Vercel > Project > Settings > Environment Variables |
   | `WHOP_API_KEY`, `WHOP_COMPANY_ID` | Whop dashboard > Developer (company API key; id starts `biz_`) |
   | `SLANT_API_KEY`, `SLANT_PLATFORM_ID` | Slant 3D dashboard > API |
   | `CRAFTCLOUD_API_KEY` | Craftcloud (All3DP) partner / API settings |
   | `RECEIPTS_MOCK` | `1` for fake Whop/Slant/Craftcloud; leave empty for live |
   | `X_BEARER_TOKEN` | developer.x.com > your app > Keys and tokens > Bearer token |
   | `X_BRAND_HANDLE` | the brand X handle without `@` |
   | `X_AUTOREPLY_MENTIONS`, `X_USER_TOKEN` | leave `0` / empty unless auto-replying to "@brand print this" mentions (user OAuth 2.0 token of the brand account) |
   | `EXA_API_KEY` | dashboard.exa.ai > API keys |
   | `SOLARI_API_KEY` (`SOLARI_CDP_URL` optional) | Solari dashboard, see docs.getsolari.com |
   | `ADS_DAILY_CAP_USD` | hard daily cap for drafted ad budgets, default `50` |
   | `CLAUDE_*`, `CODEX_*`, `<BOT>_MODEL` | keep the defaults unless a model id is rejected |
4. **Build and start:** `docker compose up -d --build` (first build takes several minutes).
5. **Sign Hermes in** (once; stored in `/opt/data/auth.json` on the `hermes-home` volume, and all
   8 bots share it). ceo, designer and closer use Claude (`anthropic`); scout, ads, production,
   hiring and finance use your ChatGPT account (`openai-codex`).
   - ChatGPT / Codex: `docker compose exec -it hermes /opt/hermes/.venv/bin/hermes auth add openai-codex --no-browser`
     It prints a URL and a code: open the URL on the Mac, sign in to ChatGPT, enter the code.
   - Claude: `docker compose exec -it hermes /opt/hermes/.venv/bin/hermes auth add anthropic --no-browser`
     Open the printed URL, approve, then paste the code it shows back into the terminal. (Hermes
     notes that using a Claude Pro/Max subscription outside Claude Code needs extra-usage credits
     on that account. If you would rather use an API key:
     `docker compose exec -it hermes /opt/hermes/.venv/bin/hermes auth add anthropic --type api-key`.)
   - Check: `docker compose exec hermes /opt/hermes/.venv/bin/hermes auth list` shows both providers.
   - Apply: `docker compose restart hermes`.
   The `claude` and `codex` CLIs are installed too (`docker compose exec -it hermes claude login`,
   `... codex login`). Hermes can borrow those logins, but it shares their single-use refresh
   tokens, so the two programs can log each other out. Use the `hermes auth add` logins above.
6. **Verify:**
   - `docker compose ps`: three services `running`, `mcp` `healthy`.
   - `curl -s http://127.0.0.1:8787/health` prints `{"ok":true}`.
   - `docker compose logs hermes | grep fleet` shows 8 `profile ... ready` lines and `cron rx-... created`.
   - `docker compose logs --tail 20 receipts-worker` shows the poll loop without tracebacks.
   - `docker compose exec hermes /opt/hermes/.venv/bin/hermes -p scout cron list` lists `rx-scout`.
7. **Open the post queue:** http://127.0.0.1:8787/queue. For each draft: Copy, Open post,
   reply from the brand account, then Mark posted. Nothing there posts by itself.
8. **Stop everything:** `docker compose down` (data stays in the volumes). Wipe all data and
   logins too: `docker compose down -v`.
