from pathlib import Path

from aiohttp import ClientTimeout
from llconfig import Config
from llconfig.converters import bool_like

config = Config()

config.init("LOGGING_LEVEL", str, "INFO")

config.init("HTTP_TIMEOUT", lambda val: ClientTimeout(total=int(val)), ClientTimeout(total=10))  # seconds
config.init("HTTP_RAISE_FOR_STATUS", bool_like, True)

config.init("STATE", Path, Path("/state/state.json"))
config.init("LIVENESS", Path, Path("/tmp/liveness"))

config.init("TELEGRAM_BOT_TOKEN", str, None)

config.init("SLEEP", int, 600)  # seconds
config.init("BACKOFF_SLEEP", int, 1200)  # seconds

config.init("SENTRY_DSN", str, None)
config.init("SENTRY_ENVIRONMENT", str, "production")
