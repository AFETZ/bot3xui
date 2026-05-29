#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/backups/migration}"
DB_PATH="${DB_PATH:-$ROOT_DIR/app/data/bot_database.sqlite3}"
XUI_DB_PATH="${XUI_DB_PATH:-}"

timestamp="$(date -u +%Y%m%d_%H%M%S)"
bundle_name="3xui-shop_migration_${timestamp}"
work_dir="$(mktemp -d)"
stage_dir="$work_dir/$bundle_name"
bundle_path="$OUTPUT_DIR/${bundle_name}.tar.gz"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  echo "[migration] .env not found in $ROOT_DIR" >&2
  exit 1
fi

if [[ ! -f "plans.json" ]]; then
  echo "[migration] plans.json not found in $ROOT_DIR" >&2
  exit 1
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "[migration] database file not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
mkdir -p "$stage_dir/source" "$stage_dir/runtime/app/data" "$stage_dir/runtime/.local" "$stage_dir/metadata"

echo "[migration] creating fresh SQLite backup..."
"$ROOT_DIR/scripts/backup_db.sh" >/dev/null

latest_db_backup="$(
  find "$ROOT_DIR/backups/db" -maxdepth 1 -type f -name 'bot_database_*.sqlite3' \
    -printf '%T@ %p\n' | sort -n | tail -n 1 | cut -d' ' -f2-
)"

if [[ -z "$latest_db_backup" || ! -f "$latest_db_backup" ]]; then
  echo "[migration] failed to locate fresh database backup" >&2
  exit 1
fi

echo "[migration] packaging source tree..."
tar \
  --exclude='./.git' \
  --exclude='./.venv' \
  --exclude='./.pytest_cache' \
  --exclude='./.mypy_cache' \
  --exclude='./.cache' \
  --exclude='./.ecc' \
  --exclude='./.local' \
  --exclude='./.ops' \
  --exclude='./backups' \
  --exclude='./logs' \
  --exclude='./app/logs' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='*.mo' \
  --exclude='./app/data/*.db' \
  --exclude='./app/data/*.sqlite3' \
  --exclude='./.env' \
  --exclude='./.env.staging' \
  -cf - . | tar -xf - -C "$stage_dir/source"

install -m 600 ".env" "$stage_dir/runtime/.env"
install -m 644 "plans.json" "$stage_dir/runtime/plans.json"
install -m 600 "$latest_db_backup" "$stage_dir/runtime/app/data/bot_database.sqlite3"

if [[ -d "$ROOT_DIR/.local/redis-data" ]]; then
  echo "[migration] packaging Redis data snapshot..."
  tar -C "$ROOT_DIR/.local" -cf - redis-data | tar -xf - -C "$stage_dir/runtime/.local"
fi

if [[ -n "$XUI_DB_PATH" ]]; then
  if [[ ! -f "$XUI_DB_PATH" ]]; then
    echo "[migration] XUI_DB_PATH is set but file does not exist: $XUI_DB_PATH" >&2
    exit 1
  fi
  mkdir -p "$stage_dir/runtime/x-ui"
  install -m 600 "$XUI_DB_PATH" "$stage_dir/runtime/x-ui/x-ui.db"
fi

{
  echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "root_dir=$ROOT_DIR"
  echo "git_commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_branch=$(git branch --show-current 2>/dev/null || echo unknown)"
  echo "tracked_dirty_files=$(git status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')"
  echo "db_backup=$latest_db_backup"
  echo
  echo "[sha256]"
  sha256sum "$latest_db_backup" ".env" "plans.json"
} > "$stage_dir/metadata/manifest.txt"

if command -v python3 >/dev/null 2>&1; then
  python3 - "$latest_db_backup" > "$stage_dir/metadata/db_summary.txt" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
con = sqlite3.connect(db_path)
tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
for table in ("servers", "users", "transactions", "promocodes", "referrals", "invites"):
    if table in tables:
        count = con.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"{table}={count}")

if "servers" in tables and "users" in tables:
    print()
    print("[servers]")
    for row in con.execute(
        """
        select s.id, s.name, s.max_clients, s.online, count(u.id) as assigned_users
        from servers s
        left join users u on u.server_id = s.id
        group by s.id, s.name, s.max_clients, s.online
        order by s.id
        """
    ):
        server_id, name, max_clients, online, assigned_users = row
        print(
            f"id={server_id} name={name} max_clients={max_clients} "
            f"online={online} assigned_users={assigned_users}"
        )

con.close()
PY
fi

cat > "$stage_dir/metadata/restore_notes.txt" <<'EOF'
Restore outline:
1. Extract this archive on the new host.
2. Copy source/. into the target project directory.
3. Copy runtime/.env to .env.
4. Copy runtime/plans.json to plans.json.
5. Copy runtime/app/data/bot_database.sqlite3 to app/data/bot_database.sqlite3.
6. Copy runtime/.local/redis-data to .local/redis-data if you want to preserve FSM/payment transient state.
7. If runtime/x-ui/x-ui.db exists, restore it to the 3X-UI host only while x-ui is stopped.
8. Start Redis and bot, then run smoke checks.
EOF

echo "[migration] creating archive..."
tar -C "$work_dir" -czf "$bundle_path" "$bundle_name"
sha256sum "$bundle_path" > "$bundle_path.sha256"

echo "[migration] created: $bundle_path"
echo "[migration] checksum: $bundle_path.sha256"
