FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . ./

ENV PYTHONPATH="/app"
ENV PATH="/app/.venv/bin:$PATH"

# check max 30 minutes between main loop iterations
# consider SLEEP and BACKOFF_SLEEP config
HEALTHCHECK CMD test "$(find /tmp/liveness -mmin -30)" || exit 1

STOPSIGNAL SIGINT

CMD ["uv", "run", "/app/telegram_bot.py"]
