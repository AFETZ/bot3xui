#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

status_line="$(docker compose ps bot | tail -n 1)"
if [[ "$status_line" != *"Up"* ]]; then
  echo "[smoke] bot container is not running" >&2
  docker compose ps bot
  exit 1
fi

domain_raw="$(grep -E '^BOT_DOMAIN=' .env | head -n 1 | cut -d'=' -f2- || true)"
if [[ -z "$domain_raw" ]]; then
  echo "[smoke] BOT_DOMAIN is not set in .env" >&2
  exit 1
fi

if [[ "$domain_raw" == http://* || "$domain_raw" == https://* ]]; then
  base_url="$domain_raw"
else
  base_url="https://$domain_raw"
fi

webhook_code="$(curl -k -s -o /dev/null -w "%{http_code}" "$base_url/webhook" || true)"
yookassa_code="$(curl -k -s -o /dev/null -w "%{http_code}" "$base_url/yookassa" || true)"

echo "[smoke] /webhook HTTP $webhook_code"
echo "[smoke] /yookassa HTTP $yookassa_code"

if [[ "$webhook_code" != "405" ]]; then
  echo "[smoke] unexpected /webhook status: $webhook_code" >&2
  exit 1
fi

if [[ "$yookassa_code" != "405" ]]; then
  echo "[smoke] unexpected /yookassa status: $yookassa_code" >&2
  exit 1
fi

if docker compose logs --tail=200 bot | rg -q "Traceback|CRITICAL"; then
  echo "[smoke] warning: suspicious log lines found in last 200 lines" >&2
  docker compose logs --tail=200 bot | rg "Traceback|CRITICAL" -n || true
fi

echo "[smoke] checks passed"
