"""
Phase 2 walk endpoints under /api/v1/walks/...

  POST /api/v1/walks/start
  GET  /api/v1/walks/{walk_id}          # ONE request with lines + breakdown hooks
  POST /api/v1/walks/{walk_id}/lines/batch   # idempotent; 401 → re-auth+retry, never drop data
  POST /api/v1/walks/{walk_id}/submit
  POST /api/v1/walks/{walk_id}/lock
  POST /api/v1/walks/{walk_id}/order-proposal
"""
from __future__ import annotations

from datetime import datetime

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from api.auth import BearerAuth
from api.purchasing import PurchaseOrderOut, _po_out
from api.types import DecimalQty
from purchasing import services as purchasing_services
from purchasing.services import PurchasingError
from walks import services as walk_services
from walks.models import Walk, WalkLine
from walks.services import WalkError

router = Router(tags=["walks"], auth=BearerAuth())

BATCH_401_DOC = (
    "401 means token missing/expired/invalid. Re-authenticate and RETRY this batch. "
    "Never discard client-held walk line payloads because of 401 — cold-room walks "
    "are 30–60 minutes and mid-walk expiry is expected."
)


class ErrorOut(Schema):
    detail: str
    code: str


class StartWalkIn(Schema):
    kind: str = "order"  # order|stock|both
    area_id: int | None = None
    notes: str = ""


class WalkLineBatchIn(Schema):
    """One count row. Idempotent key: (walk_id, item_id, area_id)."""

    item_id: int
    area_id: int | None = None
    line_id: int | None = None
    counted_qty: DecimalQty = None
    counted_unit: str | None = None
    skipped: bool = False
    note: str | None = None
    planned_order_qty: DecimalQty = None
    proposed_order_qty: DecimalQty = None


class BatchLinesIn(Schema):
    lines: list[WalkLineBatchIn]


class WalkLineOut(Schema):
    id: int
    item_id: int
    item_name: str
    item_base_unit: str
    area_id: int | None = None
    area_name: str | None = None
    counted_qty: DecimalQty = None
    counted_unit: str
    qty_base: DecimalQty = None
    proposed_order_qty: DecimalQty = None
    planned_order_qty: DecimalQty = None
    theoretical_qty: DecimalQty = Field(
        default=None,
        description=(
            "On-hand from StockBalance at walk submit/lock (0 if none). "
            "Null while still draft / skipped lines."
        ),
    )
    variance_qty: DecimalQty = Field(
        default=None,
        description=(
            "Unexplained gap (counted − theoretical) after noise floor. "
            "Never labelled error; never auto-corrects pars/balances (D13). "
            "Set on walk submit and lock."
        ),
    )
    skipped: bool
    note: str
    sort_order: int
    # ordering breakdown helpers (filled when par known; else null)
    par: DecimalQty = None
    on_order: DecimalQty = Field(
        default=None,
        description=(
            "Open replenishment PO qty_base for item (draft|sent|confirmed). "
            "Event-scoped POs excluded (D13)."
        ),
    )
    shortfall: DecimalQty = None


class WalkOut(Schema):
    id: int
    kind: str
    area_id: int | None = None
    area_name: str | None = None
    status: str
    started_at: datetime
    submitted_at: datetime | None = None
    locked_at: datetime | None = None
    notes: str
    line_count: int
    counted_count: int
    skipped_count: int
    lines: list[WalkLineOut]


class OrderProposalOut(Schema):
    walk_id: int
    purchase_order_ids: list[int]
    purchase_orders: list[PurchaseOrderOut]
    assist_proposal_id: int | None = None


def _http_walk(exc: WalkError) -> HttpError:
    status = 404 if exc.code.endswith("not_found") else 400
    return HttpError(status, f"{exc.code}: {exc.message}")


def _http_purch(exc: PurchasingError) -> HttpError:
    status = 404 if exc.code.endswith("not_found") else 400
    return HttpError(status, f"{exc.code}: {exc.message}")


def _line_out(ln: WalkLine, *, weekday: int | None = None) -> dict:
    from decimal import Decimal

    from purchasing.services import on_order_qty
    from walks.services import par_for

    par = par_for(ln.item_id, ln.area_id, weekday)
    oo = on_order_qty(ln.item_id)
    counted = None if ln.skipped else ln.qty_base
    shortfall = None
    if par is not None and counted is not None and not ln.skipped:
        s = par - counted - oo
        shortfall = s if s > 0 else Decimal("0")

    return {
        "id": ln.pk,
        "item_id": ln.item_id,
        "item_name": ln.item.name if ln.item_id else "",
        "item_base_unit": ln.item.base_unit if ln.item_id else "",
        "area_id": ln.area_id,
        "area_name": ln.area.name if ln.area_id and ln.area else None,
        "counted_qty": ln.counted_qty,
        "counted_unit": ln.counted_unit or "",
        "qty_base": ln.qty_base,
        "proposed_order_qty": ln.proposed_order_qty,
        "planned_order_qty": ln.planned_order_qty,
        "theoretical_qty": ln.theoretical_qty,
        "variance_qty": ln.variance_qty,
        "skipped": ln.skipped,
        "note": ln.note or "",
        "sort_order": ln.sort_order,
        "par": par,
        "on_order": oo,
        "shortfall": shortfall,
    }


