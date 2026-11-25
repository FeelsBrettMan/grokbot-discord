# Discord -> Grok Bot listener (Windows)

Listens to one private Discord channel and forwards allowlisted people's messages to the Grok
Bot routine webhook. The routine replies to Discord directly over REST (see `../box/` and
`../docs/routine-prompt-discord-rest.md`).
Based on RudeDude/grokbot-discord (MIT) plus local hardening.

## What it does

- Group chat: forwards messages from **trusted** people (full control) and
  **chat-only** people (conversation only) in the allowlisted server/channel, no
  @mention needed. Everyone else and other bots are ignored completely (not
  forwarded, not in history). Empty guild/channel/trusted lists = it refuses to start.
- Buffers everything said since the bot's last post, waits 3 s after the last
  message, then sends one wake with all of it (`messages`, each marked
  `trusted` true/false) plus up to the last 12 earlier messages as `history`.
- One run per channel at a time. When the bot posts (the routine's reply), the
  run ends and buffered messages from before that post are dropped, because the
  routine re-fetches right before posting and its reply covers them. Messages
  after the post start the next batch. No reply within 5 minutes releases the run.
- Shows "YourBot is typing..." while a batch is pending or a run is in flight.
- Catch-up: remembers the last forwarded message (`data\state.json`). After a
  restart or reconnect it forwards missed messages from allowed people (unless the
  bot already replied after them) as one batch.
- Failed webhook calls are retried twice (15 s, 30 s backoff), then dropped and logged.
- Logs to `logs\bridge.log` (rotating, 5 x 2 MB) with the token/key redacted.

## Adding people

In `.env` on the PC (comma-separated Discord user IDs; right-click a user with
Developer Mode on, Copy User ID), then restart the task:

```
DISCORD_TRUSTED_AUTHORS=YOUR_DISCORD_USER_ID
DISCORD_CHAT_AUTHORS=111111111111111111,222222222222222222
```

Then, from an Administrator PowerShell in the install folder:
`powershell -ExecutionPolicy Bypass -File .\restart.ps1`

The Grok Bot side has its own copy of the lists (`~/.config/discord-bridge/allowlist.json`
on the Bot's computer); ask the Bot to add the same IDs there. Both must match.
`DISCORD_AUTHOR_ALLOWLIST` still works as an old name for `DISCORD_TRUSTED_AUTHORS`;
`update.ps1` renames it.

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
   URL, webhook key) and the `YOUR_...` allowlist IDs. Save.
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
`logs\`), reinstalls packages only if `requirements.txt` changed, migrates `.env`
(`DISCORD_AUTHOR_ALLOWLIST` -> `DISCORD_TRUSTED_AUTHORS`, adds `DISCORD_CHAT_AUTHORS=`
and the new caps), checks config and restarts the task.

## Auto-start / auto-restart

Task Scheduler task `DiscordGrokBridge`:
- starts at boot, runs whether or not you are logged in (S4U logon, no stored
  password, normal user rights, no admin);
- `run.ps1` restarts the listener if it exits (10 s, backing off to 5 min);
- a 5-minute watchdog trigger restarts `run.ps1` if it ever dies.

Only one listener can ever run: a lock file in `data\` plus a machine-wide
named mutex (so even a second copy in another folder exits with "another bridge
instance is already running"). `run.ps1` puts the listener in a Windows Job
object that is killed when the task stops, and the listener also exits on its
own if `run.ps1` disappears, so stopping the task never leaves an orphan.

## Restart after editing .env

Use `restart.ps1`, not `Stop-ScheduledTask`/`Start-ScheduledTask` (older
versions left the python process running, so the change never took effect).
Administrator PowerShell:

```
cd C:\discord-bridge
powershell -ExecutionPolicy Bypass -File .\restart.ps1
```

It stops the task, kills every leftover process started from that folder, runs
the config check (stops with a clear message if `.env` is wrong), starts the
task and prints the last 10 log lines. Look for a fresh `config ok: ...`, then
`listener starting: version 0.3.1 ...` and `online as ...`. `-Target <folder>`
restarts another install folder.

Config errors (bad token, missing intent, empty guild/channel/trusted list) stop it instead of
looping; fix `.env` and run `.\restart.ps1`.

## Everyday commands

| | |
|---|---|
| status + last log lines | `.\status.ps1` |
| restart after editing .env (Admin) | `powershell -ExecutionPolicy Bypass -File .\restart.ps1` |
| run in a window (debug) | `.\run.ps1` (stop the task first) |
| config check only | `.\.venv\Scripts\python.exe -m discord_bridge --check` |
| update | `.\update.ps1 -Target C:\discord-bridge` (from the new unzipped folder) |
| remove | `.\uninstall.ps1` (add `-Purge` to also delete .venv, data, logs, .env) |

## Payload sent to the webhook

`Authorization: Bearer <GROK_BOT_GROK_WEBHOOK_KEY>`, compact UTF-8 JSON, in this order:

```
correlation_id, reply_mode="discord_rest", guild_id, channel_id, message_id,
batch_has_trusted, trusted_author_ids, omitted_count,
messages[{message_id, author_id, author_name, trusted, text, timestamp}],
history[{author, author_id, trusted, is_bot, text, timestamp}]
```

Caps: 1500 chars per message, ~4000 chars for all batch messages (oldest dropped,
counted in `omitted_count`), history 12 messages / 3000 chars / 600 per entry.
The log line `waking ... body_chars=N` shows each wake's size.

## Notes

- Don't run this and another listener on the same bot token at the same time:
  both would forward every message.
- Discord app settings needed: Message Content Intent ON; bot permissions View
  Channels, Send Messages, Read Message History (68608). No Administrator.
- `.env` is locked to your user, SYSTEM and Administrators by install.ps1.
