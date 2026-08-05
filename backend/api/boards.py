"""
Phase 1.5 + Phase 4 MEP/service board endpoints under /api/v1/boards/...

Contract:
  POST /api/v1/boards/days/open
  GET  /api/v1/boards/days/{service_date}
  POST /api/v1/boards/days/{service_date}/close
  GET  /api/v1/boards/days/{service_date}/sections/{section}   # ONE request board
  POST /api/v1/boards/days/{service_date}/sections/{section}/open
  PATCH /api/v1/boards/days/{service_date}/sections/{section}/covers
  POST /api/v1/boards/days/{service_date}/sections/{section}/waves
  GET  /api/v1/boards/days/{service_date}/sections/{section}/waves
  PATCH /api/v1/boards/waves/{wave_id}
  DELETE /api/v1/boards/waves/{wave_id}
  PUT  /api/v1/boards/lines/{line_id}/wave-allocations
  PATCH /api/v1/boards/lines/{line_id}/qty
  POST /api/v1/boards/days/{service_date}/sections/{section}/scale-produce
  PUT  /api/v1/boards/days/{service_date}/sections/{section}/outlets
  POST /api/v1/boards/lines/{line_id}/tick
  POST /api/v1/boards/lines/{line_id}/untick
  POST /api/v1/boards/components/{component_id}/tick
  POST /api/v1/boards/components/{component_id}/untick
  POST /api/v1/boards/lines/quick-add
  PATCH /api/v1/boards/lines/{line_id}/notes

Auth: Bearer. Covers never required to open day/section (Phase 4 lock).
Banquet produce scale formula:
  proposed_qty = scaling_covers * template.yield_per_cover
  scaling_covers = sum(wave.covers) if any wave covers set else section.covers
  If yield_per_cover missing → proposed stays null (human enters planned_qty).
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from api.auth import BearerAuth
from api.types import DecimalQty
from planning import services as planning_services
from planning.models import LineComponent, ProductionLine, ServiceDay, ServiceSection, Wave
from planning.services import PlanningError

router = Router(tags=["boards"], auth=BearerAuth())


# ----- schemas (Decimal end-to-end as JSON numbers — B1; blank → null, never 0) -----


class OpenDayIn(Schema):
    service_date: date
    sections: list[str] | None = None
    occupancy_rooms: int | None = None
    occupancy_guests: int | None = None
    notes: str = ""
    generate_lines: bool = True


class OpenSectionIn(Schema):
    generate_lines: bool = True


class QuickAddIn(Schema):
    service_date: date
    section: str
    name: str
    mode: str = "check"
    kind: str = "dish"
    notes: str = ""


class TickIn(Schema):
    """Optional explicit status override (ready|eighty_six|planned|…)."""

    status: str | None = None


class NoteIn(Schema):
    """D12: null or empty string clears the line note (max 500)."""

    notes: str | None = None


class BeoEventIn(Schema):
    name: str = "event"
    covers: int


class SectionCoversIn(Schema):
    """
    Per-section covers only — no global dial.
    Banquet BEO: covers_source=beo + optional events (sum must match covers if both set).
    Non-banquet: optional informational; never required to open boards.
    """

    covers: int | None = None
    covers_source: str = ""
    beo_events: list[BeoEventIn] | None = None
    notes: str | None = None


class WaveIn(Schema):
    name: str
    serve_at: time | None = None
    covers: int | None = None
    sort_order: int | None = None


class WavePatchIn(Schema):
    name: str | None = None
    serve_at: time | None = None
    covers: int | None = None
    sort_order: int | None = None


class WaveAllocationIn(Schema):
    wave_id: int
    qty: DecimalQty = None


class WaveAllocationsPutIn(Schema):
    """Replace all allocations for one line (unique line+wave)."""

    allocations: list[WaveAllocationIn]


class LineQtyIn(Schema):
    """
    Set planned/actual/proposed on a line.
    check mode: actual_qty must stay null.
    Canteen produce: enter planned/actual here — not covers-derived.
    """

    proposed_qty: DecimalQty = None
    planned_qty: DecimalQty = None
    actual_qty: DecimalQty = None
    # Which fields to write (omit key = leave unchanged). Explicit null clears.
    set_proposed: bool = False
    set_planned: bool = False
    set_actual: bool = False


class CloseDayIn(Schema):
    notes: str | None = None
    # optional per-section outturn overrides: { "canteen": {"covers_actual": 40}, ... }
    section_outturns: dict[str, dict[str, Any]] | None = None


class OutletIn(Schema):
    outlet: str = "executive_lounge"
    active: bool = True
    covers: int | None = None


class LineComponentOut(Schema):
    id: int
    item_id: int | None = None
    item_name: str | None = None
    item_house_made: bool | None = None
    item_notes: str | None = None
    supplier_item_id: int | None = None
    name: str
    planned_qty: DecimalQty = None
    unit: str
    done: bool
    sort_order: int
    # D15 ordering-mode stock dots
    stock_status: str | None = None
    stock_status_text: str | None = None
    stock_qty: float | None = None
    on_order_qty: float | None = None
    supplier_code: str | None = None
    par_qty: float | None = None


class LineEventOut(Schema):
    id: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class WaveAllocationOut(Schema):
    id: int
    wave_id: int
    wave_name: str
    qty: DecimalQty = None


class ProductionLineOut(Schema):
    id: int
    name: str
    mode: str
    kind: str
    category: str
    unit: str
    item_id: int | None = None
    item_name: str | None = None
    item_notes: str | None = None
    item_house_made: bool | None = None
    proposed_qty: DecimalQty = None
    planned_qty: DecimalQty = None
    actual_qty: DecimalQty = None
    par_level: DecimalQty = None
    status: str
    ticked: bool
    supports_lounge: bool
    source: str
    notes: str
    template_notes: str = ""
    sort_order: int
    template_id: int | None = None
    yield_per_cover: DecimalQty = None
    pending_proposal: dict | None = None
    components: list[LineComponentOut]
    events: list[LineEventOut]
    wave_allocations: list[WaveAllocationOut] = []
    # D15 ordering-mode dish summary (omit/null in counts mode)
    ingredient_count: int | None = None
    to_order_count: int | None = None
    order_summary_label: str | None = None


class WaveOut(Schema):
    id: int
    name: str
    serve_at: time | None = None
    covers: int | None = None
    sort_order: int


class OutletOut(Schema):
    id: int
    outlet: str
    active: bool
    covers: int | None = None


class ServiceSectionOut(Schema):
    id: int
    section: str
    active: bool
    covers: int | None = None
    covers_source: str
    notes: str
    line_count: int = 0
    beo_events: list[dict[str, Any]] = []
    outturn: dict[str, Any] = {}


class ServiceDayOut(Schema):
    id: int
    service_date: date
    status: str
    occupancy_rooms: int | None = None
    occupancy_guests: int | None = None
    notes: str
    opened_at: datetime
    closed_at: datetime | None = None
    outturn: dict[str, Any] = {}
    sections: list[ServiceSectionOut]


class BoardOut(Schema):
    """One-request board payload for a single section (Phase 4 + D15 modes)."""

    service_date: date
    day_status: str
    occupancy_rooms: int | None = None
    occupancy_guests: int | None = None
    section: str
    section_id: int
    active: bool
    covers: int | None = None
    covers_source: str
    notes: str
    beo_events: list[dict[str, Any]] = []
    outturn: dict[str, Any] = {}
    waves: list[WaveOut] = []
    outlets: list[OutletOut] = []
    lines: list[ProductionLineOut]
    line_count: int
    ticked_count: int
    # D15 section modes — FE needs no extra round-trip
    section_mode: str | None = None
    mode_prompt_needed: bool = True
    guided: bool = False
    mode_recommendation: str | None = None
    prep_plan: dict[str, Any] | None = None
    order_assist: dict[str, Any] | None = None


class LineOut(Schema):
    line: ProductionLineOut


class ComponentTickOut(Schema):
    id: int
    line_id: int
    done: bool
    name: str


class ScaleProduceOut(Schema):
    section: str
    service_date: str
    scaling_covers: int | None = None
    formula: str
    scaling_covers_source: str
    updated: list[dict[str, Any]]
    skipped_null_path: list[dict[str, Any]]


class WaveAllocationsOut(Schema):
    line_id: int
    allocations: list[WaveAllocationOut]


class ErrorOut(Schema):
    detail: str
    code: str


def _http_planning(exc: PlanningError) -> HttpError:
    if exc.code.endswith("not_found"):
        status = 404
    elif exc.code == "day_closed":
        status = 409
    else:
        status = 400
    return HttpError(status, f"{exc.code}: {exc.message}")


def _component_out(c: LineComponent, *, ordering_mode: bool = False) -> dict:
    item = c.item if c.item_id else None
    base = {
        "id": c.pk,
        "item_id": c.item_id,
        "item_name": item.name if item is not None else None,
        "item_house_made": bool(item.house_made) if item is not None else None,
        "item_notes": (item.notes or "") if item is not None else None,
        "supplier_item_id": c.supplier_item_id,
        "name": c.name or (item.name if item is not None else ""),
        "planned_qty": c.planned_qty,
        "unit": c.unit,
        "done": c.done,
        "sort_order": c.sort_order,
    }
    if ordering_mode:
        try:
            from planning.ordering_assist import enrich_component_dict

            return enrich_component_dict(base, ordering_mode=True)
        except Exception:  # noqa: BLE001
            return base
    return base


def _alloc_out(a) -> dict:
    return {
        "id": a.pk,
        "wave_id": a.wave_id,
        "wave_name": a.wave.name if a.wave_id and getattr(a, "wave", None) else "",
        "qty": a.qty,
    }


def _line_out(
    line: ProductionLine,
    *,
    events_limit: int = 20,
    pending_map: dict | None = None,
    ordering_mode: bool = False,
) -> dict:
    events = list(line.events.all()[:events_limit])
    item = line.item if line.item_id else None
    tmpl = line.template if line.template_id else None
    allocs = []
    if hasattr(line, "wave_allocations"):
        allocs = [_alloc_out(a) for a in line.wave_allocations.all()]
    pending = None
    if pending_map is not None:
        pending = pending_map.get(line.pk)
    comps = [
        _component_out(c, ordering_mode=ordering_mode) for c in line.components.all()
    ]
    out = {
        "id": line.pk,
        "name": line.name,
        "mode": line.mode,
        "kind": line.kind,
        "category": line.category,
        "unit": line.unit,
        "item_id": line.item_id,
        "item_name": item.name if item is not None else None,
        "item_notes": (item.notes or "") if item is not None else None,
        "item_house_made": bool(item.house_made) if item is not None else None,
        "proposed_qty": line.proposed_qty,
        "planned_qty": line.planned_qty,
        "actual_qty": line.actual_qty,
        "par_level": line.par_level,
        "status": line.status,
        "ticked": line.ticked,
        "supports_lounge": line.supports_lounge,
        "source": line.source,
        "notes": line.notes or "",
        # Template tier — joined every day from DishTemplate.notes (D14)
        "template_notes": (tmpl.notes or "") if tmpl is not None else "",
        "template_id": line.template_id,
        "sort_order": line.sort_order,
        "yield_per_cover": tmpl.yield_per_cover if tmpl is not None else None,
        "pending_proposal": pending,
        "components": comps,
        "events": [
            {
                "id": e.pk,
                "kind": e.kind,
                "payload": e.payload or {},
                "created_at": e.created_at,
            }
            for e in events
        ],
        "wave_allocations": allocs,
    }
    if ordering_mode:
        try:
            from planning.ordering_assist import dish_order_summary

            summary = dish_order_summary(comps)
            out["ingredient_count"] = summary["ingredient_count"]
            out["to_order_count"] = summary["to_order_count"]
            out["order_summary_label"] = summary["label"]
        except Exception:  # noqa: BLE001
            out["ingredient_count"] = len(comps)
            out["to_order_count"] = 0
            out["order_summary_label"] = f"{len(comps)} items"
    return out


def _wave_out(w: Wave) -> dict:
    return {
        "id": w.pk,
        "name": w.name,
        "serve_at": w.serve_at,
        "covers": w.covers,
        "sort_order": w.sort_order,
    }


def _day_out(day: ServiceDay) -> dict:
    sections = list(day.sections.all())
    return {
        "id": day.pk,
        "service_date": day.service_date,
        "status": day.status,
        "occupancy_rooms": day.occupancy_rooms,
        "occupancy_guests": day.occupancy_guests,
        "notes": day.notes,
        "opened_at": day.opened_at,
        "closed_at": day.closed_at,
        "outturn": day.outturn or {},
        "sections": [
            {
                "id": s.pk,
                "section": s.section,
                "active": s.active,
                "covers": s.covers,
                "covers_source": s.covers_source or "",
                "notes": s.notes,
                "line_count": s.lines.count() if hasattr(s, "lines") else 0,
                "beo_events": s.beo_events or [],
                "outturn": s.outturn or {},
            }
            for s in sections
        ],
    }


def _reload_line(line_id: int) -> ProductionLine:
    return (
        ProductionLine.objects.select_related("item", "template")
        .prefetch_related(
            "components",
            "components__item",
            "events",
            "wave_allocations",
            "wave_allocations__wave",
        )
        .get(pk=line_id)
    )


@router.post(
    "/days/open",
    response={200: ServiceDayOut, 400: ErrorOut, 401: ErrorOut},
    summary="Open a service day (covers never required); generate lines from templates",
)
def open_day(request: HttpRequest, body: OpenDayIn):
    try:
        day = planning_services.open_service_day(
            body.service_date,
            sections=body.sections,
            occupancy_rooms=body.occupancy_rooms,
            occupancy_guests=body.occupancy_guests,
            notes=body.notes or "",
            generate_lines=body.generate_lines,
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    day = (
        ServiceDay.objects.prefetch_related("sections", "sections__lines")
        .get(pk=day.pk)
    )
    return _day_out(day)


@router.get(
    "/days/{service_date}",
    response={200: ServiceDayOut, 404: ErrorOut},
    summary="Fetch service day + section list (+ outturn if closed)",
)
def get_day(request: HttpRequest, service_date: date):
    try:
        day = ServiceDay.objects.prefetch_related("sections", "sections__lines").get(
            service_date=service_date
        )
    except ServiceDay.DoesNotExist:
        raise HttpError(404, "day_not_found: Service day not open") from None
    return _day_out(day)


@router.post(
    "/days/{service_date}/close",
    response={200: ServiceDayOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Close service day and capture outturn (actuals snapshot). Covers never required.",
)
def close_day(request: HttpRequest, service_date: date, body: CloseDayIn = None):
    body = body or CloseDayIn()
    try:
        day = planning_services.close_service_day(
            service_date,
            notes=body.notes,
            section_outturns=body.section_outturns,
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    day = ServiceDay.objects.prefetch_related("sections", "sections__lines").get(pk=day.pk)
    return _day_out(day)


@router.post(
    "/days/{service_date}/sections/{section}/open",
    response={200: BoardOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Open one section and generate template lines; return full board",
)
def open_section(
    request: HttpRequest, service_date: date, section: str, body: OpenSectionIn = None
):
    body = body or OpenSectionIn()
    try:
        day = ServiceDay.objects.get(service_date=service_date)
    except ServiceDay.DoesNotExist:
        raise HttpError(
            404, "day_not_found: Service day not open — POST /boards/days/open first"
        ) from None
    try:
        planning_services.open_service_section(
            day, section, generate_lines=body.generate_lines
        )
        # D15: scaffold guided prep plan when mode=counts + guided
        try:
            from planning.section_modes import get_setting
            from planning.prep_plan import ensure_prep_plan_proposals

            st = get_setting(section)
            if st.mode == "counts" and st.guided:
                ensure_prep_plan_proposals(
                    service_date=service_date, section=section
                )
        except Exception:  # noqa: BLE001
            pass
        return _board_payload(service_date, section)
    except PlanningError as exc:
        raise _http_planning(exc) from exc


@router.get(
    "/days/{service_date}/sections/{section}",
    response={200: BoardOut, 404: ErrorOut},
    summary="Board fetch — ONE request per section (lines + components + waves + events)",
)
def get_board(request: HttpRequest, service_date: date, section: str):
    try:
        return _board_payload(service_date, section)
    except PlanningError as exc:
        raise _http_planning(exc) from exc


def _board_payload(service_date: date, section: str) -> dict:
    day, sec = planning_services.board_queryset(service_date, section)
    lines = list(sec.lines.all())
    try:
        from assist.services import pending_proposals_for_line_ids

        pending_map = pending_proposals_for_line_ids([ln.pk for ln in lines])
    except Exception:  # noqa: BLE001
        pending_map = {}
    try:
        from planning.section_modes import board_mode_fields

        mode_fields = board_mode_fields(section)
    except Exception:  # noqa: BLE001
        mode_fields = {
            "section_mode": None,
            "mode_prompt_needed": True,
            "guided": section in ("banqueting", "banquet_buffet"),
            "mode_recommendation": None,
        }
    ordering_mode = mode_fields.get("section_mode") == "ordering"
    line_outs = [
        _line_out(ln, pending_map=pending_map, ordering_mode=ordering_mode)
        for ln in lines
    ]
    ticked_count = sum(1 for ln in lines if ln.ticked)
    waves = [_wave_out(w) for w in sec.waves.all()]
    outlets = [
        {
            "id": o.pk,
            "outlet": o.outlet,
            "active": o.active,
            "covers": o.covers,
        }
        for o in sec.outlets.all()
    ]
    prep_plan = None
    if mode_fields.get("section_mode") == "counts":
        try:
            from planning.d15_depth import ensure_qty_draft_proposals

            ensure_qty_draft_proposals(service_date=service_date, section=section)
        except Exception:  # noqa: BLE001
            pass
    if mode_fields.get("guided") and mode_fields.get("section_mode") == "counts":
        try:
            from planning.prep_plan import prep_plan_board_payload

            prep_plan = prep_plan_board_payload(section, service_date)
        except Exception:  # noqa: BLE001
            prep_plan = None
    order_assist = None
    if ordering_mode:
        try:
            from planning.ordering_assist import (
                board_order_assist_payload,
                ensure_menu_completeness_proposals,
                ensure_order_suggest_from_board,
            )

            ensure_menu_completeness_proposals(
                service_date=service_date, section=section
            )
            ensure_order_suggest_from_board(
                service_date=service_date, section=section
            )
            order_assist = board_order_assist_payload(
                section=section, service_date=service_date
            )
        except Exception:  # noqa: BLE001
            order_assist = None
    return {
        "service_date": day.service_date,
        "day_status": day.status,
        "occupancy_rooms": day.occupancy_rooms,
        "occupancy_guests": day.occupancy_guests,
        "section": sec.section,
        "section_id": sec.pk,
        "active": sec.active,
        "covers": sec.covers,
        "covers_source": sec.covers_source or "",
        "notes": sec.notes,
        "beo_events": sec.beo_events or [],
        "outturn": sec.outturn or {},
        "waves": waves,
        "outlets": outlets,
        "lines": line_outs,
        "line_count": len(line_outs),
        "ticked_count": ticked_count,
        **mode_fields,
        "prep_plan": prep_plan,
        "order_assist": order_assist,
    }


@router.patch(
    "/days/{service_date}/sections/{section}/covers",
    response={200: BoardOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary=(
        "Set per-section covers (banquet BEO path). "
        "Never a global dial; non-banquet optional/informational only."
    ),
)
def patch_section_covers(
    request: HttpRequest, service_date: date, section: str, body: SectionCoversIn
):
    events = None
    if body.beo_events is not None:
        events = [{"name": e.name, "covers": e.covers} for e in body.beo_events]
    try:
        planning_services.set_section_covers(
            service_date,
            section,
            covers=body.covers,
            covers_source=body.covers_source or "",
            beo_events=events,
            notes=body.notes,
        )
        return _board_payload(service_date, section)
    except PlanningError as exc:
        raise _http_planning(exc) from exc


@router.get(
    "/days/{service_date}/sections/{section}/waves",
    response={200: list[WaveOut], 404: ErrorOut},
    summary="List waves on a section (banquet*)",
)
def list_waves(request: HttpRequest, service_date: date, section: str):
    try:
        day, sec = planning_services.board_queryset(service_date, section)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return [_wave_out(w) for w in sec.waves.all()]


@router.post(
    "/days/{service_date}/sections/{section}/waves",
    response={200: WaveOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Create a wave on banqueting / banquet_buffet",
)
def create_wave(
    request: HttpRequest, service_date: date, section: str, body: WaveIn
):
    try:
        wave = planning_services.upsert_wave(
            service_date,
            section,
            name=body.name,
            serve_at=body.serve_at,
            covers=body.covers,
            sort_order=body.sort_order,
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return _wave_out(wave)


@router.patch(
    "/waves/{wave_id}",
    response={200: WaveOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Update a wave",
)
def patch_wave(request: HttpRequest, wave_id: int, body: WavePatchIn):
    try:
        wave = Wave.objects.select_related("service_section__service_day").get(pk=wave_id)
    except Wave.DoesNotExist:
        raise HttpError(404, "wave_not_found: Wave not found") from None
    day = wave.service_section.service_day
    sec = wave.service_section
    try:
        planning_services.assert_day_mutable(day)
        updated = planning_services.upsert_wave(
            day.service_date,
            sec.section,
            name=body.name if body.name is not None else wave.name,
            wave_id=wave_id,
            serve_at=body.serve_at if body.serve_at is not None else wave.serve_at,
            covers=body.covers if body.covers is not None else wave.covers,
            sort_order=body.sort_order if body.sort_order is not None else wave.sort_order,
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return _wave_out(updated)


@router.delete(
    "/waves/{wave_id}",
    response={200: dict, 404: ErrorOut, 409: ErrorOut},
    summary="Delete a wave (allocations cascade)",
)
def remove_wave(request: HttpRequest, wave_id: int):
    try:
        planning_services.delete_wave(wave_id)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {"ok": True, "deleted_wave_id": wave_id}


@router.put(
    "/lines/{line_id}/wave-allocations",
    response={200: WaveAllocationsOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary=(
        "Replace wave allocations for one production line "
        "(one line across waves — never duplicate lines; unique line+wave)"
    ),
)
def put_wave_allocations(request: HttpRequest, line_id: int, body: WaveAllocationsPutIn):
    rows = [{"wave_id": a.wave_id, "qty": a.qty} for a in body.allocations]
    try:
        allocs = planning_services.set_wave_allocations(line_id, rows)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    # reload with wave names
    line = _reload_line(line_id)
    return {
        "line_id": line_id,
        "allocations": [_alloc_out(a) for a in line.wave_allocations.all()],
    }


@router.patch(
    "/lines/{line_id}/qty",
    response={200: LineOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary=(
        "Set proposed/planned/actual qty on a line. "
        "check: actual stays null. Canteen produce: enter qty (not covers-derived). "
        "Decimals are JSON numbers (B1)."
    ),
)
def patch_line_qty(request: HttpRequest, line_id: int, body: LineQtyIn):
    # Convenience: if any qty field present without set_* flags, treat as set
    set_proposed = body.set_proposed
    set_planned = body.set_planned
    set_actual = body.set_actual
    # Pydantic always has the fields; callers should set flags. If all flags false,
    # set whichever fields were explicitly intended via flags only — require at least one flag.
    if not (set_proposed or set_planned or set_actual):
        # Allow simple clients: any non-default path — if they send planned_qty alone with flags false
        # we still require at least one set_* to avoid accidental clears. Documented.
        raise HttpError(
            400,
            "invalid_qty: set at least one of set_proposed/set_planned/set_actual true",
        )
    try:
        line = planning_services.set_line_quantities(
            line_id,
            proposed_qty=body.proposed_qty,
            planned_qty=body.planned_qty,
            actual_qty=body.actual_qty,
            set_proposed=set_proposed,
            set_planned=set_planned,
            set_actual=set_actual,
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {"line": _line_out(_reload_line(line.pk))}


@router.post(
    "/days/{service_date}/sections/{section}/scale-produce",
    response={200: ScaleProduceOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary=(
        "Scale banquet produce proposed_qty from covers. "
        "formula: proposed_qty = scaling_covers * template.yield_per_cover. "
        "If template has no yield_per_cover, proposed stays null (human enters planned)."
    ),
)
def scale_produce(request: HttpRequest, service_date: date, section: str):
    try:
        return planning_services.scale_produce_proposed(service_date, section)
    except PlanningError as exc:
        raise _http_planning(exc) from exc


@router.put(
    "/days/{service_date}/sections/{section}/outlets",
    response={200: OutletOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Upsert ServiceOutlet (v1: executive_lounge on a_la_carte only)",
)
def put_outlet(
    request: HttpRequest, service_date: date, section: str, body: OutletIn
):
    try:
        obj = planning_services.upsert_service_outlet(
            service_date,
            section,
            outlet=body.outlet,
            active=body.active,
            covers=body.covers,
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {
        "id": obj.pk,
        "outlet": obj.outlet,
        "active": obj.active,
        "covers": obj.covers,
    }


@router.post(
    "/lines/{line_id}/tick",
    response={200: LineOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Tick a production line (check → ready)",
)
def tick_line(request: HttpRequest, line_id: int, body: TickIn = None):
    body = body or TickIn()
    try:
        line = planning_services.tick_line(
            line_id, ticked=True, status=body.status
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {"line": _line_out(_reload_line(line.pk))}


@router.post(
    "/lines/{line_id}/untick",
    response={200: LineOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Untick a production line (back to planned)",
)
def untick_line(request: HttpRequest, line_id: int):
    try:
        line = planning_services.tick_line(line_id, ticked=False)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {"line": _line_out(_reload_line(line.pk))}


@router.post(
    "/components/{component_id}/tick",
    response={200: ComponentTickOut, 404: ErrorOut, 409: ErrorOut},
    summary="Mark a line component done",
)
def tick_component(request: HttpRequest, component_id: int):
    try:
        comp = planning_services.tick_component(component_id, done=True)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {
        "id": comp.pk,
        "line_id": comp.line_id,
        "done": comp.done,
        "name": comp.name or (comp.item.name if comp.item_id else ""),
    }


@router.post(
    "/components/{component_id}/untick",
    response={200: ComponentTickOut, 404: ErrorOut, 409: ErrorOut},
    summary="Mark a line component not done",
)
def untick_component(request: HttpRequest, component_id: int):
    try:
        comp = planning_services.tick_component(component_id, done=False)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {
        "id": comp.pk,
        "line_id": comp.line_id,
        "done": comp.done,
        "name": comp.name or (comp.item.name if comp.item_id else ""),
    }


@router.post(
    "/lines/quick-add",
    response={200: LineOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Quick-add ad-hoc line (name only, no item FK required)",
)
def quick_add(request: HttpRequest, body: QuickAddIn):
    try:
        line = planning_services.quick_add_line(
            body.service_date,
            body.section,
            body.name,
            mode=body.mode,
            kind=body.kind,
            notes=body.notes or "",
        )
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {"line": _line_out(_reload_line(line.pk))}


@router.patch(
    "/lines/{line_id}/notes",
    response={200: LineOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Set or clear ProductionLine.notes (null/empty clears; max 500)",
)
def patch_line_notes(request: HttpRequest, line_id: int, body: NoteIn):
    try:
        line = planning_services.set_line_note(line_id, body.notes)
    except PlanningError as exc:
        raise _http_planning(exc) from exc
    return {"line": _line_out(_reload_line(line.pk))}
