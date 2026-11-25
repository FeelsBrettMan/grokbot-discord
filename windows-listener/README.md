# Discord -> Grok Bot listener (Windows)

Listens to one private Discord channel and forwards the owner's messages to the Grok
Bot routine webhook. The routine replies to Discord directly over REST (see `../box/` and
`../docs/routine-prompt-discord-rest.md`).
Based on RudeDude/grokbot-discord (MIT) plus local hardening.

## What it does

- Forwards every message from the allowlisted author in the allowlisted
  server/channel (no @mention needed). Ignores the bot itself, other bots and
  everyone else. Empty or invalid allowlists = it refuses to start.
- Waits 3 s after the owner's last message, then sends one wake with all new messages
  combined (max ~4000 chars), plus up to the last 12 channel messages as `history`
  (max ~3000 chars total, ~600 per message). Small fields go first in the JSON so a
  truncated wake still has correlation_id and the message IDs.
- Shows "YourBot is typing..." from the moment the owner writes until the reply appears.
- One run per channel at a time: a run is finished when the bot posts in the
  channel (the routine's reply) or after 5 minutes. Messages sent meanwhile go
  out together as the next wake.
- Catch-up: remembers the last forwarded message (`data\state.json`). After a
  restart or reconnect it forwards the owner's messages it missed (unless the bot
  already replied after them) as one batch.
- Failed webhook calls are retried twice (15 s, 30 s backoff), then dropped and logged.
- Logs to `logs\bridge.log` (rotating, 5 x 2 MB) with the token/key redacted.

## Install

1. Install Python 3.12 or newer if you don't have it:
   `winget install -e --id Python.Python.3.12 --scope machine`
2. Unzip to a permanent folder, e.g. `C:\discord-bridge`.
3. Open **PowerShell as Administrator**, then:
   ```
   cd C:\discord-bridge
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```
   The first run creates `.env` and stops.
4. `notepad .env`: replace the three `changeme` values (bot token, routine webhook
   URL, webhook key) and the three `YOUR_...` allowlist IDs. Save.
5. Run `install.ps1` again (same command). It checks the config, registers the
   `DiscordGrokBridge` scheduled task and starts it.
6. Check: `.\status.ps1` should say Running and the log should show
   `online as YourBot#0000` and `allowlisted channel ... visible=True`.

Then send a message in the channel: you should see "YourBot is typing..." and a reply.

## Update to a new version

1. Unzip the new `discord-bridge-windows.zip` to e.g. `Downloads\discord-bridge-new`.
2. Administrator PowerShell:
   ```
   cd $HOME\Downloads\discord-bridge-new\discord-bridge
   powershell -ExecutionPolicy Bypass -File .\update.ps1 -Target C:\discord-bridge
   ```
It stops the task, replaces code files only (keeps `.env`, `data\state.json`,
`logs\`), reinstalls packages only if `requirements.txt` changed, moves old
default limits in `.env` to the new ones, checks config and restarts the task.

## Auto-start / auto-restart

Task Scheduler task `DiscordGrokBridge`:
- starts at boot, runs whether or not you are logged in (S4U logon, no stored
  password, normal user rights, no admin);
- `run.ps1` restarts the listener if it exits (10 s, backing off to 5 min);
- a 5-minute watchdog trigger restarts `run.ps1` if it ever dies (the task's
  "do not start a new instance" rule stops duplicates; the app also holds a
  lock file so two copies can never run).

Config errors (bad token, missing intent, empty allowlist) stop it instead of
looping; fix `.env` and run `Start-ScheduledTask DiscordGrokBridge`.

## Everyday commands

| | |
|---|---|
| status + last log lines | `.\status.ps1` |
| restart after editing .env | `Stop-ScheduledTask DiscordGrokBridge; Start-ScheduledTask DiscordGrokBridge` |
| run in a window (debug) | `.\run.ps1` (stop the task first) |
| config check only | `.\.venv\Scripts\python.exe -m discord_bridge --check` |
| update | `.\update.ps1 -Target C:\discord-bridge` (from the new unzipped folder) |
| remove | `.\uninstall.ps1` (add `-Purge` to also delete .venv, data, logs, .env) |

## Payload sent to the webhook

`Authorization: Bearer <GROK_BOT_GROK_WEBHOOK_KEY>`, JSON:
compact UTF-8, fields in this order:
`correlation_id, reply_mode="discord_rest", author_id, guild_id, channel_id, message_id,
message_ids, author_name, bot, text, history[{author, is_bot, text, timestamp}]`.
A typical body is ~300-350 chars plus text and history; the log line
`waking ... body_chars=N` shows each wake's size.

## Notes

- Don't run this and another listener on the same bot token at the same time:
  both would forward every message.
- Discord app settings needed: Message Content Intent ON; bot permissions View
  Channels, Send Messages, Read Message History (68608). No Administrator.
- `.env` is locked to your user, SYSTEM and Administrators by install.ps1.
