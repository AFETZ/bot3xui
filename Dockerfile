FROM python:3.12-slim-bullseye

ENV PYTHONPATH=/

COPY pyproject.toml poetry.lock /
RUN pip install --no-cache-dir poetry && poetry install --no-interaction --no-root

COPY ./app /app
