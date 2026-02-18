#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEDULE="${1:-15 * * * *}"
KEEP_DAYS="${KEEP_DAYS:-14}"
TAG="# 3xui-shop-db-backup"
CRON_CMD="cd $ROOT_DIR && KEEP_DAYS=$KEEP_DAYS ./scripts/backup_db.sh >> $ROOT_DIR/backups/backup.log 2>&1"

mkdir -p "$ROOT_DIR/backups"

existing_cron="$(crontab -l 2>/dev/null || true)"
filtered_cron="$(printf "%s\n" "$existing_cron" | rg -v "3xui-shop-db-backup" || true)"
new_entry="$SCHEDULE $CRON_CMD $TAG"

{
  printf "%s\n" "$filtered_cron"
  printf "%s\n" "$new_entry"
} | sed '/^$/d' | crontab -

echo "[cron] installed backup job:"
echo "$new_entry"
