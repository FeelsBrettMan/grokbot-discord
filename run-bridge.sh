#!/usr/bin/env bash
# Keep-alive launcher for the Discord->Grok Bot bridge. Single instance (flock), restart loop.
# Usage: run-bridge.sh            (foreground supervisor loop)
#        run-bridge.sh --daemon   (detach with nohup; log in ~/.local/state/discord-bridge/)
#        run-bridge.sh --check    (validate config only; never prints secret values)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="${BRIDGE_CONFIG_DIR:-$HOME/.config/discord-bridge}"
STATE="$HOME/.local/state/discord-bridge"
mkdir -p "$STATE"; chmod 700 "$STATE"
LOG="$STATE/bridge.log"
export BRIDGE_ENV_FILE="$CFG/bridge.env"

load_secret() {  # VAR file  -> export VAR from file if VAR unset; never echoes
  local var="$1" file="$CFG/secrets/$2"
  if [[ -z "${!var:-}" && -f "$file" ]]; then
    printf -v "$var" '%s' "$(tr -d '\r\n' < "$file")"; export "$var"
  fi
}
load_secret DISCORD_BOT_TOKEN discord_bot_token
load_secret CALLBACK_SECRET callback_secret
load_secret GROK_BOT_GROK_WEBHOOK_URL grok_webhook_url
load_secret GROK_BOT_GROK_WEBHOOK_KEY grok_webhook_key

missing=()
for v in DISCORD_BOT_TOKEN CALLBACK_SECRET GROK_BOT_GROK_WEBHOOK_URL GROK_BOT_GROK_WEBHOOK_KEY; do
  [[ -n "${!v:-}" ]] || missing+=("$v")
done
if (( ${#missing[@]} )); then
  echo "refusing to start: missing ${missing[*]}" >&2; exit 78
fi
PY="$DIR/.venv/bin/python"; [[ -x "$PY" ]] || { echo "venv missing: run python3 -m venv .venv && .venv/bin/pip install -e ." >&2; exit 70; }

if [[ "${1:-}" == "--check" ]]; then
  cd "$DIR"; "$PY" -c 'from grokbot_discord.config import load_settings as l; s=l(); print("config ok: guilds=%d channels=%d authors=%d bots=%s" % (len(s.guilds),len(s.channels),len(s.authors),",".join(s.bots)))'
  exit $?
fi
if [[ "${1:-}" == "--daemon" ]]; then
  nohup "$0" >>"$LOG" 2>&1 < /dev/null & disown; echo "started supervisor pid $! (log: $LOG)"; exit 0
fi

exec 9>"$STATE/bridge.lock"
flock -n 9 || { echo "bridge already running" >&2; exit 0; }
echo "$$" > "$STATE/supervisor.pid"
cd "$DIR"
while true; do
  "$PY" -m grokbot_discord || rc=$?
  rc=${rc:-0}
  echo "$(date -Is) bridge exited rc=$rc; restart in 5s"
  [[ $rc -eq 2 ]] && { echo "config error; not restarting"; exit 2; }
  rc=; sleep 5
done
