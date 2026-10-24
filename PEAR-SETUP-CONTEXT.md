# For Pear: finish the Receipts Docker setup on this Mac

Akshaya authorized this: get the Receipts bot fleet running in Docker on this Mac, fast. You can edit and rebuild files in `~/receipts/backend/deploy/` and `~/receipts/backend/fleet/bootstrap.sh` as needed. Build, read the error, fix, rebuild, until all three services are up.

## Where things stand (Oct 24, ~11:40)
- OrbStack is running (`docker version` shows a Server).
- Repo cloned at `~/receipts` (github.com/akshayalohia/receipts, main @ 961e572).
- `~/receipts/backend/deploy/.env` exists (chmod 600) with `MCP_TOKEN` and `SITE_ADMIN_TOKEN` generated and `RECEIPTS_MOCK=1`. Third-party keys (Whop, Slant, Craftcloud, X, Exa, Solari) are empty on purpose: Akshaya fills them in.
- `docker compose config -q` passes. `docker compose up -d --build` fails at `Dockerfile.hermes:24`: `pip install /opt/hermes-src` → `RuntimeError: Building wheels or sdists for hermes-agent is not supported. Hermes is distributed via the shell installer, Docker image, or Nix.`
- Dit pushed a fix to main (Dockerfile.hermes now builds FROM nousresearch/hermes-agent:latest, runs bootstrap as uid 10000, gateway in foreground; SETUP-MAC.md step 5 has the real Hermes login commands). Run `git -C ~/receipts pull` first, then rebuild. If it still fails, follow the fix direction below.

## The stack (backend/deploy/docker-compose.yml)
- `receipts-worker`: `python -m receipts.worker`, the order pipeline (Whop → print file → Slant 3D/Craftcloud), polling every 60 s.
- `mcp`: MCP server with the bot tools, plus the human post-queue page at `127.0.0.1:8787/queue` and `/health`.
- `hermes`: 8 Hermes bot profiles (ceo, scout, designer, closer, ads, production, hiring, finance). `fleet/bootstrap.sh` renders their configs from `fleet/fleet.yaml`, copies SOUL.md and skills, and creates crons.
- Isolation rules (keep them): non-root uid 10000, `read_only: true` + tmpfs `/tmp`, `cap_drop: [ALL]`, `no-new-privileges`, named volumes only (`receipts-data`, `hermes-home`), no bind mounts of `~`, no docker socket, ports bound to 127.0.0.1 only.

## Fix direction for the hermes image
1. Base it on the official image: `FROM nousresearch/hermes-agent:latest` (check that `docker pull` works on arm64). Look inside it (`docker run --rm --entrypoint sh nousresearch/hermes-agent:latest -c 'which hermes; id; echo $HERMES_HOME'`) to find the hermes binary path, the default user and HERMES_HOME.
2. The official image starts through s6-overlay, which needs root. With cap_drop ALL and uid 10000, override the entrypoint and run `sh /opt/fleet/bootstrap.sh` directly. Call hermes by its absolute path, and end bootstrap by running the gateway in the foreground with cron on. If one isolation key truly can't work, relax only that one and say which and why.
3. Keep the `claude` and `codex` CLIs in the image (`npm install -g @anthropic-ai/claude-code @openai/codex`; install Node if the base lacks it).
4. Sign-in: Hermes needs its own provider auth, not just the CLIs. Find the provider ids with `hermes auth --help` / `hermes auth list` inside the container. Codex is `openai-codex` (`hermes auth add openai-codex`). Codex on a ChatGPT account rejects some models (e.g. `sol-6.1`), so pick one `hermes model` lists for openai-codex and set `CODEX_MODEL` in .env. Claude: use whatever Hermes provider the Claude subscription login maps to. Akshaya runs the interactive logins himself; give him the exact commands.

## Done when
- `docker compose ps` shows 3 services running and `mcp` healthy.
- `curl -s http://127.0.0.1:8787/health` returns `{"ok":true}`.
- `docker compose logs hermes` shows the 8 profiles created with no tracebacks.
- Akshaya has the exact login commands, and the path `~/receipts/backend/deploy/.env` to fill in.
- Commit your deploy fixes on a branch `mac-setup` in ~/receipts (don't push unless Akshaya says so) and list the changed files.

## Don't
No posting, messaging, purchases or sign-ups. No macOS setting changes. No secrets in replies. Nothing outside `~/receipts` and Docker.

## Bigger picture (only if needed)
`~/receipts/CEO-HANDOFF.md` is the full company context for the CEO bot; `SETUP-MAC.md` has the original setup steps.
