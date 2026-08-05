"""
D15 Section settings API — /api/v1/sections/...
"""
from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema

from api.auth import BearerAuth
from planning.section_modes import (
    SectionModeError,
    list_section_settings,
    setting_view,
    upsert_section_mode,
)

router = Router(tags=["sections"], auth=BearerAuth())


class ErrorOut(Schema):
    detail: str
    code: str


class SectionSettingOut(Schema):
    section: str
    mode: str | None = None
    guided: bool = False
    decided_at: str | None = None
    mode_prompt_needed: bool = True
    mode_recommendation: str
    updated_at: str | None = None


class SectionSettingsListOut(Schema):
    settings: list[SectionSettingOut]


class SectionSettingPatchIn(Schema):
    mode: str  # counts | ordering
    guided: bool | None = None


@router.get(
    "/settings",
    response=SectionSettingsListOut,
    summary="All six section mode settings (mode null until chef chooses)",
)
def get_all_settings(request: HttpRequest):
    return {"settings": list_section_settings()}


@router.patch(
    "/{section}/settings",
    response={200: SectionSettingOut, 400: ErrorOut, 404: ErrorOut},
    summary="Upsert section mode (counts|ordering). Never silent default — chef choice.",
)
def patch_section_settings(
    request: HttpRequest, section: str, body: SectionSettingPatchIn
):
    try:
        obj = upsert_section_mode(
            section, mode=body.mode, guided=body.guided
        )
    except SectionModeError as exc:
        code = 404 if exc.code == "bad_section" else 400
        return code, {"detail": exc.message, "code": exc.code}
    return 200, setting_view(obj).as_dict()
