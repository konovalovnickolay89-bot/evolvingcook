#!/usr/bin/env bash
# Pull-and-deploy when the tracked branch moves on GitHub. Cron-safe.
#
# One-time setup on the server (crontab -e):
#   */5 * * * * EVOLVINGCOOK_DEPLOY_BRANCH=main /path/to/repo/backend/scripts/auto-deploy.sh >> $HOME/evolvingcook-deploy.log 2>&1
#
# Point EVOLVINGCOOK_DEPLOY_BRANCH at a feature branch to track it instead.
# Exits quietly when nothing changed. Refuses (loudly) if the server
# checkout has local commits or edits — it never overwrites server-local
# work; fix the checkout by hand, then runs resume.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BRANCH="${EVOLVINGCOOK_DEPLOY_BRANCH:-main}"
LOCK="$ROOT/.auto-deploy.lock"

cd "$ROOT"

exec 9>"$LOCK"
if ! flock -n 9; then
  exit 0 # previous run still going
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "$(date -Is) auto-deploy: checkout is dirty — not touching it." >&2
  exit 1
fi

git fetch origin "$BRANCH" --quiet
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
if [[ "$LOCAL" == "$REMOTE" ]]; then
  exit 0 # up to date
fi

echo "$(date -Is) auto-deploy: $LOCAL -> $REMOTE ($BRANCH)"
git checkout --quiet "$BRANCH"
if ! git merge --ff-only --quiet "origin/$BRANCH"; then
  echo "$(date -Is) auto-deploy: local history diverged from origin/$BRANCH — resolve by hand." >&2
  exit 1
fi

"$ROOT/backend/scripts/deploy.sh"
echo "$(date -Is) auto-deploy: done at $(git rev-parse --short HEAD)"
