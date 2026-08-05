"""
D15 prep plan helpers — guided banqueting steps as AssistProposals.

Deterministic scaffold when LLM offline; LLM path must still supply `working`.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from planning.models import ProductionLine, ServiceSection
from planning.section_modes import PROMPT_VERSION, assert_job_allowed, get_setting

logger = logging.getLogger(__name__)


def _dec(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def catalogue_candidates_for_section(section: str, *, limit: int = 80) -> list[dict]:
    """Candidate items for LLM context — never invent names outside this list."""
    from catalog.models import Item

    qs = (
        Item.objects.filter(active=True)
        .order_by("name")
        .values("id", "name", "base_unit", "house_made")[:limit]
    )
    # Prefer items linked to templates/lines in section when possible
    linked_ids = set(
        ProductionLine.objects.filter(
            service_section__section=section,
            item_id__isnull=False,
        ).values_list("item_id", flat=True)[:limit]
    )
    out: list[dict] = []
    seen: set[int] = set()
    for row in Item.objects.filter(pk__in=linked_ids).order_by("name").values(
        "id", "name", "base_unit", "house_made"
    ):
        seen.add(row["id"])
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "unit": row["base_unit"],
                "house_made": bool(row["house_made"]),
            }
        )
    for row in qs:
        if row["id"] in seen:
            continue
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "unit": row["base_unit"],
                "house_made": bool(row["house_made"]),
            }
        )
        if len(out) >= limit:
            break
    return out


def validate_prep_step_body(body: dict) -> str:
    """Return parse_error string or empty if OK."""
    if not isinstance(body, dict):
        return "prep_step must be object"
    if str(body.get("target") or "") != "prep_step":
        return "target must be prep_step"
    title = str(body.get("title") or "").strip()
    if not title:
        return "title required"
    phase = str(body.get("phase") or "").strip().lower()
    if phase not in {"mep", "day_of"}:
        return "phase must be mep|day_of"
    working = str(body.get("working") or "").strip()
    if not working:
        return "working required (show the arithmetic / why)"
    if phase == "mep" and body.get("clock_time"):
        # soft: clear rather than fail? Spec says MEP gets NO clock_time
        body["clock_time"] = None
    if phase == "day_of" and not body.get("clock_time"):
        return "day_of steps require clock_time"
    return ""


def _service_time_for_section(sec: ServiceSection) -> time:
    waves = list(sec.waves.all()) if hasattr(sec, "waves") else []
    times = [w.serve_at for w in waves if getattr(w, "serve_at", None)]
    if times:
        return min(times)
    # banquet default lunch service
    return time(12, 30)


def build_scaffold_prep_steps(
    sec: ServiceSection,
    *,
    service_date: date,
) -> list[dict[str, Any]]:
    """
    Deterministic MEP-first scaffold from board lines + covers.
    Each step includes working text. LLM may replace via prep_plan job later.
    """
    covers = sec.covers
    lines = list(
        ProductionLine.objects.filter(service_section=sec)
        .select_related("template", "item")
        .order_by("sort_order", "id")
    )
    steps: list[dict[str, Any]] = []
    idx = 0
    # MEP: produce/prep lines first by kind weight
    mep_kinds = {"prep", "sauce", "stock"}
    mep_lines = [ln for ln in lines if ln.kind in mep_kinds or ln.mode == "produce"]
    day_lines = [ln for ln in lines if ln not in mep_lines]

    for ln in mep_lines:
        qty = ln.planned_qty if ln.planned_qty is not None else ln.proposed_qty
        ypc = None
        if ln.template_id and ln.template and ln.template.yield_per_cover is not None:
            ypc = ln.template.yield_per_cover
        if qty is None and covers is not None and ypc is not None:
            qty = (Decimal(covers) * ypc).quantize(Decimal("0.001"))
        working_parts = []
        if covers is not None and ypc is not None:
            working_parts.append(
                f"{covers} covers × {ypc} {ln.unit or 'ea'}/cover = {qty}"
            )
        elif qty is not None:
            working_parts.append(f"planned/proposed on board = {qty} {ln.unit or ''}".strip())
        else:
            working_parts.append(
                "qty unset — set covers + yield_per_cover or enter planned_qty"
            )
        working_parts.append("MEP first: longest lead before service day.")
        steps.append(
            {
                "target": "prep_step",
                "title": f"Prep — {ln.name}",
                "phase": "mep",
                "order_index": idx,
                "clock_time": None,
                "qty": _dec(qty),
                "unit": ln.unit or None,
                "working": " ".join(working_parts),
                "watch_out": None,
                "line_id": ln.pk,
                "service_date": str(service_date),
                "section": sec.section,
            }
        )
        idx += 1

    svc = _service_time_for_section(sec)
    # Backwards plan: finish 30 min before service, then -20 min steps
    base = datetime.combine(service_date, svc)
    offset_min = 30
    for ln in day_lines:
        clock_dt = base - timedelta(minutes=offset_min)
        clock_s = clock_dt.strftime("%H:%M")
        qty = ln.planned_qty if ln.planned_qty is not None else ln.proposed_qty
        working = (
            f"Finish/hold before service {svc.strftime('%H:%M')}: "
            f"clock {clock_s} is service minus {offset_min}m. "
        )
        if qty is not None:
            working += f"Board qty {qty} {ln.unit or ''}".strip()
        else:
            working += "Confirm qty on board before fire."
        steps.append(
            {
                "target": "prep_step",
                "title": f"Day-of — {ln.name}",
                "phase": "day_of",
                "order_index": idx,
                "clock_time": clock_s,
                "qty": _dec(qty),
                "unit": ln.unit or None,
                "working": working,
                "watch_out": "Hot-hold / allergen check before pass"
                if ln.kind == "dish"
                else None,
                "line_id": ln.pk,
                "service_date": str(service_date),
                "section": sec.section,
            }
        )
        idx += 1
        offset_min += 15

    return steps


@transaction.atomic
def ensure_prep_plan_proposals(
    *,
    service_date: date,
    section: str,
    model_name: str = "scaffold",
) -> list[AssistProposal]:
    """
    Create pending prep_step proposals if guided counts and none pending for this day.
    Idempotent per (section, service_date, order_index) while pending.
    """
    assert_job_allowed(kind="prep_plan", section=section)

    from planning.models import ServiceDay

    try:
        day = ServiceDay.objects.get(service_date=service_date)
        sec = ServiceSection.objects.prefetch_related("waves").get(
            service_day=day, section=section
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("prep_plan section missing: %s", exc)
        return []

    # existing pending prep for this day+section
    existing = list(
        AssistProposal.objects.filter(
            kind="prep_plan",
            status=AssistProposal.Status.PENDING,
        ).order_by("id")
    )
    pending_for = []
    for p in existing:
        ctx = p.context if isinstance(p.context, dict) else {}
        prop = p.proposal if isinstance(p.proposal, dict) else {}
        if (
            ctx.get("section") == section
            and str(ctx.get("service_date") or prop.get("service_date") or "")
            == str(service_date)
        ):
            pending_for.append(p)
    if pending_for:
        return pending_for

    steps = build_scaffold_prep_steps(sec, service_date=service_date)
    created: list[AssistProposal] = []
    for step in steps:
        err = validate_prep_step_body(step)
        prop = dict(step)
        prop["prompt_version"] = PROMPT_VERSION
        p = AssistProposal.objects.create(
            kind="prep_plan",
            context={
                "section": section,
                "service_date": str(service_date),
                "covers": sec.covers,
            },
            proposal=prop,
            rationale=str(step.get("working") or "")[:500],
            model=model_name,
            status=AssistProposal.Status.PENDING,
            parse_error=err,
        )
        created.append(p)
    return created


def prep_plan_board_payload(section: str, service_date: date) -> dict | None:
    """Board embed: pending + accepted prep steps for guided sections."""
    try:
        st = get_setting(section)
    except Exception:  # noqa: BLE001
        return None
    if st.mode != "counts" or not st.guided:
        return None

    steps_out: list[dict] = []
    qs = AssistProposal.objects.filter(kind="prep_plan").order_by("id")
    for p in qs[:200]:
        ctx = p.context if isinstance(p.context, dict) else {}
        prop = p.proposal if isinstance(p.proposal, dict) else {}
        if ctx.get("section") != section and prop.get("section") != section:
            continue
        sd = str(ctx.get("service_date") or prop.get("service_date") or "")
        if sd != str(service_date):
            continue
        steps_out.append(
            {
                "proposal_id": p.pk,
                "status": p.status,
                "accept_able": (
                    p.status == AssistProposal.Status.PENDING
                    and not p.parse_error
                    and not validate_prep_step_body(dict(prop))
                ),
                "title": prop.get("title"),
                "phase": prop.get("phase"),
                "order_index": prop.get("order_index"),
                "clock_time": prop.get("clock_time"),
                "qty": prop.get("qty"),
                "unit": prop.get("unit"),
                "working": prop.get("working"),
                "watch_out": prop.get("watch_out"),
                "target": "prep_step",
                "parse_error": p.parse_error or None,
                "model": p.model or "",
                "prompt_version": prop.get("prompt_version") or PROMPT_VERSION,
            }
        )
    steps_out.sort(
        key=lambda s: (
            0 if s.get("phase") == "mep" else 1,
            s.get("order_index") if s.get("order_index") is not None else 999,
            s.get("proposal_id") or 0,
        )
    )
    return {
        "service_date": str(service_date),
        "section": section,
        "steps": steps_out,
    }
