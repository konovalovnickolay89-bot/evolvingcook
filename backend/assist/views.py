"""
Internal A2A push receiver — POST /api/internal/agent-events

Not on /api/v1. CSRF exempt. Auth = HMAC only (X-A2A-Signature).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from assist.services import AssistError, handle_agent_event

logger = logging.getLogger(__name__)


def _client_ip(request: HttpRequest) -> str:
    # Prefer direct REMOTE_ADDR; do not trust X-Forwarded-For for loopback gate
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _is_loopback(ip: str) -> bool:
    return ip in {"127.0.0.1", "::1", "localhost"}


def verify_a2a_signature(payload: dict, header_sig: str, secret: str) -> bool:
    """
    D11 / Hermes algorithm:
      body_for_mac = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
      hmac-sha256 hex
    """
    if not secret or not header_sig:
        return False
    sig = header_sig.strip()
    # Accept raw hex only (not sha256= prefix)
    if sig.lower().startswith("sha256="):
        sig = sig.split("=", 1)[1].strip()
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


@csrf_exempt
@require_POST
def agent_events(request: HttpRequest) -> HttpResponse:
    if settings.A2A_INTERNAL_LOOPBACK_ONLY and not _is_loopback(_client_ip(request)):
        logger.warning(
            "agent-events rejected non-loopback REMOTE_ADDR=%s",
            _client_ip(request),
        )
        return JsonResponse(
            {"detail": "loopback only", "code": "forbidden_remote"},
            status=403,
        )

    secret = settings.WEBHOOK_SECRET or ""
    if not secret:
        logger.error("WEBHOOK_SECRET unset — refusing agent-events")
        return JsonResponse(
            {"detail": "webhook not configured", "code": "misconfigured"},
            status=503,
        )

    raw = request.body or b""
    try:
        payload = json.loads(raw.decode("utf-8") if raw else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse(
            {"detail": "invalid json", "code": "bad_json"},
            status=400,
        )
    if not isinstance(payload, dict):
        return JsonResponse(
            {"detail": "payload must be object", "code": "bad_json"},
            status=400,
        )

    header_sig = request.headers.get("X-A2A-Signature") or request.META.get(
        "HTTP_X_A2A_SIGNATURE", ""
    )
    if not verify_a2a_signature(payload, header_sig, secret):
        logger.warning("agent-events bad signature task hint=%s", payload.keys())
        return JsonResponse(
            {"detail": "invalid signature", "code": "bad_signature"},
            status=401,
        )

    try:
        result = handle_agent_event(payload)
    except AssistError as exc:
        logger.warning("agent-events business error: %s", exc)
        return JsonResponse(
            {"detail": str(exc), "code": getattr(exc, "code", "assist_error")},
            status=400,
        )
    except Exception:  # noqa: BLE001
        logger.exception("agent-events unhandled")
        return JsonResponse(
            {"detail": "internal error", "code": "internal"},
            status=500,
        )

    return JsonResponse(result, status=200)
