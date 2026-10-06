#!/usr/bin/env bash
# Publish backend/ as the backend-rooted deploy branch (backend-deploy).
#
# The server runs a standalone backend checkout (manage.py at its root)
# and auto-deploys from origin/backend-deploy. git-subtree split chokes
# on this repo's squashed subtree history, so snapshot instead: each run
# commits the current backend/ tree, parented on the previous
# backend-deploy commit so the server's --ff-only pull always works.
#
# Run from the monorepo after any backend change lands:
#   backend/scripts/push-backend-deploy.sh
set -euo pipefail

ROOT="$(git -C "$(cd "$(dirname "$0")" && pwd)" rev-parse --show-toplevel)"
cd "$ROOT"

BRANCH="backend-deploy"
SRC="$(git rev-parse --short HEAD)"
TREE="$(git rev-parse "HEAD:backend")"

PARENT_ARGS=()
if git rev-parse --verify --quiet "refs/remotes/origin/$BRANCH" >/dev/null; then
  PARENT="$(git rev-parse "refs/remotes/origin/$BRANCH")"
  if [[ "$(git rev-parse "$PARENT^{tree}")" == "$TREE" ]]; then
    echo "backend-deploy already matches backend/ of $SRC — nothing to push."
    exit 0
  fi
  PARENT_ARGS=(-p "$PARENT")
fi

COMMIT="$(git commit-tree "$TREE" "${PARENT_ARGS[@]}" \
  -m "backend-deploy: backend/ of $SRC" \
  -m "Snapshot of the monorepo backend tree for the server checkout.")"
git branch -f "$BRANCH" "$COMMIT"
git push -u origin "$BRANCH:$BRANCH"
echo "pushed $BRANCH = $COMMIT (backend/ of $SRC)"
