"""
Gate for /api/internal/* routes.

Cloudflare Tunnel dials http://127.0.0.1:8000, so REMOTE_ADDR is loopback for
public traffic to api.apidiscoverysolution.uk. A loopback check on its own
does not make these routes unreachable. cloudflared always adds CF-* and
forwarding headers; a direct caller on the host (Hermes, a gate script) does
not. Rejecting those headers closes the tunnel path even when the shared
secret leaks.

intelligence_assign has no payload signature, so it also requires
X-Internal-Token (INTERNAL_API_TOKEN). Fail closed when that setting is
missing or shorter than 16 characters. agent-events keeps HMAC
(X-A2A-Signature / WEBHOOK_SECRET) as its credential — Hermes cannot attach
an extra header to the push — and the same direct-loopback rule so the
tunnel cannot reach it.
"""
from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)

_LOOPBACK = frozenset({"127.0.0.1", "::1"})

# Headers that mean the request crossed a proxy or the Cloudflare edge.
# A direct loopback client does not set these. X-Forwarded-* is included
# because cloudflared sets them; they are not trusted as a client address.
_FORWARDED_META = frozenset(
    {
        "HTTP_FORWARDED",
        "HTTP_TRUE_CLIENT_IP",
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_FORWARDED_HOST",
        "HTTP_X_FORWARDED_PROTO",
        "HTTP_X_ORIGINAL_FORWARDED_FOR",
        "HTTP_X_REAL_IP",
    }
)

_MIN_TOKEN_LEN = 16


def _client_ip(request: HttpRequest) -> str:
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _edge_header_names(request: HttpRequest) -> list[str]:
    found: list[str] = []
    for key, value in request.META.items():
        if not value or not isinstance(value, str):
            continue
        if key in _FORWARDED_META or key.startswith("HTTP_CF_"):
            found.append(key)
    return found


def direct_loopback_or_response(request: HttpRequest) -> JsonResponse | None:
    """403 unless this is a direct loopback call with no edge/proxy headers."""
    ip = _client_ip(request)
    if ip not in _LOOPBACK:
        logger.warning("internal route rejected REMOTE_ADDR=%s", ip or "-")
        return JsonResponse(
            {"detail": "forbidden", "code": "forbidden_remote"},
            status=403,
        )
    edge = _edge_header_names(request)
    if edge:
        logger.warning(
            "internal route rejected edge headers=%s",
            ",".join(sorted(edge)),
        )
        return JsonResponse(
            {"detail": "forbidden", "code": "forbidden_edge"},
            status=403,
        )
    return None


def internal_token_or_response(request: HttpRequest) -> JsonResponse | None:
    """403/503 shared-secret gate. Unset or short token refuses every call."""
    expected = getattr(settings, "INTERNAL_API_TOKEN", "") or ""
    if len(expected) < _MIN_TOKEN_LEN:
        logger.error("INTERNAL_API_TOKEN unset or too short — refusing internal route")
        return JsonResponse(
            {"detail": "internal api token not configured", "code": "misconfigured"},
            status=503,
        )
    provided = request.headers.get("X-Internal-Token") or ""
    if not hmac.compare_digest(provided, expected):
        logger.warning("internal route rejected bad X-Internal-Token")
        return JsonResponse(
            {"detail": "forbidden", "code": "forbidden"},
            status=403,
        )
    return None
