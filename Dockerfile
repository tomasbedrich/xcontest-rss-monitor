FROM python:3.7

WORKDIR /app

COPY Pipfile Pipfile.lock ./
RUN pip3 install pipenv
RUN pipenv install --deploy --system

COPY monitor.py ./

CMD ["python3", "/app/monitor.py"]
