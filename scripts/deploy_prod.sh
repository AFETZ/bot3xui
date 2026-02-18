#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${STATE_DIR:-$ROOT_DIR/.ops}"
REMOTE="${REMOTE:-afetz}"
TARGET_REF="${1:-main}"

cd "$ROOT_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "[deploy] tracked files are dirty. Commit/stash changes before deploy." >&2
  exit 1
fi

mkdir -p "$STATE_DIR"

previous_commit="$(git rev-parse HEAD)"

"$ROOT_DIR/scripts/backup_db.sh"

git fetch "$REMOTE" --tags

if [[ "$TARGET_REF" == "main" ]]; then
  git switch main >/dev/null
  git pull --ff-only "$REMOTE" main
else
  if git rev-parse --verify "$TARGET_REF^{commit}" >/dev/null 2>&1; then
    git switch --detach "$TARGET_REF" >/dev/null
  elif git rev-parse --verify "$REMOTE/$TARGET_REF^{commit}" >/dev/null 2>&1; then
    git switch --detach "$REMOTE/$TARGET_REF" >/dev/null
  else
    echo "[deploy] ref not found: $TARGET_REF" >&2
    exit 1
  fi
fi

current_commit="$(git rev-parse HEAD)"
echo "$previous_commit" > "$STATE_DIR/rollback_commit"
echo "$current_commit" > "$STATE_DIR/current_commit"
echo "$TARGET_REF" > "$STATE_DIR/current_ref"

docker compose up -d --build bot
docker compose ps bot
docker compose logs --tail=60 bot

echo "[deploy] complete: $current_commit"
