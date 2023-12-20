FROM python:3.12-slim

WORKDIR /app

RUN pip3 install --no-cache-dir pipenv
COPY Pipfile Pipfile.lock ./
RUN pipenv install --deploy --system
RUN pip3 uninstall -y pipenv

COPY . ./

# check max 30 minutes between main loop iterations
# consider SLEEP and BACKOFF_SLEEP config
HEALTHCHECK CMD test "$(find /tmp/liveness -mmin -30)" || exit 1

CMD ["python3", "/app/telegram_bot.py"]
