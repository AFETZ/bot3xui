#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${STATE_DIR:-$ROOT_DIR/.ops}"
ROLLBACK_FILE="$STATE_DIR/rollback_commit"

cd "$ROOT_DIR"

if [[ ! -f "$ROLLBACK_FILE" ]]; then
  echo "[rollback] rollback commit file not found: $ROLLBACK_FILE" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "[rollback] tracked files are dirty. Commit/stash changes before rollback." >&2
  exit 1
fi

target_commit="$(cat "$ROLLBACK_FILE")"
if [[ -z "$target_commit" ]]; then
  echo "[rollback] rollback target is empty." >&2
  exit 1
fi

current_commit="$(git rev-parse HEAD)"

"$ROOT_DIR/scripts/backup_db.sh"

git switch --detach "$target_commit" >/dev/null

echo "$current_commit" > "$ROLLBACK_FILE"
echo "$target_commit" > "$STATE_DIR/current_commit"
echo "rollback:$target_commit" > "$STATE_DIR/current_ref"

docker compose up -d --build bot
docker compose ps bot
docker compose logs --tail=60 bot

echo "[rollback] complete: $target_commit"
