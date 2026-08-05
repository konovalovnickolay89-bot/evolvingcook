"""
Phase 2 purchasing endpoints under /api/v1/purchasing/...

  GET  /api/v1/purchasing/orders/{po_id}
  POST /api/v1/purchasing/orders/{po_id}/send
  POST /api/v1/purchasing/orders/{po_id}/deliveries
  GET  /api/v1/purchasing/deliveries/{delivery_id}
  POST /api/v1/purchasing/deliveries/{delivery_id}/lines/batch
"""
from __future__ import annotations

from datetime import date, datetime

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from api.auth import BearerAuth
from api.types import DecimalQty
from purchasing import services as purchasing_services
from purchasing.models import Delivery, DeliveryLine, PurchaseOrder, PurchaseOrderLine
from purchasing.services import PurchasingError

router = Router(tags=["purchasing"], auth=BearerAuth())


class ErrorOut(Schema):
    detail: str
    code: str


class POLineOut(Schema):
    id: int
    supplier_item_id: int
    item_id: int
    item_name: str
    supplier_code: str
    pack_description: str
    pack_qty: DecimalQty = None
    proposed_packs: DecimalQty = None
    packs: DecimalQty = None
    qty_base: DecimalQty = None
    price: DecimalQty = None
    # Breakdown on every order line (contract)
    par: DecimalQty = None
    counted: DecimalQty = None
    on_order: DecimalQty = Field(
        default=None,
        description=(
            "Snapshot at proposal: open replenishment PO qty_base sum for the item "
            "(statuses draft|sent|confirmed). Event-scoped POs excluded (D13)."
        ),
    )
    shortfall: DecimalQty = None
    note: str = ""


class PurchaseOrderOut(Schema):
    id: int
    supplier_id: int
    supplier_name: str
    walk_id: int | None = None
    order_date: date
    delivery_date: date | None = None
    status: str
    scope: str = Field(
        description=(
            "replenishment (default) | event. Only replenishment open qty counts "
            "toward on_order / shortfall. Event POs never reduce shortfall. "
            "Order-proposal creates always default to replenishment."
        ),
    )
    total: DecimalQty = None
    notes: str
    sent_at: datetime | None = None
    created_at: datetime
    line_count: int
    lines: list[POLineOut]


class DeliveryLineIn(Schema):
    supplier_item_id: int
    packs_expected: DecimalQty = None
    packs_received: DecimalQty = None
    price: DecimalQty = None
    note: str = ""  # short|over|substituted|rejected|ok
    note_text: str = ""


class CreateDeliveryIn(Schema):
    received_on: date | None = None
    notes: str = ""
    complete: bool = False
    lines: list[DeliveryLineIn] | None = None


class DeliveryLineOut(Schema):
    id: int
    supplier_item_id: int
    item_id: int
    item_name: str
    packs_expected: DecimalQty = None
    packs_received: DecimalQty = None
    price: DecimalQty = None
    note: str
    note_text: str


class DeliveryOut(Schema):
    id: int
    purchase_order_id: int
    supplier_id: int
    supplier_name: str
    received_on: date
    status: str
    notes: str
    created_at: datetime
    line_count: int
    lines: list[DeliveryLineOut]


class BatchDeliveryLinesIn(Schema):
    lines: list[DeliveryLineIn]


def _http_purch(exc: PurchasingError) -> HttpError:
    status = 404 if exc.code.endswith("not_found") else 400
    return HttpError(status, f"{exc.code}: {exc.message}")


def _poline_out(ln: PurchaseOrderLine) -> dict:
    si = ln.supplier_item
    item = si.item if si else None
    return {
        "id": ln.pk,
        "supplier_item_id": ln.supplier_item_id,
        "item_id": si.item_id if si else 0,
        "item_name": item.name if item else "",
        "supplier_code": si.supplier_code if si else "",
        "pack_description": si.pack_description if si else "",
        "pack_qty": si.pack_qty if si else None,
        "proposed_packs": ln.proposed_packs,
        "packs": ln.packs,
        "qty_base": ln.qty_base,
        "price": ln.price,
        "par": ln.par,
        "counted": ln.counted,
        "on_order": ln.on_order,
        "shortfall": ln.shortfall,
        "note": ln.note or "",
    }


