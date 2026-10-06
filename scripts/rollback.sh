#!/usr/bin/env bash
# One-command rollback: restore previous git tree + redeploy.
# Usage: ./scripts/rollback.sh
# Requires a prior successful deploy that wrote .deploy-previous-ref.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REF_FILE="$ROOT/.deploy-previous-ref"
if [[ ! -f "$REF_FILE" ]]; then
  echo "No $REF_FILE — cannot rollback. Manually checkout a known-good commit, then ./scripts/deploy.sh" >&2
  exit 1
fi
PREV="$(tr -d '[:space:]' < "$REF_FILE")"
if [[ -z "$PREV" ]]; then
  echo "Empty previous ref" >&2
  exit 1
fi

if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repo — file-level rollback only: restart unit after manual restore" >&2
  systemctl --user restart evolving-cook-django.service
  exit 0
fi

echo "Rolling back to $PREV"
# Stash only if dirty so checkout can proceed; leave stash for human
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  git -C "$ROOT" stash push -u -m "rollback-auto-$(date -u +%Y%m%dT%H%M%SZ)" || true
fi
git -C "$ROOT" checkout "$PREV"
exec "$ROOT/scripts/deploy.sh"
