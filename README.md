# grokbot-discord (FeelsBrettMan fork)

Chat with a Grok Bot from a private Discord channel as if it were the normal chat
window, alone or as a small group: no @mention needed, replies follow the whole
conversation, and only allowlisted people in an allowlisted channel can wake it.
**Trusted** people get full control; **chat-only** people can only talk.

Fork of [RudeDude/grokbot-discord](https://github.com/RudeDude/grokbot-discord) (MIT).
It contains two ways to run the bridge:

| | Where the listener runs | How replies get back |
|---|---|---|
| **Windows listener** (`windows-listener/`, recommended) | an always-on Windows PC | the routine posts to Discord REST itself (`box/discord_post.py`) |
| **Box bridge** (`src/grokbot_discord/`, original layout) | the Grok Bot computer | the routine POSTs to the bridge's local `/reply` callback |

## Architecture (Windows listener)

```
Discord channel
   |  Gateway events (Guilds, GuildMessages, MessageContent)
   v
Windows listener (windows-listener/, Task Scheduler, auto-restart)
   |  fail-closed guild/channel allowlists, trusted + chat-only authors
   |  (everyone else and other bots ignored), group batching since the bot's
   |  last post, 3s debounce, one run in flight per channel, catch-up
   |  POST JSON + "Authorization: Bearer <routine webhook key>"
   v
Grok Bot webhook routine  -> wakes the Bot (main chat) with the JSON body
   |  correlation_id first ... messages[] (with trusted flags), history last
   v
Bot re-fetches with box/discord_fetch.py --since <message_id>, then runs
box/discord_post.py on its computer
   |  POST https://discord.com/api/v10/channels/{channel_id}/messages
   |  "Authorization: Bot <token read from a 600 file>", 1900-char chunks
   v
Discord channel  (the listener sees the bot's post -> run finished, older buffered
                  messages dropped as covered -> next batch)
```

While a run is in flight the listener keeps the typing indicator alive. A run
ends when the bot posts in the channel or after 5 minutes.

## Setup

1. **Discord app**: New Application, Bot, turn on **Message Content Intent**, reset
   the token. Invite with scope `bot` and permissions View Channels, Send Messages,
   Read Message History (`68608`). Never Administrator. Use a private server.
2. **Grok Bot routine**: create a routine with a webhook trigger and paste
   [docs/routine-prompt-discord-rest.md](docs/routine-prompt-discord-rest.md) as its
   instruction (fill in the IDs and helper path). Copy its webhook URL and key.
3. **Bot computer**: put the bot token in `~/.config/discord-bridge/secrets/discord_bot_token`
   (`chmod 600`) and copy [examples/allowlist.example.json](examples/allowlist.example.json)
   to `~/.config/discord-bridge/allowlist.json` (`chmod 600`) with your IDs. The
   `box/` helpers read it and refuse everything if it is missing or its channel or
   trusted list is empty. Keep it in sync with the listener's `.env`
   (`DISCORD_TRUSTED_AUTHORS`, `DISCORD_CHAT_AUTHORS`).
4. **Windows PC**: follow [windows-listener/README.md](windows-listener/README.md)
   (`install.ps1`, fill `.env`, auto-start task; `update.ps1` for upgrades).
5. Test: write in the channel. You should see the typing indicator, then a reply.

Run only one listener per bot token, or every message is forwarded twice.

Secrets never go in this repo: `.env`, `secrets/`, `data/state.json` and logs are
git-ignored, and all IDs in examples are placeholders.

## Credits

- **[RudeDude/grokbot-discord](https://github.com/RudeDude/grokbot-discord)** (MIT,
  Don J. Rude): the base of this fork. Python discord.py gateway, fail-closed
  guild/channel/author allowlists, webhook wake with Bearer key, `/reply`
  callback, message splitting, `bots.yaml` routing, tests,
  [COMPARISON.md](COMPARISON.md).
- **[larry-fuqua/discord-grok-bot-kit](https://github.com/larry-fuqua/discord-grok-bot-kit)**
  (MIT): RudeDude adopted the kit's leading bot-name wake, the instant "Got it."
  pickup ack (this fork replaces it with a typing indicator) and the
  `watch.sh` / `ensure-up.sh` keep-alive pattern plus keep-alive routine, as
  described in COMPARISON.md (written by RudeDude, comparing against the kit at
  commit [`0797998`](https://github.com/larry-fuqua/discord-grok-bot-kit/commit/0797998fbcd1e601c4bb42ae661edcc9ab911710)).
  The kit's idea of the Bot posting to Discord REST directly (`bin/discord-send`)
  inspired this fork's `box/discord_post.py`.
- **[RealDragonJT/grok-discord-bridge](https://github.com/RealDragonJT/grok-discord-bridge)**
  (MIT): ideas only, no code. Running the listener on an always-on host instead
  of the Grok Bot computer, and catching up on messages missed while offline.
- **[NinjaProtocol/grokbot-discord-plugin](https://github.com/NinjaProtocol/grokbot-discord-plugin)**
  (MIT): ideas only, no code. Redacting Discord tokens from logs and allowing only
  one Gateway connection per bot token.
- **[lucklypriyansh-2/grok-bot-relay](https://github.com/lucklypriyansh-2/grok-bot-relay)** (MIT):
  the observation that long routine webhook bodies can be truncated, so small
  identifying fields go first.
- The trusted vs chat-only split and group batching (v0.3.0 of the Windows
  listener) are this fork's own design; no outside code.
- Dependencies: [discord.py](https://github.com/Rapptz/discord.py) (MIT),
  [aiohttp](https://github.com/aio-libs/aiohttp) (Apache-2.0),
  [PyYAML](https://github.com/yaml/pyyaml) (MIT, box bridge only).

---

# Box bridge (original grokbot-discord README)

Fork changes in the box bridge: `/reply` only answers a pending wake and posts to
that wake's allowlisted channel; one wake in flight per channel with a 3s
debounce and 15-min expiry; `history` and `message_ids` in the payload; typing
indicator instead of the "Got it." ack; `REQUIRE_MENTION=false` routes to the
default bot; [run-bridge.sh](run-bridge.sh) keep-alive launcher with config in
`~/.config/discord-bridge` ([examples/](examples/)); callback routine prompt in
[docs/routine-prompt-callback.md](docs/routine-prompt-callback.md).

Python Discord gateway for talking to Grok Bots from a private server. One Discord bot, many Grok Bots. Built so you can chat from a phone anywhere Discord works.

Licensed under the [MIT License](LICENSE).

Grok Bot has no Discord inbound plugin. A long-running process holds the Gateway, hears an address (a Discord `@mention`, a mapped role, or a leading bot name), replies **Got it.** immediately, POSTs a webhook ping to wake the target Grok Bot, then posts the real reply when that bot calls back.

```
Discord  --gateway-->  Python process  --POST webhook-->  Grok Bot
     ^                         |
     |                         |  POST /reply
     +------ channel post -----+
```

The webhook returns 200 when the Grok Bot *wakes*, not when it finishes. Replies are async. The pickup ack is not.

## 1. Discord application

1. Open [Discord Developer Portal](https://discord.com/developers/applications) → New Application.
2. Bot → Add Bot. Enable **Message Content Intent**.
3. Reset Token and copy it. That is `DISCORD_BOT_TOKEN`. Never commit it.
4. OAuth2 → URL Generator. Scopes: `bot`. Permissions: View Channels, Send Messages, Read Message History.
5. Open the URL, invite the bot into a **private** server and the channel you will use.
6. Discord Settings → Advanced → Developer Mode. Right-click the server, channel, and your user → Copy ID. Those are the allowlists.

## 2. One webhook routine per Grok Bot

On each Grok Bot:

1. Create a routine with trigger type `webhook`.
2. Use [prompts/webhook-routine.md](prompts/webhook-routine.md) as the prompt.
3. Open the routine panel. Copy the webhook URL (`https://api2.cursor.sh/automations/webhook/<id>`).
4. Copy the sender key. Do not paste the key into chat or git.

The Discord bridge already replies **Got it.** The webhook routine should send the real answer, not another pickup ack.

## 3. Local config

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
cp bots.example.yaml bots.yaml
chmod +x watch.sh ensure-up.sh
```

Fill `.env`:

- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ALLOWLIST`, `DISCORD_CHANNEL_ALLOWLIST`, `DISCORD_AUTHOR_ALLOWLIST` (comma-separated snowflakes)
- `CALLBACK_SECRET` (a long random string the Grok Bots use when they POST replies)
- `GROK_BOT_<NAME>_WEBHOOK_URL` and `GROK_BOT_<NAME>_WEBHOOK_KEY` for each bot in `bots.yaml`

Empty allowlists refuse to start. Empty bots list refuses to start. Missing webhook URL/key refuses to start unless `DRY_RUN=true`.

`bots.yaml` maps names, aliases, and optional Discord role IDs to those env vars. Keys stay in env.

## 4. Run

```bash
.venv/bin/pytest
.venv/bin/python -m grokbot_discord
```

Logs `online as YourBot#1234` when the Gateway is up. The process also listens on `CALLBACK_BIND:CALLBACK_PORT` (default `127.0.0.1:8787`) for `/health` and `/reply`.

Foreground is fine for a first test. For a crash loop, start the watchdog instead:

```bash
./ensure-up.sh
```

Confirm `bridge.log` contains `online as`. `watch.sh` restarts the gateway if it exits.

Dry-run first, no Grok Bot keys required:

```bash
DRY_RUN=true .venv/bin/python -m grokbot_discord
```

Addressed messages are logged as would-POST. Nothing leaves the machine.

## 5. Talk to a bot

In the allowlisted channel, any one of these wakes a Grok Bot. You do not need both a Discord `@` and the bot name.

- `loops ping` or `@loops ping` — first token is a name or alias from `bots.yaml` (leading `@` is optional text, not a Discord mention)
- `@bridge loops ping` — Discord `@mention` of this bot, then the Grok Bot name
- mention a Discord role mapped in `bots.yaml`
- `@bridge ping` — uses `DEFAULT_BOT` / `default:` in yaml if set

The channel gets an instant **Got it.** then the real reply when the Grok Bot calls back.

An unknown name does not fire a webhook. The channel gets `unknown bot. configured: …`.

## 6. Where this runs

Grok Bots on the same Linux machine should use `CALLBACK_PUBLIC_URL=http://127.0.0.1:8787`. If a Grok Bot is elsewhere, bind `CALLBACK_BIND=0.0.0.0` and set `CALLBACK_PUBLIC_URL` to an address that bot can reach (Tailscale is enough). Do not put the sender key or `CALLBACK_SECRET` in the browser or in git.

## Discord bridge watchdog

A scheduled Grok Bot routine named **discord bridge watchdog** is already saved on the live bot. That prompt was not previously in this repo.

This tree now has the keep-alive from [discord-grok-bot-kit](https://github.com/larry-fuqua/discord-grok-bot-kit), adapted here:

- `watch.sh` — restart loop if the gateway process dies
- `ensure-up.sh` — start `watch.sh` if it is not running
- [prompts/keep-alive-routine.md](prompts/keep-alive-routine.md) — in-repo copy of the watchdog prompt, so the live routine can be recreated if it drifts

Point the existing **discord bridge watchdog** routine at `./ensure-up.sh` in this directory. Stay quiet if the listener is already up. Only message the owner if it could not be started.

Optional cron if you do not want to rely on the Grok Bot schedule:

```
@reboot /path/to/grokbot-discord/ensure-up.sh
15 8,12,16,20 * * * /path/to/grokbot-discord/ensure-up.sh
```

## Routing and filters

A message is dropped when:

- the author is this Discord bot
- guild, channel, or author is not allowlisted (allowlisted *bots* are accepted; there is no blanket `author.bot` drop)
- `REQUIRE_MENTION=true` and the message is not addressed: no Discord `@mention` of this bot, no mapped role mention, and the first token is not a configured bot name/alias
- `message_id` was already handled
- the channel already has `IN_FLIGHT_PER_CHANNEL` wakes waiting on a reply (default 2)

## Layout

- `src/grokbot_discord/` — Gateway, filters, routing, webhook client, reply callback
- `prompts/webhook-routine.md` — paste into each Grok Bot webhook routine
- `prompts/keep-alive-routine.md` — in-repo copy of the **discord bridge watchdog** scheduled routine
- `watch.sh`, `ensure-up.sh` — crash loop and start-if-missing
- `.github/workflows/ci.yml` — `ruff` + `pytest` on PRs