def _po_out(po: PurchaseOrder) -> dict:
    lines = list(po.lines.all())
    return {
        "id": po.pk,
        "supplier_id": po.supplier_id,
        "supplier_name": po.supplier.name if po.supplier_id else "",
        "walk_id": po.walk_id,
        "order_date": po.order_date,
        "delivery_date": po.delivery_date,
        "status": po.status,
        "scope": po.scope,
        "total": po.total,
        "notes": po.notes or "",
        "sent_at": po.sent_at,
        "created_at": po.created_at,
        "line_count": len(lines),
        "lines": [_poline_out(ln) for ln in lines],
    }


def _dline_out(ln: DeliveryLine) -> dict:
    si = ln.supplier_item
    item = si.item if si else None
    return {
        "id": ln.pk,
        "supplier_item_id": ln.supplier_item_id,
        "item_id": si.item_id if si else 0,
        "item_name": item.name if item else "",
        "packs_expected": ln.packs_expected,
        "packs_received": ln.packs_received,
        "price": ln.price,
        "note": ln.note or "",
        "note_text": ln.note_text or "",
    }


def _delivery_out(d: Delivery) -> dict:
    lines = list(d.lines.all())
    return {
        "id": d.pk,
        "purchase_order_id": d.purchase_order_id,
        "supplier_id": d.supplier_id,
        "supplier_name": d.supplier.name if d.supplier_id else "",
        "received_on": d.received_on,
        "status": d.status,
        "notes": d.notes or "",
        "created_at": d.created_at,
        "line_count": len(lines),
        "lines": [_dline_out(ln) for ln in lines],
    }


@router.get(
    "/orders/{po_id}",
    response={200: PurchaseOrderOut, 401: ErrorOut, 404: ErrorOut},
    summary=(
        "Fetch PO + lines with breakdown (one request). "
        "scope=replenishment|event; on_order on lines is snapshot at proposal time "
        "(open replenishment only: draft|sent|confirmed)."
    ),
)
def get_po(request: HttpRequest, po_id: int):
    try:
        po = purchasing_services.po_queryset(po_id)
    except PurchasingError as exc:
        raise _http_purch(exc) from exc
    return _po_out(po)


@router.post(
    "/orders/{po_id}/send",
    response={200: PurchaseOrderOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="PO draft → sent",
)
def send_po(request: HttpRequest, po_id: int):
    try:
        po = purchasing_services.send_po(po_id)
    except PurchasingError as exc:
        raise _http_purch(exc) from exc
    return _po_out(po)


@router.post(
    "/orders/{po_id}/deliveries",
    response={200: DeliveryOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary=(
        "Create delivery receipt; when complete, posts StockMovement kind=receipt "
        "and updates StockBalance (item.default_area)"
    ),
)
def create_delivery(request: HttpRequest, po_id: int, body: CreateDeliveryIn):
    try:
        lines = None
        if body.lines is not None:
            lines = [ln.dict() for ln in body.lines]
        d = purchasing_services.create_delivery(
            po_id,
            received_on=body.received_on,
            lines=lines,
            notes=body.notes or "",
            complete=body.complete,
        )
    except PurchasingError as exc:
        raise _http_purch(exc) from exc
    return _delivery_out(d)


@router.get(
    "/deliveries/{delivery_id}",
    response={200: DeliveryOut, 401: ErrorOut, 404: ErrorOut},
    summary="Fetch delivery + lines (one request)",
)
def get_delivery(request: HttpRequest, delivery_id: int):
    try:
        d = purchasing_services.delivery_queryset(delivery_id)
    except PurchasingError as exc:
        raise _http_purch(exc) from exc
    return _delivery_out(d)


@router.post(
    "/deliveries/{delivery_id}/lines/batch",
    response={200: DeliveryOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    summary="Batch update delivery lines (short|over|substituted|rejected)",
)
def batch_delivery_lines(request: HttpRequest, delivery_id: int, body: BatchDeliveryLinesIn):
    try:
        d = purchasing_services.batch_delivery_lines(
            delivery_id, [ln.dict() for ln in body.lines]
        )
    except PurchasingError as exc:
        raise _http_purch(exc) from exc
    return _delivery_out(d)
