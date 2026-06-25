#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.local/host-bot"

mkdir -p "${RUNTIME_DIR}"
cd "${ROOT_DIR}"

exec flock -n -E 0 "${RUNTIME_DIR}/bot.lock" bash -c '
    while ! timeout 1 bash -c "</dev/tcp/127.0.0.1/10808" 2>/dev/null; do
        sleep 2
    done

    while ! timeout 1 bash -c "</dev/tcp/127.0.0.1/6380" 2>/dev/null; do
        sleep 2
    done

    while true; do
        .venv/bin/pybabel compile -d app/locales -D bot &&
        .venv/bin/alembic -c app/db/alembic.ini upgrade head &&
        .venv/bin/python -m app

        exit_code=$?
        printf "%s host bot exited with code %s; restarting in 10 seconds\n" \
            "$(date -u "+%Y-%m-%dT%H:%M:%SZ")" "${exit_code}"
        sleep 10
    done
'
