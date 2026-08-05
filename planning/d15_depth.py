"""
D15.1 depth — qty drafts, prep LLM apply, walk shortfall order, covers refresh.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from planning.models import ProductionLine, ServiceDay, ServiceSection
from planning.section_modes import PROMPT_VERSION, get_setting

logger = logging.getLogger(__name__)


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@transaction.atomic
def ensure_qty_draft_proposals(
    *,
    service_date: date,
    section: str,
    kind: str = "qty_draft",
) -> list[AssistProposal]:
    """
    Counts-mode: one planned_qty proposal per produce/replenish line with a
    suggested qty (proposed, covers×yield, or par). MEP-ish order by kind.
    """
    st = get_setting(section)
    if st.mode != "counts":
        return []

    try:
        day = ServiceDay.objects.get(service_date=service_date)
        sec = ServiceSection.objects.prefetch_related("waves").get(
            service_day=day, section=section
        )
    except Exception:
        return []

    # kind weight: prep/sauce first
    weight = {"prep": 0, "sauce": 1, "stock": 2, "dish": 3, "buffet": 4, "service": 5}
    lines = list(
        ProductionLine.objects.filter(service_section=sec)
        .select_related("template", "item")
        .order_by("sort_order", "id")
    )
    lines.sort(key=lambda ln: (weight.get(ln.kind, 9), ln.sort_order, ln.pk))

    covers = sec.covers
    if covers is None:
        from planning.services import _scaling_covers

        covers = _scaling_covers(sec)

    created: list[AssistProposal] = []
    for ln in lines:
        if ln.mode == ProductionLine.Mode.CHECK:
            continue
        # skip if pending qty already
        if AssistProposal.objects.filter(
            status=AssistProposal.Status.PENDING,
            kind__in=("qty_draft", "morning_qty"),
            context__line_id=ln.pk,
            context__service_date=str(service_date),
        ).exists():
            continue

        qty = ln.proposed_qty if ln.proposed_qty is not None else ln.planned_qty
        working_parts: list[str] = []
        ypc = None
        if ln.template_id and ln.template and ln.template.yield_per_cover is not None:
            ypc = ln.template.yield_per_cover
        if qty is None and covers is not None and ypc is not None:
            qty = (Decimal(int(covers)) * ypc).quantize(Decimal("0.001"))
            working_parts.append(f"{covers} covers × {ypc} = {qty}")
        elif qty is not None:
            working_parts.append(f"board proposed/planned = {qty}")
        else:
            working_parts.append(
                "no covers×yield and no proposed — chef enters planned_qty"
            )

        if ln.mode == ProductionLine.Mode.REPLENISH and ln.par_level is not None:
            working_parts.append(f"par on line = {ln.par_level}")

        phase = "mep" if ln.kind in ("prep", "sauce", "stock") else "day_of"
        clock_time = None
        if kind == "morning_qty" and phase == "day_of":
            # Backwards from service: default 12:30, or earliest wave serve_at
            from datetime import datetime, time, timedelta

            svc = time(12, 30)
            try:
                waves = list(sec.waves.all()) if hasattr(sec, "waves") else []
                times = [w.serve_at for w in waves if getattr(w, "serve_at", None)]
                if times:
                    svc = min(times)
            except Exception:
                pass
            # stagger by order index among day_of lines
            day_i = sum(1 for c in created if (c.proposal or {}).get("phase") == "day_of")
            offset = 30 + day_i * 15
            clock_dt = datetime.combine(service_date, svc) - timedelta(minutes=offset)
            clock_time = clock_dt.strftime("%H:%M")
            working_parts.append(
                f"clock {clock_time} = service {svc.strftime('%H:%M')} minus {offset}m"
            )

        body = {
            "target": "planned_qty",
            "line_id": ln.pk,
            "line_name": ln.name,
            "planned_qty": _f(qty),
            "unit": ln.unit or "ea",
            "working": " · ".join(working_parts),
            "phase": phase,
            "order_index": len(created),
            "clock_time": clock_time,
            "prompt_version": PROMPT_VERSION,
            "rationale": f"qty draft for {ln.name}",
        }
        p = AssistProposal.objects.create(
            kind=kind if kind in ("qty_draft", "morning_qty") else "qty_draft",
            context={
                "section": section,
                "service_date": str(service_date),
                "line_id": ln.pk,
            },
            proposal=body,
            rationale=body["rationale"],
            model="scaffold",
            status=AssistProposal.Status.PENDING,
        )
        created.append(p)
    return created


def build_qty_draft_prompt(context: dict) -> str:
    from planning.prep_plan import catalogue_candidates_for_section

    section = str(context.get("section") or "")
    try:
        cands = catalogue_candidates_for_section(section, limit=40)
    except Exception:
        cands = []
    return (
        f"TASK kind=qty_draft\nprompt_version={PROMPT_VERSION}\n"
        "Return STRICT JSON: {\"proposals\":[{\"target\":\"planned_qty\",\"line_id\":int,"
        "\"planned_qty\":number|null,\"working\":string,\"rationale\":string|null}]}\n"
        "working REQUIRED. Prefer reversible numbers. Never invent lines — use board only.\n"
        f"context={context}\ncandidates={cands}\n"
    )


@transaction.atomic
def apply_prep_plan_llm_payload(
    *,
    job: AssistJob | None,
    task_id: str,
    payload: dict,
    context: dict,
    model_name: str = "",
) -> dict[str, Any]:
    """
    Replace pending prep_step proposals for section+date with LLM steps.
    Requires non-empty working on each step.
    """
    from planning.prep_plan import validate_prep_step_body
    from planning.section_modes import PROMPT_VERSION as PV

    section = context.get("section") or payload.get("section")
    sd = str(context.get("service_date") or payload.get("service_date") or "")
    steps = payload.get("steps")
    if not section or not sd:
        return {"ok": False, "action": "bad_context"}
    if not isinstance(steps, list) or not steps:
        return {"ok": False, "action": "no_steps"}

    # Drop pending scaffold/LLM prep for this day (keep accepted)
    pending = AssistProposal.objects.filter(
        kind="prep_plan",
        status=AssistProposal.Status.PENDING,
        context__section=section,
        context__service_date=sd,
    )
    deleted, _ = pending.delete()

    created_ids: list[int] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        body = dict(step)
        body["target"] = "prep_step"
        body.setdefault("order_index", i)
        body.setdefault("service_date", sd)
        body.setdefault("section", section)
        body["prompt_version"] = body.get("prompt_version") or PV
        err = validate_prep_step_body(body)
        p = AssistProposal.objects.create(
            kind="prep_plan",
            context={
                "section": section,
                "service_date": sd,
                "covers": context.get("covers"),
            },
            proposal=body,
            rationale=str(body.get("working") or body.get("rationale") or "")[:500],
            model=model_name or "a2a",
            status=AssistProposal.Status.PENDING,
            task_id=f"{task_id}:{i}" if task_id else None,
            job=job,
            parse_error=err,
        )
        created_ids.append(p.pk)

    if job is not None:
        job.status = AssistJob.Status.SUCCEEDED
        job.error = ""
        if task_id and not job.task_id:
            job.task_id = task_id
        job.save(update_fields=["status", "error", "task_id", "updated_at"])

    return {
        "ok": True,
        "action": "prep_plan_replaced",
        "deleted_pending": deleted,
        "proposal_ids": created_ids,
        "task_id": task_id,
    }


@transaction.atomic
def apply_qty_draft_llm_payload(
    *,
    job: AssistJob | None,
    task_id: str,
    payload: dict,
    context: dict,
    kind: str = "qty_draft",
) -> dict[str, Any]:
    proposals = payload.get("proposals") or payload.get("lines") or []
    if not isinstance(proposals, list):
        return {"ok": False, "action": "no_proposals"}
    section = context.get("section")
    sd = str(context.get("service_date") or "")
    created = []
    for i, row in enumerate(proposals):
        if not isinstance(row, dict):
            continue
        body = dict(row)
        body["target"] = "planned_qty"
        body["prompt_version"] = PROMPT_VERSION
        working = str(body.get("working") or "").strip()
        err = "" if working else "working required"
        if body.get("line_id") is None:
            err = err or "line_id required"
        p = AssistProposal.objects.create(
            kind=kind,
            context={
                "section": section,
                "service_date": sd,
                "line_id": body.get("line_id"),
            },
            proposal=body,
            rationale=str(body.get("rationale") or working)[:500],
            model="a2a",
            status=AssistProposal.Status.PENDING,
            task_id=f"{task_id}:q{i}" if task_id else None,
            job=job,
            parse_error=err,
        )
        created.append(p.pk)
    if job is not None:
        job.status = AssistJob.Status.SUCCEEDED
        job.error = ""
        if task_id and not job.task_id:
            job.task_id = task_id
        job.save(update_fields=["status", "error", "task_id", "updated_at"])
    return {"ok": True, "action": "qty_draft_created", "proposal_ids": created}


def refresh_prep_plan_after_covers(service_date: date, section: str) -> int:
    """
    After covers change: drop pending prep steps and re-scaffold with new maths.
    Accepted steps stay (chef already locked them).
    """
    try:
        st = get_setting(section)
    except Exception:
        return 0
    if st.mode != "counts" or not st.guided:
        return 0

    deleted, _ = AssistProposal.objects.filter(
        kind="prep_plan",
        status=AssistProposal.Status.PENDING,
        context__section=section,
        context__service_date=str(service_date),
    ).delete()

    from planning.prep_plan import ensure_prep_plan_proposals

    created = ensure_prep_plan_proposals(
        service_date=service_date, section=section, model_name="scaffold-covers-refresh"
    )
    logger.info(
        "prep refresh covers section=%s date=%s deleted=%s created=%s",
        section,
        service_date,
        deleted,
        len(created),
    )
    return len(created)


def walk_shortfall_order_lines(walk_id: int) -> list[dict[str, Any]]:
    """
    Mirror propose_orders_from_walk shortfall math without writing POs.
    Returns order_packs lines [{item_id, packs, why, name}].
    """
    from decimal import ROUND_CEILING

    from catalog.models import Item
    from purchasing.services import preferred_supplier_item
    from walks.models import Walk, WalkLine
    from walks.services import par_for

    try:
        walk = Walk.objects.get(pk=walk_id)
    except Walk.DoesNotExist:
        return []

    lines = list(
        WalkLine.objects.filter(walk_id=walk_id)
        .select_related("item", "area")
        .order_by("sort_order", "id")
    )
    weekday = timezone.localdate().weekday()
    agg: dict[int, dict[str, Any]] = {}
    for ln in lines:
        if ln.skipped:
            continue
        if ln.qty_base is None and ln.counted_qty is None:
            continue
        counted = ln.qty_base if ln.qty_base is not None else Decimal("0")
        par = par_for(ln.item_id, ln.area_id, weekday)
        if par is None:
            continue
        b = agg.setdefault(
            ln.item_id,
            {"par_sum": Decimal("0"), "counted_sum": Decimal("0"), "item": ln.item},
        )
        b["par_sum"] += par
        b["counted_sum"] += counted

    out: list[dict] = []
    for item_id, b in agg.items():
        shortfall = b["par_sum"] - b["counted_sum"]
        if shortfall <= 0:
            continue
        si = preferred_supplier_item(item_id)
        pack_qty = (si.pack_qty if si and si.pack_qty else None) or Decimal("1")
        packs = (shortfall / pack_qty).to_integral_value(rounding=ROUND_CEILING)
        if packs <= 0:
            continue
        name = b["item"].name if b.get("item") else str(item_id)
        out.append(
            {
                "item_id": item_id,
                "supplier_item_id": si.pk if si else None,
                "name": name,
                "packs": float(packs),
                "why": (
                    f"walk shortfall: par {b['par_sum']} − counted {b['counted_sum']} "
                    f"= {shortfall}; ceil/{pack_qty} → {packs} packs"
                ),
            }
        )
    return out


def ensure_order_suggest_from_walk(
    *,
    walk_id: int,
    section: str | None = None,
    service_date: date | None = None,
) -> AssistProposal | None:
    lines = walk_shortfall_order_lines(walk_id)
    if not lines:
        return None
    sd = service_date or timezone.localdate()
    sec = section or ""
    # Prefer merge into existing pending order_suggest for section+date
    qs = AssistProposal.objects.filter(
        kind="order_suggest",
        status=AssistProposal.Status.PENDING,
    ).order_by("-id")
    existing = None
    for p in qs[:30]:
        ctx = p.context if isinstance(p.context, dict) else {}
        if sec and ctx.get("section") != sec:
            continue
        if str(ctx.get("service_date") or "") not in ("", str(sd)):
            continue
        existing = p
        break

    body_lines = lines
    if existing:
        prop = existing.proposal if isinstance(existing.proposal, dict) else {}
        old = list(prop.get("lines") or [])
        seen = {int(x["item_id"]) for x in old if isinstance(x, dict) and x.get("item_id")}
        for row in lines:
            if int(row["item_id"]) not in seen:
                old.append(row)
                seen.add(int(row["item_id"]))
        body_lines = old
        prop["lines"] = body_lines
        prop["target"] = "order_packs"
        prop["prompt_version"] = PROMPT_VERSION
        prop["source"] = "walk+board"
        existing.proposal = prop
        existing.rationale = f"{len(body_lines)} order lines (walk shortfall merged)"
        existing.context = {
            **(existing.context if isinstance(existing.context, dict) else {}),
            "walk_id": walk_id,
            "service_date": str(sd),
            "section": sec or existing.context.get("section") if isinstance(existing.context, dict) else sec,
        }
        existing.save()
        return existing

    return AssistProposal.objects.create(
        kind="order_suggest",
        context={
            "section": sec,
            "service_date": str(sd),
            "walk_id": walk_id,
        },
        proposal={
            "target": "order_packs",
            "lines": body_lines,
            "service_date": str(sd),
            "section": sec,
            "source": "walk",
            "prompt_version": PROMPT_VERSION,
            "rationale": f"{len(body_lines)} items short vs par on walk #{walk_id}",
        },
        rationale=f"{len(body_lines)} items short vs par on walk #{walk_id}",
        model="scaffold-walk",
        status=AssistProposal.Status.PENDING,
    )


def qty_draft_board_payload(*, section: str, service_date: date) -> dict | None:
    """Separate FE strip from prep_plan — pending qty_draft/morning_qty proposals."""
    try:
        st = get_setting(section)
    except Exception:
        return None
    if st.mode != "counts":
        return None
    steps = []
    qs = (
        AssistProposal.objects.filter(
            kind__in=("qty_draft", "morning_qty"),
            status__in=(
                AssistProposal.Status.PENDING,
                AssistProposal.Status.ACCEPTED,
            ),
        )
        .order_by("id")
    )
    for p in qs[:200]:
        ctx = p.context if isinstance(p.context, dict) else {}
        prop = p.proposal if isinstance(p.proposal, dict) else {}
        if ctx.get("section") != section and prop.get("section") != section:
            continue
        sd = str(ctx.get("service_date") or prop.get("service_date") or "")
        if sd != str(service_date):
            continue
        steps.append(
            {
                "proposal_id": p.pk,
                "kind": p.kind,
                "status": p.status,
                "accept_able": (
                    p.status == AssistProposal.Status.PENDING
                    and not p.parse_error
                    and prop.get("target") == "planned_qty"
                ),
                "line_id": prop.get("line_id") or ctx.get("line_id"),
                "line_name": prop.get("line_name"),
                "planned_qty": prop.get("planned_qty"),
                "unit": prop.get("unit"),
                "working": prop.get("working"),
                "phase": prop.get("phase"),
                "order_index": prop.get("order_index"),
                "clock_time": prop.get("clock_time"),
                "target": "planned_qty",
                "parse_error": p.parse_error or None,
            }
        )
    steps.sort(
        key=lambda s: (
            0 if s.get("phase") == "mep" else 1,
            s.get("order_index") if s.get("order_index") is not None else 999,
            s.get("proposal_id") or 0,
        )
    )
    if not steps:
        return {"service_date": str(service_date), "section": section, "items": []}
    return {"service_date": str(service_date), "section": section, "items": steps}
