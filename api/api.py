"""
API v1 — django-ninja routers.

Phase 0 surface:
  GET  /api/v1/version
  POST /api/v1/auth/login
  POST /api/v1/auth/refresh
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from api.auth import BearerAuth, issue_token, login_with_password, user_from_token


api = NinjaAPI(
    title="Evolving Cook API",
    version=settings.CONTRACT_VERSION,
    urls_namespace="api",
    openapi_url="/openapi.json",
    docs_url="/docs",
    description=(
        "Backend contract for Evolving Cook. "
        "Auth: Bearer token from /auth/login (Django signing, 30 days). "
        "401 is never a reason to drop client data — re-auth and retry."
    ),
)


class VersionOut(Schema):
    app_version: str
    contract_version: str
    api: str = "v1"


class LoginIn(Schema):
    email: str
    password: str


class TokenOut(Schema):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    on_401: str = (
        "Re-authenticate and retry the request. "
        "Do not discard walk/board payload on 401."
    )


class RefreshIn(Schema):
    access_token: str | None = None


class ErrorOut(Schema):
    detail: str
    code: str


@api.get("/version", response=VersionOut, auth=None, tags=["meta"])
def version(request: HttpRequest):
    return {
        "app_version": settings.APP_VERSION,
        "contract_version": settings.CONTRACT_VERSION,
        "api": "v1",
    }


@api.post(
    "/auth/login",
    response={200: TokenOut, 401: ErrorOut, 429: ErrorOut},
    auth=None,
    tags=["auth"],
)
def auth_login(request: HttpRequest, body: LoginIn):
    # App-side rate limit (edge WAF may also cover /api/v1/auth/*)
    if is_ratelimited(
        request,
        group="auth_login",
        key="ip",
        rate=settings.AUTH_LOGIN_RATELIMIT,
        method="POST",
        increment=True,
    ):
        return 429, {
            "detail": "Too many login attempts. Try again later.",
            "code": "rate_limited",
        }

    user = login_with_password(body.email, body.password)
    if user is None:
        return 401, {"detail": "Invalid email or password", "code": "invalid_credentials"}

    token = issue_token(user)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.AUTH_TOKEN_MAX_AGE,
        "on_401": (
            "Re-authenticate and retry the request. "
            "Do not discard walk/board payload on 401."
        ),
    }


@api.post(
    "/auth/refresh",
    response={200: TokenOut, 401: ErrorOut},
    auth=None,
    tags=["auth"],
)
def auth_refresh(request: HttpRequest, body: RefreshIn = None):
    raw = None
    if body and body.access_token:
        raw = body.access_token
    else:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.lower().startswith("bearer "):
            raw = header[7:].strip()
    if not raw:
        return 401, {"detail": "Missing token", "code": "missing_token"}
    user = user_from_token(raw)
    if user is None:
        return 401, {
            "detail": (
                "Token invalid or expired — re-authenticate and retry; "
                "do not drop data"
            ),
            "code": "token_expired_or_invalid",
        }
    token = issue_token(user)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.AUTH_TOKEN_MAX_AGE,
        "on_401": (
            "Re-authenticate and retry the request. "
            "Do not discard walk/board payload on 401."
        ),
    }


bearer_auth = BearerAuth()
