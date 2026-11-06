"""
Auth helpers: signed Bearer tokens (Django signing).

Lifetime is settings.AUTH_TOKEN_MAX_AGE (env AUTH_TOKEN_MAX_AGE_SECONDS,
default 30 days). A walk is 30–60 min offline in a cold room; the token
may expire mid-walk. A 401 must be clearly distinguishable from a data error so
the frontend re-auths and retries. A 401 is NEVER a reason to drop data.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.http import HttpRequest
from ninja.security import HttpBearer


@dataclass
class AuthUser:
    id: int
    email: str


class BearerAuth(HttpBearer):
    """django-ninja security class. Returns AuthUser or None."""

    def authenticate(self, request, token: str) -> AuthUser | None:
        user = user_from_token(token)
        if user is None:
            return None
        request.auth_user = user
        return user


def issue_token(user) -> str:
    payload = {"uid": user.pk, "email": user.email}
    return signing.dumps(payload, salt=settings.AUTH_TOKEN_SALT)


def user_from_token(token: str):
    try:
        data = signing.loads(
            token,
            salt=settings.AUTH_TOKEN_SALT,
            max_age=settings.AUTH_TOKEN_MAX_AGE,
        )
    except signing.BadSignature:
        return None
    except signing.SignatureExpired:
        return None
    User = get_user_model()
    try:
        user = User.objects.get(pk=data["uid"], is_active=True)
    except (User.DoesNotExist, KeyError, TypeError):
        return None
    return user


def login_with_password(email: str, password: str):
    """Authenticate by email (USERNAME_FIELD may be username)."""
    User = get_user_model()
    email = (email or "").strip().lower()
    if not email or not password:
        return None
    # Prefer email lookup; Django default User uses username
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.filter(username__iexact=email).first()
    if user is None:
        return None
    # authenticate needs USERNAME_FIELD
    authed = authenticate(username=user.get_username(), password=password)
    if authed is None or not authed.is_active:
        return None
    return authed


def client_ip_for_login(request: HttpRequest) -> str:
    """IP bucket for login rate limiting.

    The tunnel's REMOTE_ADDR is always 127.0.0.1. cloudflared overwrites
    CF-Connecting-IP with the real client, so that header is the per-IP key
    when it is a valid address. X-Forwarded-For is ignored: the client can
    prepend it and would otherwise mint a fresh bucket per request.
    """
    cf = (request.META.get("HTTP_CF_CONNECTING_IP") or "").split(",")[0].strip()
    if cf:
        try:
            return str(ipaddress.ip_address(cf))
        except ValueError:
            pass
    remote = (request.META.get("REMOTE_ADDR") or "").strip()
    try:
        return str(ipaddress.ip_address(remote))
    except ValueError:
        return "unknown"


def login_ip_key(_group: str, request: HttpRequest) -> str:
    return client_ip_for_login(request)


def username_for_login(request: HttpRequest) -> str:
    """Normalised login name from the JSON body. Missing name shares one bucket."""
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "-"
    if not isinstance(payload, dict):
        return "-"
    email = str(payload.get("email") or payload.get("username") or "").strip().lower()
    return email or "-"


def login_username_key(_group: str, request: HttpRequest) -> str:
    return username_for_login(request)


def token_payload_for_openapi() -> dict[str, Any]:
    return {
        "token_type": "Bearer",
        "expires_in_seconds": settings.AUTH_TOKEN_MAX_AGE,
        "note": (
            "401 on protected endpoints means re-auth then retry. "
            "Never drop client-held walk/board data because of 401."
        ),
    }
