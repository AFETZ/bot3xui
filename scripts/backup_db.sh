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
elif command -v python3 >/dev/null 2>&1; then
  python3 - "$DB_PATH" "$backup_file" <<'PY'
import sqlite3
import sys

source_path, backup_path = sys.argv[1:3]

source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=5)
target = sqlite3.connect(backup_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
else
  cp "$DB_PATH" "$backup_file"
fi

sha256sum "$backup_file" > "${backup_file}.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -name "bot_database_*.sqlite3" -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name "bot_database_*.sqlite3.sha256" -mtime +"$KEEP_DAYS" -delete

echo "[backup] created: $backup_file"
