#!/bin/sh
# Create / refresh the eight Receipts Hermes profiles (ceo scout designer closer ads production
# hiring finance) inside HERMES_HOME, then run the gateway (which ticks the cron jobs).
#
# Entrypoint of the `hermes` service (deploy/Dockerfile.hermes copies this folder to /opt/fleet;
# compose runs it as uid 10000 instead of the image's s6 /init). Idempotent; BOOTSTRAP_ONLY=1
# skips the final `exec hermes gateway run` (foreground; the gateway runs the cron ticker).
# Model auth: `hermes auth add anthropic` / `hermes auth add openai-codex` (stored in
# $HERMES_HOME/auth.json), or the `claude` / `codex` CLI logins under $HOME, which Hermes adopts
# (auth.adopt_external_logins, on by default). See SETUP-MAC.md step 5.
set -eu

FLEET_DIR="${FLEET_DIR:-$(cd "$(dirname "$0")" && pwd)}"
HERMES_HOME="${HERMES_HOME:-/opt/data}"
export HERMES_HOME
# The official image's venv binary, by absolute path (outside the image: whatever is on PATH).
HERMES_BIN="${HERMES_BIN:-/opt/hermes/.venv/bin/hermes}"
[ -x "$HERMES_BIN" ] || HERMES_BIN="$(command -v hermes)"
hermes() { "$HERMES_BIN" "$@"; }
RENDER="${FLEET_PYTHON:-python3} $FLEET_DIR/profiles.py"
PROFILES="$($RENDER bots)"

: "${MCP_TOKEN:?MCP_TOKEN must be set}"
RECEIPTS_MCP_URL="${RECEIPTS_MCP_URL:-http://mcp:8787/mcp}"
# Hermes provider ids: `anthropic` (Claude account or Claude Code login), `openai-codex`
# (ChatGPT login). gpt-5.5 is in Hermes' openai-codex catalog; *-codex ids are rejected there.
CLAUDE_PROVIDER="${CLAUDE_PROVIDER:-anthropic}"
CLAUDE_MODEL="${CLAUDE_MODEL:-claude-sonnet-4-6}"
CODEX_PROVIDER="${CODEX_PROVIDER:-openai-codex}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"

log() { printf '[fleet] %s\n' "$*"; }

# set_env FILE KEY VALUE: replace or append KEY=VALUE, keep every other line.
set_env() {
    file="$1"; key="$2"; value="$3"
    touch "$file"
    chmod 600 "$file"
    grep -v "^${key}=" "$file" > "$file.tmp" || true
    printf '%s=%s\n' "$key" "$value" >> "$file.tmp"
    mv "$file.tmp" "$file"
}

mkdir -p "$HERMES_HOME" "${HOME:-$HERMES_HOME/home}"
# The image's XDG_RUNTIME_DIR sits under /tmp, which is an empty tmpfs here.
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then mkdir -p -m 700 "$XDG_RUNTIME_DIR"; fi
hermes config set gateway.multiplex_profiles true

for p in $PROFILES; do
    src="$FLEET_DIR/$p"
    dst="$HERMES_HOME/profiles/$p"
    if [ ! -f "$src/SOUL.md" ]; then
        echo "[fleet] missing $src/SOUL.md" >&2
        exit 1
    fi
    if [ ! -d "$dst" ]; then
        log "creating profile $p"
        hermes profile create "$p" --no-alias
    fi
    cp "$src/SOUL.md" "$dst/SOUL.md"
    $RENDER config "$p" > "$dst/config.yaml"
    if [ -d "$src/skills" ]; then
        mkdir -p "$dst/skills"
        cp -R "$src/skills/." "$dst/skills/"
    fi

    upper="$(echo "$p" | tr '[:lower:]' '[:upper:]')"
    eval "override=\${${upper}_MODEL:-}"
    if [ "$($RENDER engine "$p")" = claude ]; then
        provider="$CLAUDE_PROVIDER"; model="${override:-$CLAUDE_MODEL}"
    else
        provider="$CODEX_PROVIDER"; model="${override:-$CODEX_MODEL}"
    fi
    env_file="$dst/.env"
    set_env "$env_file" MCP_TOKEN "$MCP_TOKEN"
    set_env "$env_file" RECEIPTS_MCP_URL "$RECEIPTS_MCP_URL"
    set_env "$env_file" FLEET_PROVIDER "$provider"
    set_env "$env_file" FLEET_MODEL "$model"
    log "profile $p ready ($provider / $model)"
done

# ---- cron jobs (created once; the gateway ticks them) ----
$RENDER cron | while IFS="$(printf '\t')" read -r bot name schedule prompt; do
    if hermes -p "$bot" cron list 2>/dev/null | grep -q "$name"; then
        log "cron $name exists"
    else
        hermes -p "$bot" cron create "$schedule" "$prompt" --name "$name" --deliver local
        log "cron $name created ($schedule)"
    fi
done

if [ "${BOOTSTRAP_ONLY:-0}" = 1 ]; then
    log "bootstrap done (BOOTSTRAP_ONLY=1)"
    exit 0
fi
log "starting gateway (foreground, cron ticker on)"
# `exec` skips shell functions, so put the binary's directory first: `hermes` is $HERMES_BIN.
# --no-supervise: s6 is not running here, so stay in the foreground instead of redirecting to it.
PATH="$(dirname "$HERMES_BIN"):$PATH"
export PATH
exec hermes gateway run --no-supervise
