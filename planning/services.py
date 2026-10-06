"""
Planning business rules (Phase 1.5 boards + Phase 4 full planner).

Routers orchestrate; models validate; services write domain state.
LLM never writes here.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone

from planning.models import (
    DishTemplate,
    LineComponent,
    LineEvent,
    ProductionLine,
    ServiceDay,
    ServiceOutlet,
    ServiceSection,
    ServiceSectionCode,
    Wave,
    WaveAllocation,
)

BANQUET_SECTIONS = frozenset(
    {
        ServiceSectionCode.BANQUETING,
        ServiceSectionCode.BANQUET_BUFFET,
    }
)


class PlanningError(Exception):
    def __init__(self, message: str, code: str = "planning_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _event(line: ProductionLine, kind: str, **payload: Any) -> LineEvent:
    return LineEvent.objects.create(line=line, kind=kind, payload=payload or {})


def decimal_or_none(v) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _dec_json(v: Decimal | None):
    if v is None:
        return None
    if v == v.to_integral_value():
        return int(v)
    return float(v)


def get_day(service_date: date) -> ServiceDay:
    try:
        return ServiceDay.objects.get(service_date=service_date)
    except ServiceDay.DoesNotExist as exc:
        raise PlanningError(
            f"Service day {service_date} not open", code="day_not_found"
        ) from exc


def assert_day_mutable(day: ServiceDay) -> None:
    if day.status == ServiceDay.Status.CLOSED:
        raise PlanningError(
            f"Service day {day.service_date} is closed — reopen before mutating boards",
            code="day_closed",
        )


def _section_for_day(day: ServiceDay, section: str) -> ServiceSection:
    try:
        return ServiceSection.objects.select_related("service_day").get(
            service_day=day, section=section
        )
    except ServiceSection.DoesNotExist as exc:
        raise PlanningError(
            f"Section {section} not open for {day.service_date}",
            code="section_not_found",
        ) from exc


@transaction.atomic
def open_service_day(
    service_date: date,
    *,
    sections: list[str] | None = None,
    occupancy_rooms: int | None = None,
    occupancy_guests: int | None = None,
    notes: str = "",
    generate_lines: bool = True,
) -> ServiceDay:
    """
    Open (or re-open) a service day. Covers never required.
    Optionally open listed sections (default: any section that has active templates,
    plus a_la_carte always if templates exist).
    """
    day, created = ServiceDay.objects.get_or_create(
        service_date=service_date,
        defaults={
            "status": ServiceDay.Status.OPEN,
            "occupancy_rooms": occupancy_rooms,
            "occupancy_guests": occupancy_guests,
            "notes": notes or "",
            "opened_at": timezone.now(),
            "closed_at": None,
            "outturn": {},
        },
    )
    if not created:
        upd: list[str] = []
        if day.status != ServiceDay.Status.OPEN:
            day.status = ServiceDay.Status.OPEN
            day.opened_at = timezone.now()
            day.closed_at = None
            # Keep prior outturn history nested under last_outturn when reopening
            if day.outturn:
                prior = day.outturn
                day.outturn = {"reopened_from": prior}
            upd += ["status", "opened_at", "closed_at", "outturn"]
        if occupancy_rooms is not None and day.occupancy_rooms != occupancy_rooms:
            day.occupancy_rooms = occupancy_rooms
            upd.append("occupancy_rooms")
        if occupancy_guests is not None and day.occupancy_guests != occupancy_guests:
            day.occupancy_guests = occupancy_guests
            upd.append("occupancy_guests")
        if notes and notes != day.notes:
            day.notes = notes
            upd.append("notes")
        if upd:
            day.save(update_fields=upd)

    if sections is None:
        qs = (
            DishTemplate.objects.filter(active=True)
            .values_list("section", flat=True)
            .distinct()
        )
        section_list = sorted(set(qs))
        if not section_list:
            section_list = [ServiceSectionCode.A_LA_CARTE]
    else:
        section_list = list(sections)

    valid = {c.value for c in ServiceSectionCode}
    for sec in section_list:
        if sec not in valid:
            raise PlanningError(f"Unknown section: {sec}", code="invalid_section")
        open_service_section(day, sec, generate_lines=generate_lines)

    return day


@transaction.atomic
def open_service_section(
    day: ServiceDay,
    section: str,
    *,
    generate_lines: bool = True,
) -> ServiceSection:
    assert_day_mutable(day)
    sec, _ = ServiceSection.objects.get_or_create(
        service_day=day,
        section=section,
        defaults={
            "active": True,
            "covers": None,
            "covers_source": "",
            "beo_events": [],
            "outturn": {},
        },
    )
    if not sec.active:
        sec.active = True
        sec.save(update_fields=["active"])
    if generate_lines:
        generate_lines_from_templates(sec)
    return sec


@transaction.atomic
def generate_lines_from_templates(service_section: ServiceSection) -> int:
    """
    Idempotent: create ProductionLine + components from active DishTemplates
    for this section. Existing template-sourced lines are left alone (no dupes).
    Resolves Item by template.item, else case-insensitive name match (house_made).
    """
    from catalog.models import Item

    existing_template_ids = set(
        ProductionLine.objects.filter(
            service_section=service_section,
            template_id__isnull=False,
        ).values_list("template_id", flat=True)
    )
    templates = (
        DishTemplate.objects.filter(
            section=service_section.section,
            active=True,
        )
        .select_related("item")
        .prefetch_related("components", "components__item", "components__supplier_item")
        .order_by("sort_order", "name")
    )
    created = 0
    for tmpl in templates:
        if tmpl.pk in existing_template_ids:
            # Backfill missing item FK on existing template lines (D12 house_made FE).
            line = (
                ProductionLine.objects.filter(
                    service_section=service_section,
                    template_id=tmpl.pk,
                    item_id__isnull=True,
                )
                .order_by("id")
                .first()
            )
            if line is not None:
                resolved = tmpl.item
                if resolved is None:
                    resolved = Item.objects.filter(name__iexact=(tmpl.name or "").strip()).first()
                if resolved is not None:
                    line.item = resolved
                    line.save(update_fields=["item", "updated_at"])
            continue
        resolved_item = tmpl.item
        if resolved_item is None:
            resolved_item = Item.objects.filter(name__iexact=(tmpl.name or "").strip()).first()
        line = ProductionLine.objects.create(
            service_section=service_section,
            item=resolved_item,
            name=tmpl.name,
            mode=tmpl.mode,
            kind=tmpl.kind,
            category=tmpl.category or service_section.section,
            unit=tmpl.unit or "ea",
            proposed_qty=None,
            planned_qty=None,
            actual_qty=None,  # check: always null
            par_level=tmpl.par_level,
            status=ProductionLine.Status.PLANNED,
            supports_lounge=tmpl.supports_lounge,
            source=ProductionLine.Source.TEMPLATE,
            # Day-tier notes start empty; template notes joined in board payload
            notes="",
            sort_order=tmpl.sort_order,
            template=tmpl,
        )
        comps = []
        for c in tmpl.components.all():
            comps.append(
                LineComponent(
                    line=line,
                    item=c.item,
                    supplier_item=c.supplier_item,
                    name=c.name or (c.item.name if c.item_id else ""),
                    planned_qty=c.planned_qty,
                    unit=c.unit or (c.item.base_unit if c.item_id else "ea"),
                    done=False,
                    sort_order=c.sort_order,
                )
            )
        if comps:
            LineComponent.objects.bulk_create(comps)
        _event(
            line,
            "generated",
            source="template",
            template_id=tmpl.pk,
            mode=line.mode,
        )
        created += 1
    return created


def board_queryset(service_date: date, section: str):
    """One-request board: day + section + lines + components + events (prefetched)."""
    try:
        day = ServiceDay.objects.get(service_date=service_date)
    except ServiceDay.DoesNotExist as exc:
        raise PlanningError(
            f"Service day {service_date} not open", code="day_not_found"
        ) from exc
    try:
        sec = (
            ServiceSection.objects.select_related("service_day")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=ProductionLine.objects.select_related("item", "template")
                    .prefetch_related(
                        Prefetch(
                            "components",
                            queryset=LineComponent.objects.select_related(
                                "item", "supplier_item"
                            ).order_by("sort_order", "id"),
                        ),
                        Prefetch(
                            "events",
                            queryset=LineEvent.objects.order_by("-created_at", "-id"),
                        ),
                        Prefetch(
                            "wave_allocations",
                            queryset=WaveAllocation.objects.select_related("wave").order_by(
                                "wave__sort_order", "wave_id"
                            ),
                        ),
                    )
                    .order_by("sort_order", "id"),
                ),
                Prefetch(
                    "waves",
                    queryset=Wave.objects.order_by("sort_order", "id"),
                ),
                Prefetch(
                    "outlets",
                    queryset=ServiceOutlet.objects.order_by("outlet"),
                ),
            )
            .get(service_day=day, section=section)
        )
    except ServiceSection.DoesNotExist as exc:
        raise PlanningError(
            f"Section {section} not open for {service_date}",
            code="section_not_found",
        ) from exc
    return day, sec


@transaction.atomic
def tick_line(line_id: int, *, ticked: bool = True, status: str | None = None) -> ProductionLine:
    try:
        line = (
            ProductionLine.objects.select_for_update()
            .select_related("service_section__service_day")
            .get(pk=line_id)
        )
    except ProductionLine.DoesNotExist as exc:
        raise PlanningError("Line not found", code="line_not_found") from exc

    assert_day_mutable(line.service_section.service_day)

    old = line.status
    if status:
        if status not in {c.value for c in ProductionLine.Status}:
            raise PlanningError(f"Invalid status {status}", code="invalid_status")
        line.status = status
    elif ticked:
        line.status = ProductionLine.Status.READY
    else:
        line.status = ProductionLine.Status.PLANNED

    # check mode: never set actual_qty
    if line.mode == ProductionLine.Mode.CHECK:
        line.actual_qty = None

    line.save(update_fields=["status", "actual_qty", "updated_at"])
    _event(
        line,
        "tick" if ticked or status == ProductionLine.Status.READY else "untick",
        from_status=old,
        to_status=line.status,
        mode=line.mode,
    )
    return line


@transaction.atomic
def tick_component(component_id: int, *, done: bool = True) -> LineComponent:
    try:
        comp = (
            LineComponent.objects.select_for_update()
            .select_related("line__service_section__service_day")
            .get(pk=component_id)
        )
    except LineComponent.DoesNotExist as exc:
        raise PlanningError("Component not found", code="component_not_found") from exc

    assert_day_mutable(comp.line.service_section.service_day)

    old = comp.done
    comp.done = done
    comp.save(update_fields=["done"])
    _event(
        comp.line,
        "component_tick" if done else "component_untick",
        component_id=comp.pk,
        from_done=old,
        to_done=done,
    )
    return comp


@transaction.atomic
def quick_add_line(
    service_date: date,
    section: str,
    name: str,
    *,
    mode: str = ProductionLine.Mode.CHECK,
    kind: str = ProductionLine.Kind.DISH,
    notes: str = "",
) -> ProductionLine:
    name = (name or "").strip()
    if not name:
        raise PlanningError("name required for quick-add", code="name_required")
    if mode not in {c.value for c in ProductionLine.Mode}:
        raise PlanningError(f"Invalid mode {mode}", code="invalid_mode")

    day = get_day(service_date)
    assert_day_mutable(day)

    sec, _ = ServiceSection.objects.get_or_create(
        service_day=day,
        section=section,
        defaults={"active": True, "covers": None},
    )

    max_sort = (
        ProductionLine.objects.filter(service_section=sec)
        .order_by("-sort_order")
        .values_list("sort_order", flat=True)
        .first()
    )
    sort_order = (max_sort or 0) + 10

    line = ProductionLine(
        service_section=sec,
        item=None,  # name only — no item FK required
        name=name,
        mode=mode,
        kind=kind,
        category=section,
        unit="ea",
        proposed_qty=None,
        planned_qty=None,
        actual_qty=None if mode == ProductionLine.Mode.CHECK else None,
        par_level=None,
        status=ProductionLine.Status.PLANNED,
        supports_lounge=False,
        source=ProductionLine.Source.MANUAL,
        notes=notes or "",
        sort_order=sort_order,
        template=None,
    )
    line.full_clean()
    line.save()
    _event(line, "quick_add", name=name, mode=mode, source="manual")
    return line


NOTE_MAX_LENGTH = 500


@transaction.atomic
def set_line_note(line_id: int, notes: str | None) -> ProductionLine:
    """
    D12/D14: set or clear ProductionLine.notes (day tier).
    None or blank string clears. Max 500 chars.
    Auto-enqueues parse_note when text long enough; assist never blocks/fails the save.
    """
    try:
        line = (
            ProductionLine.objects.select_for_update()
            .select_related("service_section__service_day")
            .get(pk=line_id)
        )
    except ProductionLine.DoesNotExist as exc:
        raise PlanningError("Line not found", code="line_not_found") from exc

    assert_day_mutable(line.service_section.service_day)

    if notes is None:
        cleaned = ""
    else:
        cleaned = notes.strip() if isinstance(notes, str) else str(notes)
        if len(cleaned) > NOTE_MAX_LENGTH:
            raise PlanningError(
                f"notes max_length is {NOTE_MAX_LENGTH}",
                code="notes_too_long",
            )

    old = line.notes or ""
    line.notes = cleaned
    line.save(update_fields=["notes", "updated_at"])
    _event(
        line,
        "note_clear" if not cleaned else "note_set",
        from_notes=old,
        to_notes=cleaned,
    )
    if cleaned:
        try:
            from assist.services import maybe_auto_enqueue_parse_note_for_line

            # refresh item/template without FOR UPDATE join
            line = ProductionLine.objects.select_related("item", "template").get(pk=line.pk)
            maybe_auto_enqueue_parse_note_for_line(line, text=cleaned)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "auto parse_note enqueue failed line=%s", line_id
            )
    return line


# ----- Phase 4: covers / waves / allocations / qty / close -----


@transaction.atomic
def set_section_covers(
    service_date: date,
    section: str,
    *,
    covers: int | None,
    covers_source: str = "",
    beo_events: list[dict] | None = None,
    notes: str | None = None,
) -> ServiceSection:
    """
    Set per-section covers. Banquet BEO path: source=beo + optional event breakdown.
    Covers never required on non-banquet; BEO covers entry is for banquet* only.
    """
    day = get_day(service_date)
    assert_day_mutable(day)
    sec = _section_for_day(day, section)

    source = (covers_source or "").strip()
    valid_sources = {c.value for c in ServiceSection.CoversSource} | {""}
    if source not in valid_sources:
        raise PlanningError(
            f"Invalid covers_source {source!r}", code="invalid_covers_source"
        )

    if source == ServiceSection.CoversSource.BEO and section not in BANQUET_SECTIONS:
        raise PlanningError(
            "covers_source=beo only allowed on banqueting / banquet_buffet",
            code="beo_section_only",
        )

    events_clean: list[dict] = []
    if beo_events is not None:
        if section not in BANQUET_SECTIONS:
            raise PlanningError(
                "beo_events only allowed on banqueting / banquet_buffet",
                code="beo_section_only",
            )
        total = 0
        for ev in beo_events:
            if not isinstance(ev, dict):
                raise PlanningError("beo_events entries must be objects", code="invalid_beo")
            name = str(ev.get("name") or "").strip() or "event"
            try:
                c = int(ev["covers"]) if ev.get("covers") is not None else None
            except (TypeError, ValueError) as exc:
                raise PlanningError(
                    "beo event covers must be int", code="invalid_beo"
                ) from exc
            if c is None or c < 0:
                raise PlanningError(
                    "beo event covers must be >= 0", code="invalid_beo"
                )
            events_clean.append({"name": name, "covers": c})
            total += c
        # Sum events onto section when covers omitted
        if covers is None:
            covers = total
        elif covers != total:
            raise PlanningError(
                f"covers ({covers}) must equal sum of beo_events ({total})",
                code="beo_covers_mismatch",
            )
        if source == "":
            source = ServiceSection.CoversSource.BEO

    if covers is not None and covers < 0:
        raise PlanningError("covers must be >= 0 or null", code="invalid_covers")

    sec.covers = covers
    sec.covers_source = source
    if beo_events is not None:
        sec.beo_events = events_clean
    if notes is not None:
        sec.notes = notes
    sec.save()
    # D15.1: guided prep plan working strings track covers
    try:
        from planning.d15_depth import refresh_prep_plan_after_covers

        refresh_prep_plan_after_covers(service_date, section)
    except Exception:  # noqa: BLE001
        pass
    return sec


@transaction.atomic
def upsert_wave(
    service_date: date,
    section: str,
    *,
    name: str,
    wave_id: int | None = None,
    serve_at: time | None = None,
    covers: int | None = None,
    sort_order: int | None = None,
) -> Wave:
    """Create or update a wave on a banquet section (allowed on banquet* only)."""
    day = get_day(service_date)
    assert_day_mutable(day)
    if section not in BANQUET_SECTIONS:
        raise PlanningError(
            "Waves only allowed on banqueting / banquet_buffet",
            code="wave_section_only",
        )
    sec = _section_for_day(day, section)
    name = (name or "").strip()
    if not name:
        raise PlanningError("wave name required", code="name_required")
    if covers is not None and covers < 0:
        raise PlanningError("wave covers must be >= 0 or null", code="invalid_covers")

    if wave_id is not None:
        try:
            wave = Wave.objects.select_for_update().get(pk=wave_id, service_section=sec)
        except Wave.DoesNotExist as exc:
            raise PlanningError("Wave not found", code="wave_not_found") from exc
        wave.name = name
        wave.serve_at = serve_at
        wave.covers = covers
        if sort_order is not None:
            wave.sort_order = sort_order
        try:
            wave.save()
        except IntegrityError as exc:
            raise PlanningError(
                f"Wave name already exists on section: {name}",
                code="wave_name_conflict",
            ) from exc
        return wave

    max_sort = (
        Wave.objects.filter(service_section=sec)
        .order_by("-sort_order")
        .values_list("sort_order", flat=True)
        .first()
    )
    so = sort_order if sort_order is not None else (max_sort or 0) + 10
    try:
        wave = Wave.objects.create(
            service_section=sec,
            name=name,
            serve_at=serve_at,
            covers=covers,
            sort_order=so,
        )
    except IntegrityError as exc:
        raise PlanningError(
            f"Wave name already exists on section: {name}",
            code="wave_name_conflict",
        ) from exc
    return wave


@transaction.atomic
def delete_wave(wave_id: int) -> None:
    try:
        wave = (
            Wave.objects.select_for_update()
            .select_related("service_section__service_day")
            .get(pk=wave_id)
        )
    except Wave.DoesNotExist as exc:
        raise PlanningError("Wave not found", code="wave_not_found") from exc
    assert_day_mutable(wave.service_section.service_day)
    wave.delete()


@transaction.atomic
def set_wave_allocations(
    line_id: int,
    allocations: list[dict],
) -> list[WaveAllocation]:
    """
    Replace wave allocations for one produce line.
    One line across waves — never duplicate the line. unique(line, wave) enforced.
    """
    try:
        line = (
            ProductionLine.objects.select_for_update()
            .select_related("service_section__service_day")
            .get(pk=line_id)
        )
    except ProductionLine.DoesNotExist as exc:
        raise PlanningError("Line not found", code="line_not_found") from exc

    assert_day_mutable(line.service_section.service_day)
    sec = line.service_section
    if sec.section not in BANQUET_SECTIONS:
        raise PlanningError(
            "Wave allocations only on banqueting / banquet_buffet lines",
            code="wave_section_only",
        )

    seen_waves: set[int] = set()
    cleaned: list[tuple[Wave, Decimal | None]] = []
    for row in allocations:
        if not isinstance(row, dict):
            raise PlanningError("allocation rows must be objects", code="invalid_allocation")
        wid = row.get("wave_id")
        if wid is None:
            raise PlanningError("wave_id required", code="invalid_allocation")
        try:
            wid = int(wid)
        except (TypeError, ValueError) as exc:
            raise PlanningError("wave_id must be int", code="invalid_allocation") from exc
        if wid in seen_waves:
            raise PlanningError(
                f"duplicate wave_id {wid} in payload", code="duplicate_wave_allocation"
            )
        seen_waves.add(wid)
        try:
            wave = Wave.objects.get(pk=wid, service_section=sec)
        except Wave.DoesNotExist as exc:
            raise PlanningError(
                f"Wave {wid} not on this section", code="wave_not_found"
            ) from exc
        qty = decimal_or_none(row.get("qty"))
        cleaned.append((wave, qty))

    WaveAllocation.objects.filter(line=line).delete()
    out: list[WaveAllocation] = []
    for wave, qty in cleaned:
        try:
            alloc = WaveAllocation.objects.create(line=line, wave=wave, qty=qty)
        except IntegrityError as exc:
            raise PlanningError(
                "unique(line, wave) violated", code="allocation_conflict"
            ) from exc
        out.append(alloc)

    _event(
        line,
        "wave_allocations_set",
        allocations=[
            {"wave_id": a.wave_id, "qty": _dec_json(a.qty)} for a in out
        ],
    )
    return out


@transaction.atomic
def set_line_quantities(
    line_id: int,
    *,
    proposed_qty=None,
    planned_qty=None,
    actual_qty=None,
    set_proposed: bool = False,
    set_planned: bool = False,
    set_actual: bool = False,
) -> ProductionLine:
    """
    Set produce/replenish quantities. check mode: actual_qty always forced null.
    Canteen produce qty is entered here (not covers-derived).
    """
    try:
        line = (
            ProductionLine.objects.select_for_update()
            .select_related("service_section__service_day")
            .get(pk=line_id)
        )
    except ProductionLine.DoesNotExist as exc:
        raise PlanningError("Line not found", code="line_not_found") from exc

    assert_day_mutable(line.service_section.service_day)

    old = {
        "proposed_qty": _dec_json(line.proposed_qty),
        "planned_qty": _dec_json(line.planned_qty),
        "actual_qty": _dec_json(line.actual_qty),
    }
    fields = ["updated_at"]

    if set_proposed:
        line.proposed_qty = decimal_or_none(proposed_qty)
        fields.append("proposed_qty")
    if set_planned:
        line.planned_qty = decimal_or_none(planned_qty)
        fields.append("planned_qty")
    if set_actual:
        if line.mode == ProductionLine.Mode.CHECK:
            if decimal_or_none(actual_qty) is not None:
                raise PlanningError(
                    "check lines must keep actual_qty null",
                    code="check_actual_forbidden",
                )
            line.actual_qty = None
        else:
            line.actual_qty = decimal_or_none(actual_qty)
        fields.append("actual_qty")
    elif line.mode == ProductionLine.Mode.CHECK:
        line.actual_qty = None
        if "actual_qty" not in fields:
            fields.append("actual_qty")

    line.save(update_fields=fields)
    _event(
        line,
        "qty_set",
        from_qty=old,
        to_qty={
            "proposed_qty": _dec_json(line.proposed_qty),
            "planned_qty": _dec_json(line.planned_qty),
            "actual_qty": _dec_json(line.actual_qty),
        },
        mode=line.mode,
    )
    return line


def _scaling_covers(sec: ServiceSection) -> int | None:
    """
    Covers used for produce proposed_qty scaling on banquet*.
    Prefer sum of wave.covers when any wave has covers; else section.covers.
    """
    waves = list(sec.waves.all()) if hasattr(sec, "waves") else list(
        Wave.objects.filter(service_section=sec)
    )
    wave_covers = [w.covers for w in waves if w.covers is not None]
    if wave_covers:
        return sum(wave_covers)
    return sec.covers


@transaction.atomic
def scale_produce_proposed(service_date: date, section: str) -> dict:
    """
    Banquet produce scaling:
      proposed_qty = scaling_covers * template.yield_per_cover
    when yield_per_cover is set; otherwise proposed stays null (human enters planned).
    Never invent catalogue yields.
    Formula documented in OpenAPI + gate report.
    """
    day = get_day(service_date)
    assert_day_mutable(day)
    if section not in BANQUET_SECTIONS:
        raise PlanningError(
            "scale-produce only for banqueting / banquet_buffet",
            code="scale_section_only",
        )
    sec = _section_for_day(day, section)
    covers = _scaling_covers(sec)
    locked_ids = list(
        ProductionLine.objects.select_for_update()
        .filter(service_section=sec, mode=ProductionLine.Mode.PRODUCE)
        .values_list("pk", flat=True)
    )
    lines = list(
        ProductionLine.objects.filter(pk__in=locked_ids).select_related("template")
    )
    updated = []
    skipped = []
    for line in lines:
        ypc = None
        if line.template_id and line.template and line.template.yield_per_cover is not None:
            ypc = line.template.yield_per_cover
        if covers is None or ypc is None:
            # leave proposed as-is (typically null) — documented null path
            skipped.append(
                {
                    "line_id": line.pk,
                    "name": line.name,
                    "reason": "missing_covers" if covers is None else "no_yield_per_cover",
                    "proposed_qty": _dec_json(line.proposed_qty),
                }
            )
            continue
        new_q = (Decimal(covers) * ypc).quantize(Decimal("0.000001"))
        old = line.proposed_qty
        line.proposed_qty = new_q
        line.save(update_fields=["proposed_qty", "updated_at"])
        _event(
            line,
            "scale_proposed",
            covers=covers,
            yield_per_cover=_dec_json(ypc),
            from_proposed=_dec_json(old),
            to_proposed=_dec_json(new_q),
            formula="proposed_qty = scaling_covers * template.yield_per_cover",
            scaling_covers_source="sum(wave.covers) if any else section.covers",
        )
        updated.append(
            {
                "line_id": line.pk,
                "name": line.name,
                "proposed_qty": _dec_json(new_q),
                "yield_per_cover": _dec_json(ypc),
            }
        )
    return {
        "section": section,
        "service_date": str(service_date),
        "scaling_covers": covers,
        "formula": "proposed_qty = scaling_covers * template.yield_per_cover",
        "scaling_covers_source": "sum(wave.covers) if any wave.covers set else section.covers",
        "updated": updated,
        "skipped_null_path": skipped,
    }


@transaction.atomic
def upsert_service_outlet(
    service_date: date,
    section: str,
    *,
    outlet: str,
    active: bool = True,
    covers: int | None = None,
) -> ServiceOutlet:
    """ALC lounge is an outlet of a_la_carte, not a peer section."""
    day = get_day(service_date)
    assert_day_mutable(day)
    if section != ServiceSectionCode.A_LA_CARTE:
        raise PlanningError(
            "ServiceOutlet v1 only on a_la_carte (executive_lounge)",
            code="outlet_section_only",
        )
    if outlet not in {c.value for c in ServiceOutlet.Outlet}:
        raise PlanningError(f"Unknown outlet {outlet}", code="invalid_outlet")
    sec = _section_for_day(day, section)
    obj, _ = ServiceOutlet.objects.update_or_create(
        service_section=sec,
        outlet=outlet,
        defaults={"active": active, "covers": covers},
    )
    return obj


@transaction.atomic
def close_service_day(
    service_date: date,
    *,
    notes: str | None = None,
    section_outturns: dict | None = None,
) -> ServiceDay:
    """
    Close day + capture outturn from line actuals (and optional section overrides).
    Covers never required on non-banquet sections.
    """
    day = get_day(service_date)
    if day.status == ServiceDay.Status.CLOSED:
        raise PlanningError(
            f"Service day {service_date} already closed", code="day_already_closed"
        )

    sections = list(
        ServiceSection.objects.filter(service_day=day).prefetch_related(
            Prefetch(
                "lines",
                queryset=ProductionLine.objects.order_by("sort_order", "id"),
            )
        )
    )
    section_payload: list[dict] = []
    for sec in sections:
        lines_out = []
        for ln in sec.lines.all():
            lines_out.append(
                {
                    "line_id": ln.pk,
                    "name": ln.name,
                    "mode": ln.mode,
                    "status": ln.status,
                    "proposed_qty": _dec_json(ln.proposed_qty),
                    "planned_qty": _dec_json(ln.planned_qty),
                    "actual_qty": _dec_json(ln.actual_qty),
                    "ticked": ln.ticked,
                }
            )
        override = {}
        if section_outturns and sec.section in section_outturns:
            override = section_outturns[sec.section] or {}
            if not isinstance(override, dict):
                raise PlanningError(
                    "section_outturns values must be objects",
                    code="invalid_outturn",
                )
            sec.outturn = {
                **(sec.outturn or {}),
                **override,
                "captured_at": timezone.now().isoformat(),
            }
            sec.save(update_fields=["outturn"])
        else:
            sec.outturn = {
                "line_count": len(lines_out),
                "ticked_count": sum(1 for x in lines_out if x["ticked"]),
                "captured_at": timezone.now().isoformat(),
            }
            sec.save(update_fields=["outturn"])

        section_payload.append(
            {
                "section": sec.section,
                "covers": sec.covers,
                "covers_source": sec.covers_source or "",
                "outturn": sec.outturn,
                "lines": lines_out,
            }
        )

    outturn = {
        "closed_at": timezone.now().isoformat(),
        "service_date": str(service_date),
        "sections": section_payload,
    }
    day.status = ServiceDay.Status.CLOSED
    day.closed_at = timezone.now()
    day.outturn = outturn
    upd = ["status", "closed_at", "outturn"]
    if notes is not None:
        day.notes = notes
        upd.append("notes")
    day.save(update_fields=upd)
    return day
