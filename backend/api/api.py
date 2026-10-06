"""
API v1 — django-ninja routers.

Phase 0 surface:
  GET  /api/v1/version
  POST /api/v1/auth/login
  POST /api/v1/auth/refresh

Phase 1.5 boards:
  /api/v1/boards/...  (see api.boards)
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django_ratelimit.core import is_ratelimited
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from api.assist import router as assist_router
from api.auth import BearerAuth, issue_token, login_with_password, user_from_token
from api.boards import router as boards_router
from api.inventory import router as inventory_router
from api.items import router as items_router
from api.purchasing import router as purchasing_router
from api.recipes import router as recipes_router
from api.sections import router as sections_router
from api.station_log import router as station_log_router
from api.walks import router as walks_router


api = NinjaAPI(
    title="Evolving Cook API",
    version=settings.CONTRACT_VERSION,
    urls_namespace="api",
    openapi_url="/openapi.json",
    docs_url="/docs",
    description=(
        "Backend contract for Evolving Cook. "
        "Auth: Bearer token from /auth/login (Django signing, 30 days). "
        "401 is never a reason to drop client data — re-auth and retry. "
        "Walk batch submit 401: re-auth and retry the batch; never discard line payloads. "
        "Phase 1.5: /boards/* MEP service boards (covers never required). "
        "Phase 2: /walks/* lifecycle + /purchasing/* PO draft→send + delivery receipt. "
        "Phase 3: /inventory/* append-only stock ledger (balances, movements, waste, "
        "count_adjustment, transfer). Delivery complete → receipt movements; "
        "walk submit/lock → theoretical + unexplained variance (never auto-correct). "
        "Phase 4: /boards/* full planner — banquet BEO covers + waves + WaveAllocation "
        "(one line across waves), produce scale formula "
        "proposed_qty = scaling_covers * template.yield_per_cover (null yield → null proposed), "
        "canteen produce qty entered (not covers-derived), day close + outturn. "
        "Covers never required outside banquet*. "
        "D12/D14: line notes (today) + template_notes (dish template, every day) + "
        "item notes/house_made. NOTE→ASSIST v2: note-save auto-enqueues parse_note; "
        "board lines carry pending_proposal inline; accept target line|template|item. "
        "D15: /sections/* section mode (counts|ordering, null until chef chooses); "
        "BoardOut carries section_mode, mode_prompt_needed, guided, mode_recommendation, prep_plan. "
        "Phase 5: /assist/* AssistProposal accept/reject + jobs (Hermes A2A); "
        "B15 explode via POST /assist/explode. "
        "Internal agent-events is NOT on /api/v1."
    ),
)

api.add_router("/boards", boards_router)
api.add_router("/boards", station_log_router)
api.add_router("/sections", sections_router)
api.add_router("/items", items_router)
api.add_router("/walks", walks_router)
api.add_router("/purchasing", purchasing_router)
api.add_router("/inventory", inventory_router)
api.add_router("/assist", assist_router)
api.add_router("/recipes", recipes_router)


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
