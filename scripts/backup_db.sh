#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-$ROOT_DIR/app/data/bot_database.sqlite3}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/db}"
KEEP_DAYS="${KEEP_DAYS:-14}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "[backup] database file not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/bot_database_${timestamp}.sqlite3"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB_PATH" ".timeout 5000" ".backup '$backup_file'"
else
  cp "$DB_PATH" "$backup_file"
fi

sha256sum "$backup_file" > "${backup_file}.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -name "bot_database_*.sqlite3" -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name "bot_database_*.sqlite3.sha256" -mtime +"$KEEP_DAYS" -delete

echo "[backup] created: $backup_file"
