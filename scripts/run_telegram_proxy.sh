#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XRAY_DIR="${ROOT_DIR}/.local/xray"

mkdir -p "${XRAY_DIR}/logs"
cd "${ROOT_DIR}"

exec flock -n -E 0 "${XRAY_DIR}/xray.lock" bash -c '
    while true; do
        .local/xray/bin/xray run -c .local/xray/config.json
        exit_code=$?
        printf "%s Telegram proxy exited with code %s; restarting in 5 seconds\n" \
            "$(date -u "+%Y-%m-%dT%H:%M:%SZ")" "${exit_code}"
        sleep 5
    done
'
