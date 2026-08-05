"""
Phase 3 inventory endpoints under /api/v1/inventory/...

  GET  /api/v1/inventory/balances
  GET  /api/v1/inventory/movements
  POST /api/v1/inventory/waste
  POST /api/v1/inventory/count-adjustment
  POST /api/v1/inventory/transfer

Delivery receipts and walk variance are side-effects of purchasing/walks services.
"""
from __future__ import annotations

from datetime import datetime

from django.http import HttpRequest
from ninja import Query, Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from api.auth import BearerAuth
from api.types import DecimalQty, DecimalQtyRequired
from inventory import services as inv_services
from inventory.models import StockBalance, StockMovement
from inventory.services import InventoryError, VARIANCE_LABEL

router = Router(tags=["inventory"], auth=BearerAuth())


class ErrorOut(Schema):
    detail: str
    code: str


class BalanceOut(Schema):
    item_id: int
    item_name: str
    item_base_unit: str
    area_id: int
    area_name: str
    qty: DecimalQty = None
    updated_at: datetime


class MovementOut(Schema):
    id: int
    item_id: int
    item_name: str
    area_id: int
    area_name: str
    qty: DecimalQty = None
    kind: str
    source_type: str
    source_id: str
    occurred_at: datetime
    note: str


class WasteIn(Schema):
    item_id: int
    area_id: int
    qty: DecimalQtyRequired = Field(
        description="Positive amount wasted (base units). Stored as negative movement.",
    )
    note: str = ""


class CountAdjustmentIn(Schema):
    item_id: int
    area_id: int
    qty: DecimalQtyRequired = Field(
        description=(
            "Signed compensating qty in base units. Human-driven only — "
            "never auto-derived from unexplained variance (D13)."
        ),
    )
    note: str = ""


class TransferIn(Schema):
    item_id: int
    from_area_id: int
    to_area_id: int
    qty: DecimalQtyRequired = Field(description="Positive amount to move (base units).")
    note: str = ""


class TransferOut(Schema):
    transfer_out: MovementOut
    transfer_in: MovementOut


def _http_inv(exc: InventoryError) -> HttpError:
    status = 404 if exc.code.endswith("not_found") else 400
    return HttpError(status, f"{exc.code}: {exc.message}")


def _bal_out(b: StockBalance) -> dict:
    return {
        "item_id": b.item_id,
        "item_name": b.item.name if b.item_id else "",
        "item_base_unit": b.item.base_unit if b.item_id else "",
        "area_id": b.area_id,
        "area_name": b.area.name if b.area_id else "",
        "qty": b.qty,
        "updated_at": b.updated_at,
    }


def _mov_out(m: StockMovement) -> dict:
    return {
        "id": m.pk,
        "item_id": m.item_id,
        "item_name": m.item.name if m.item_id else "",
        "area_id": m.area_id,
        "area_name": m.area.name if m.area_id else "",
        "qty": m.qty,
        "kind": m.kind,
        "source_type": m.source_type or "",
        "source_id": m.source_id or "",
        "occurred_at": m.occurred_at,
        "note": m.note or "",
    }


@router.get(
    "/balances",
    response={200: list[BalanceOut], 401: ErrorOut},
    summary="List stock balances (filter item and/or area)",
)
def get_balances(
    request: HttpRequest,
    item_id: int | None = Query(None),
    area_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    rows = inv_services.list_balances(item_id=item_id, area_id=area_id, limit=limit)
    return [_bal_out(b) for b in rows]


@router.get(
    "/movements",
    response={200: list[MovementOut], 401: ErrorOut},
    summary="List recent stock movements (filter item/area/kind)",
)
def get_movements(
    request: HttpRequest,
    item_id: int | None = Query(None),
    area_id: int | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    rows = inv_services.list_movements(
        item_id=item_id, area_id=area_id, kind=kind, limit=limit
    )
    return [_mov_out(m) for m in rows]


@router.post(
    "/waste",
    response={200: MovementOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Post waste movement (balance decreases)",
)
def post_waste(request: HttpRequest, body: WasteIn):
    try:
        mov = inv_services.post_waste(
            item_id=body.item_id,
            area_id=body.area_id,
            qty=body.qty,
            note=body.note or "",
        )
        mov = StockMovement.objects.select_related("item", "area").get(pk=mov.pk)
    except InventoryError as exc:
        raise _http_inv(exc) from exc
    return _mov_out(mov)


@router.post(
    "/count-adjustment",
    response={200: MovementOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary=(
        "Human compensating count_adjustment movement. "
        f"Variance is {VARIANCE_LABEL} only — never auto-posts adjustments."
    ),
)
def post_count_adjustment(request: HttpRequest, body: CountAdjustmentIn):
    try:
        mov = inv_services.post_count_adjustment(
            item_id=body.item_id,
            area_id=body.area_id,
            qty=body.qty,
            note=body.note or "",
        )
        mov = StockMovement.objects.select_related("item", "area").get(pk=mov.pk)
    except InventoryError as exc:
        raise _http_inv(exc) from exc
    return _mov_out(mov)


@router.post(
    "/transfer",
    response={200: TransferOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Paired transfer_out + transfer_in in one transaction",
)
def post_transfer(request: HttpRequest, body: TransferIn):
    try:
        out_m, in_m = inv_services.transfer_stock(
            item_id=body.item_id,
            from_area_id=body.from_area_id,
            to_area_id=body.to_area_id,
            qty=body.qty,
            note=body.note or "",
        )
        out_m = StockMovement.objects.select_related("item", "area").get(pk=out_m.pk)
        in_m = StockMovement.objects.select_related("item", "area").get(pk=in_m.pk)
    except InventoryError as exc:
        raise _http_inv(exc) from exc
    return {"transfer_out": _mov_out(out_m), "transfer_in": _mov_out(in_m)}