def _walk_out(walk: Walk) -> dict:
    from django.utils import timezone

    weekday = timezone.localdate().weekday()
    lines = list(walk.lines.all())
    outs = [_line_out(ln, weekday=weekday) for ln in lines]
    counted_count = sum(
        1 for ln in lines if (not ln.skipped and ln.counted_qty is not None)
    )
    skipped_count = sum(1 for ln in lines if ln.skipped)
    return {
        "id": walk.pk,
        "kind": walk.kind,
        "area_id": walk.area_id,
        "area_name": walk.area.name if walk.area_id and walk.area else None,
        "status": walk.status,
        "started_at": walk.started_at,
        "submitted_at": walk.submitted_at,
        "locked_at": walk.locked_at,
        "notes": walk.notes or "",
        "line_count": len(outs),
        "counted_count": counted_count,
        "skipped_count": skipped_count,
        "lines": outs,
    }


@router.post(
    "/start",
    response={200: WalkOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Start walk; generate lines by area ordered by walk_order (nulls last)",
)
def start_walk(request: HttpRequest, body: StartWalkIn):
    try:
        walk = walk_services.start_walk(
            kind=body.kind,
            area_id=body.area_id,
            notes=body.notes or "",
        )
        walk = walk_services.walk_queryset(walk.pk)
    except WalkError as exc:
        raise _http_walk(exc) from exc
    return _walk_out(walk)


@router.get(
    "/{walk_id}",
    response={200: WalkOut, 401: ErrorOut, 404: ErrorOut},
    summary="Fetch walk + lines in ONE request (par/on_order/shortfall per line when known)",
)
def get_walk(request: HttpRequest, walk_id: int):
    try:
        walk = walk_services.walk_queryset(walk_id)
    except WalkError as exc:
        raise _http_walk(exc) from exc
    return _walk_out(walk)


@router.post(
    "/{walk_id}/lines/batch",
    response={200: WalkOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Batch submit walk lines (idempotent on walk+item+area)",
    description=BATCH_401_DOC,
)
def batch_lines(request: HttpRequest, walk_id: int, body: BatchLinesIn):
    """
    Idempotent upsert. Double-submit is normal after signal loss.

    **401 contract:** re-authenticate and retry — NEVER drop client walk data.
    """
    payload = []
    for ln in body.lines:
        if hasattr(ln, "model_dump"):
            payload.append(ln.model_dump())
        else:
            payload.append(ln.dict())
    try:
        walk = walk_services.batch_submit_lines(walk_id, payload)
    except WalkError as exc:
        raise _http_walk(exc) from exc
    return _walk_out(walk)


@router.post(
    "/{walk_id}/submit",
    response={200: WalkOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Mark walk submitted (still editable until lock)",
)
def submit_walk(request: HttpRequest, walk_id: int):
    try:
        walk = walk_services.submit_walk(walk_id)
    except WalkError as exc:
        raise _http_walk(exc) from exc
    return _walk_out(walk)


@router.post(
    "/{walk_id}/lock",
    response={200: WalkOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Lock walk (no further batch edits)",
)
def lock_walk(request: HttpRequest, walk_id: int):
    try:
        walk = walk_services.lock_walk(walk_id)
    except WalkError as exc:
        raise _http_walk(exc) from exc
    return _walk_out(walk)


@router.post(
    "/{walk_id}/order-proposal",
    response={200: OrderProposalOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary=(
        "Build draft POs: sum shortfalls across areas per (item,supplier) "
        "then ceil(total/pack_qty); breakdown on every line"
    ),
)
def order_proposal(request: HttpRequest, walk_id: int):
    try:
        pos = purchasing_services.propose_orders_from_walk(walk_id)
    except PurchasingError as exc:
        raise _http_purch(exc) from exc
    except WalkError as exc:
        raise _http_walk(exc) from exc

    # D15.1: also surface shortfall as Assist order_suggest (accept → order_packs)
    assist_id = None
    try:
        from planning.d15_depth import ensure_order_suggest_from_walk
        from walks.models import Walk

        w = Walk.objects.filter(pk=walk_id).only("id").first()
        prop = ensure_order_suggest_from_walk(
            walk_id=walk_id,
            service_date=timezone.localdate(),
        )
        assist_id = prop.pk if prop else None
    except Exception:  # noqa: BLE001
        assist_id = None

    po_outs = [_po_out(po) for po in pos]
    return {
        "walk_id": walk_id,
        "purchase_order_ids": [p["id"] for p in po_outs],
        "purchase_orders": po_outs,
        "assist_proposal_id": assist_id,
    }
