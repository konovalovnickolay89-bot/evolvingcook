#!/usr/bin/env bash
# One-command deploy for Evolving Cook Django API (user systemd).
# Usage: ./scripts/deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UNIT="evolving-cook-django.service"
VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"
GUNICORN="$VENV/bin/gunicorn"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing $ROOT/.env (mode 600). Copy .env.example and fill secrets." >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv at $VENV — create it and pip install -r requirements.txt" >&2
  exit 1
fi

# Record previous git ref for rollback (best-effort)
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$ROOT" rev-parse HEAD > "$ROOT/.deploy-previous-ref" || true
  echo "previous_ref=$(cat "$ROOT/.deploy-previous-ref" 2>/dev/null || echo none)"
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

export DJANGO_SETTINGS_MODULE=config.settings
echo "== migrate =="
"$PYTHON" manage.py migrate --noinput
echo "== ensure account (unusable password until changepassword) =="
"$PYTHON" scripts/ensure_account.py
echo "== collectstatic =="
"$PYTHON" manage.py collectstatic --noinput
echo "== export openapi =="
"$PYTHON" scripts/export_openapi.py

mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$ROOT/deploy/evolving-cook-django.service" \
  "$HOME/.config/systemd/user/$UNIT"

systemctl --user daemon-reload
systemctl --user enable "$UNIT"
# Prefer restart; if unavailable mid-session, HUP gunicorn master
if systemctl --user restart "$UNIT"; then
  :
else
  echo "systemctl restart unavailable; sending HUP to master" >&2
  MAIN=$(systemctl --user show "$UNIT" -p MainPID --value)
  if [[ -n "$MAIN" && "$MAIN" != "0" ]]; then
    kill -HUP "$MAIN" || true
  else
    systemctl --user start "$UNIT"
  fi
fi
sleep 1
systemctl --user --no-pager --full status "$UNIT" || true

echo "== local health =="
curl -fsS -H "Host: api.apidiscoverysolution.uk" \
  "http://127.0.0.1:8000/api/v1/version" || {
  echo "health check failed" >&2
  exit 1
}
echo
echo "deploy_ok unit=$UNIT bind=127.0.0.1:8000"
