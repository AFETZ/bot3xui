#!/usr/bin/env bash
set -euo pipefail

wiki_remote="${1:-git@github.com:AFETZ/bot3xui.wiki.git}"
tmp_dir="$(mktemp -d)"
repo_root="$(git rev-parse --show-toplevel)"

cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

git clone "$wiki_remote" "$tmp_dir/wiki"
rsync -a --delete --exclude .git "$repo_root/docs/wiki/" "$tmp_dir/wiki/"

cd "$tmp_dir/wiki"
git add .

source_ref="$(git -C "$repo_root" rev-parse --short HEAD)"
if git diff --cached --quiet; then
  echo "GitHub Wiki is already up to date."
  exit 0
fi

git commit -m "docs: sync wiki from ${source_ref}"
git push
