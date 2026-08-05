"""
D15 Section modes — recommendations, settings CRUD, mode gates.

Never silently default mode. Recommendations are hints for FE only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from planning.models import SectionSetting, ServiceSectionCode

# Assist recommendation only — never auto-written as mode.
SECTION_MODE_RECOMMENDATIONS: dict[str, str] = {
    ServiceSectionCode.SKYBAR.value: SectionSetting.Mode.ORDERING.value,
    ServiceSectionCode.A_LA_CARTE.value: SectionSetting.Mode.ORDERING.value,
    ServiceSectionCode.CANTEEN.value: SectionSetting.Mode.COUNTS.value,
    ServiceSectionCode.BREAKFAST_BUFFET.value: SectionSetting.Mode.COUNTS.value,
    ServiceSectionCode.BANQUETING.value: SectionSetting.Mode.COUNTS.value,
    ServiceSectionCode.BANQUET_BUFFET.value: SectionSetting.Mode.COUNTS.value,
}

GUIDED_DEFAULT_SECTIONS = frozenset(
    {
        ServiceSectionCode.BANQUETING.value,
        ServiceSectionCode.BANQUET_BUFFET.value,
    }
)

VALID_MODES = frozenset(
    {SectionSetting.Mode.COUNTS.value, SectionSetting.Mode.ORDERING.value}
)

# Job kinds allowed per mode (parse_note always allowed once section known).
# qty/prep drafts blocked when mode is null or ordering.
ORDERING_ALLOWED_KINDS = frozenset(
    {
        "parse_note",
        "menu_completeness",
        "order_suggest",
    }
)
COUNTS_ALLOWED_KINDS = frozenset(
    {
        "parse_note",
        "menu_completeness",
        "order_suggest",
        "qty_draft",
        "prep_plan",
        "morning_qty",
    }
)
# Before chef chooses — only reversible note parse
UNSET_ALLOWED_KINDS = frozenset({"parse_note"})

# Proposal targets gated by mode
ORDERING_TARGETS = frozenset({"order_packs", "component_fix", "line", "template", "item"})
COUNTS_TARGETS = frozenset(
    {
        "planned_qty",
        "order_packs",
        "new_line",
        "component_fix",
        "prep_step",
        "line",
        "template",
        "item",
    }
)

PROMPT_VERSION = "section-modes-v1"


class SectionModeError(Exception):
    def __init__(self, message: str, code: str = "section_mode_error"):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SectionModeView:
    section: str
    mode: str | None
    guided: bool
    decided_at: str | None
    mode_prompt_needed: bool
    mode_recommendation: str
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "mode": self.mode,
            "guided": self.guided,
            "decided_at": self.decided_at,
            "mode_prompt_needed": self.mode_prompt_needed,
            "mode_recommendation": self.mode_recommendation,
            "updated_at": self.updated_at,
        }


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def default_guided_for(section: str) -> bool:
    return section in GUIDED_DEFAULT_SECTIONS


def recommend_mode(section: str) -> str:
    return SECTION_MODE_RECOMMENDATIONS.get(
        section, SectionSetting.Mode.COUNTS.value
    )


def ensure_all_section_settings() -> list[SectionSetting]:
    """Idempotent seed of six rows; mode stays null."""
    out: list[SectionSetting] = []
    for code, _label in ServiceSectionCode.choices:
        obj, _created = SectionSetting.objects.get_or_create(
            section=code,
            defaults={
                "mode": None,
                "guided": default_guided_for(code),
                "decided_at": None,
            },
        )
        out.append(obj)
    return out


def get_setting(section: str) -> SectionSetting:
    if section not in {c.value for c in ServiceSectionCode}:
        raise SectionModeError(f"unknown section {section}", code="bad_section")
    ensure_all_section_settings()
    return SectionSetting.objects.get(section=section)


def setting_view(obj: SectionSetting) -> SectionModeView:
    return SectionModeView(
        section=obj.section,
        mode=obj.mode or None,
        guided=bool(obj.guided),
        decided_at=_iso(obj.decided_at),
        mode_prompt_needed=obj.mode is None or obj.mode == "",
        mode_recommendation=recommend_mode(obj.section),
        updated_at=_iso(obj.updated_at),
    )


def list_section_settings() -> list[dict[str, Any]]:
    rows = ensure_all_section_settings()
    # stable kitchen order
    order = [c.value for c in ServiceSectionCode]
    rows_sorted = sorted(rows, key=lambda r: order.index(r.section) if r.section in order else 99)
    return [setting_view(r).as_dict() for r in rows_sorted]


@transaction.atomic
def upsert_section_mode(
    section: str,
    *,
    mode: str,
    guided: bool | None = None,
) -> SectionSetting:
    if section not in {c.value for c in ServiceSectionCode}:
        raise SectionModeError(f"unknown section {section}", code="bad_section")
    mode_s = (mode or "").strip().lower()
    if mode_s not in VALID_MODES:
        raise SectionModeError(
            "mode must be 'counts' or 'ordering'", code="bad_mode"
        )
    ensure_all_section_settings()
    obj = SectionSetting.objects.select_for_update().get(section=section)
    obj.mode = mode_s
    if guided is not None:
        obj.guided = bool(guided)
    elif obj.decided_at is None and section in GUIDED_DEFAULT_SECTIONS:
        # first decision keeps banquet guided default unless FE sent guided
        obj.guided = True
    obj.decided_at = timezone.now()
    obj.save()
    return obj


def board_mode_fields(section: str) -> dict[str, Any]:
    """Fields merged into BoardOut — one-request rule."""
    try:
        obj = get_setting(section)
    except SectionModeError:
        return {
            "section_mode": None,
            "mode_prompt_needed": True,
            "guided": default_guided_for(section),
            "mode_recommendation": recommend_mode(section),
        }
    v = setting_view(obj)
    return {
        "section_mode": v.mode,
        "mode_prompt_needed": v.mode_prompt_needed,
        "guided": v.guided,
        "mode_recommendation": v.mode_recommendation,
    }


def allowed_kinds_for_mode(mode: str | None) -> frozenset[str]:
    if mode is None or mode == "":
        return UNSET_ALLOWED_KINDS
    if mode == SectionSetting.Mode.ORDERING:
        return ORDERING_ALLOWED_KINDS
    if mode == SectionSetting.Mode.COUNTS:
        return COUNTS_ALLOWED_KINDS
    return UNSET_ALLOWED_KINDS


def assert_job_allowed(*, kind: str, section: str | None) -> None:
    """
    Raise SectionModeError(mode_gate) when kind is not allowed for section's mode.
    parse_note without section still allowed (line-scoped notes).
    """
    kind_s = (kind or "").strip()
    if not section:
        # no section context — only parse_note
        if kind_s != "parse_note":
            raise SectionModeError(
                f"kind {kind_s} requires section context",
                code="mode_gate",
            )
        return
    obj = get_setting(section)
    allowed = allowed_kinds_for_mode(obj.mode)
    # guided prep_plan only when guided + counts
    if kind_s == "prep_plan":
        if obj.mode != SectionSetting.Mode.COUNTS or not obj.guided:
            raise SectionModeError(
                "prep_plan requires mode=counts and guided=true",
                code="mode_gate",
            )
        return
    if kind_s not in allowed:
        raise SectionModeError(
            f"kind {kind_s} not allowed for section {section} "
            f"mode={obj.mode or 'unset'}",
            code="mode_gate",
        )


def assert_target_allowed(*, target: str, section: str | None) -> None:
    t = (target or "").strip().lower()
    if not section:
        if t not in {"line", "template", "item"}:
            raise SectionModeError(
                f"target {t} requires section mode context",
                code="mode_gate",
            )
        return
    obj = get_setting(section)
    mode = obj.mode
    if mode == SectionSetting.Mode.ORDERING:
        allowed = ORDERING_TARGETS
    elif mode == SectionSetting.Mode.COUNTS:
        allowed = COUNTS_TARGETS
        if t == "prep_step" and not obj.guided:
            raise SectionModeError(
                "prep_step requires guided=true",
                code="mode_gate",
            )
    else:
        # unset — note tiers only
        allowed = frozenset({"line", "template", "item"})
    if t not in allowed:
        raise SectionModeError(
            f"target {t} not allowed for section {section} mode={mode or 'unset'}",
            code="mode_gate",
        )


def allows_quantity_ui(section: str) -> bool:
    obj = get_setting(section)
    return obj.mode == SectionSetting.Mode.COUNTS
