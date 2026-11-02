# xcontest-rss-monitor

Telegram bot that watches [XContest](https://www.xcontest.org) pilots and posts their new flights into a chat.

It polls the XContest RSS flight feed for all registered pilots, and posts every flight newer than the last one seen.
Pilots rejected by the feed (HTTP 400) and chats the bot can no longer post to are unregistered automatically.

## Commands

- `/register <XCONTEST-USERNAME>` - start watching a pilot in this chat
- `/unregister <XCONTEST-USERNAME>` - stop watching a pilot in this chat
- `/list` - list pilots watched in this chat
- `/help` - show help

## Configuration

Set via environment variables (in Docker Compose, a `.env` file):

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | - | Bot token from [@BotFather](https://t.me/BotFather), required |
| `SLEEP` | `600` | Seconds between feed checks |
| `BACKOFF_SLEEP` | `1200` | Seconds to wait after a failed request |
| `STATE` | `/state/state.json` | Path to the JSON state file (registered pilots and chats) |
| `LIVENESS` | `/tmp/liveness` | File touched on every loop iteration, used by the Docker healthcheck |
| `HTTP_TIMEOUT` | `10` | HTTP request timeout in seconds |
| `LOGGING_LEVEL` | `INFO` | Python logging level |
| `SENTRY_DSN` | - | Sentry DSN, optional |
| `SENTRY_ENVIRONMENT` | `production` | Sentry environment |

## Running

Locally, with [uv](https://docs.astral.sh/uv/):

```sh
TELEGRAM_BOT_TOKEN=... STATE=state.json LIVENESS=liveness uv run telegram_bot.py
```

With Docker Compose (state is kept in `./state`):

```sh
echo "TELEGRAM_BOT_TOKEN=..." > .env
mkdir -p state
docker compose up -d
```

## Deployment

Every push to `master` builds and publishes `tomasbedrich/xcontest-rss-monitor:latest` to Docker Hub.
On the server, `./deploy.sh` pulls the repository and the image, and restarts the container.
