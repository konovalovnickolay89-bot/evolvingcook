#!/usr/bin/env bash
# Run from an EXTERNAL host shell (SSH/console), NOT from Hermes TUI/gateway.
# Restarts hermes-gateway so A2A :9900 binds, then prints agent-card status.
set -euo pipefail
echo "== before =="
systemctl --user is-active hermes-gateway.service || true
ss -ltnp 2>/dev/null | grep -E '9900' || echo "9900 not listening"
echo "== restart =="
systemctl --user restart hermes-gateway.service
sleep 3
echo "== after =="
systemctl --user is-active hermes-gateway.service
ss -ltnp 2>/dev/null | grep -E '9900' || echo "9900 still not listening"
code=$(curl -sS -m 8 -o /tmp/a2a-agent-card.json -w '%{http_code}' \
  http://127.0.0.1:9900/.well-known/agent-card.json || echo fail)
echo "agent-card HTTP: $code"
head -c 800 /tmp/a2a-agent-card.json 2>/dev/null || true
echo
if [[ "$code" == "200" ]]; then
  echo "A2A_OK — tell Hermes: verify live round-trip and complete"
  exit 0
fi
echo "A2A_FAIL — check: journalctl --user -u hermes-gateway -n 80 --no-pager"
exit 1
