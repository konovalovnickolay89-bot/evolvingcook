"""
Purchasing business rules (Phase 2 + D13 scope).

Order proposal: shortfall = max(0, par − counted − on_order) summed across
ALL areas per (item, supplier) before ceil(total/pack_qty).

D13: on_order sums open replenishment POs only (draft|sent|confirmed).
Event-scoped POs never reduce shortfall.

Phase 3: complete delivery → inventory.post_receipts_for_delivery (kind=receipt).
Variance language: unexplained (never "error"); math lives in inventory.services.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone

from catalog.models import Supplier, SupplierItem
from purchasing.models import Delivery, DeliveryLine, PurchaseOrder, PurchaseOrderLine
from walks.models import Walk, WalkLine
from walks.services import WalkError, par_for, walk_queryset


class PurchasingError(Exception):
    def __init__(self, message: str, code: str = "purchasing_error"):
        super().__init__(message)
        self.message = message
        self.code = code


# Suppress only zero packs on order proposal. Brief pack-level floor only.
NOISE_FLOOR_PACKS = Decimal("0")

# --- D13 variance language (implemented in inventory.services) ---
VARIANCE_LABEL = "unexplained"
OPEN_PO_STATUSES_FOR_ON_ORDER = (
    PurchaseOrder.Status.DRAFT,
    PurchaseOrder.Status.SENT,
    PurchaseOrder.Status.CONFIRMED,
)


def on_order_qty(item_id: int, *, exclude_po_id: int | None = None) -> Decimal:
    """
    Base units still outstanding on open **replenishment** POs.

    Open statuses: draft | sent | confirmed (not received/closed).
    D13: scope=event POs are excluded regardless of status — they must never
    reduce replenishment shortfall.
    """
    qs = PurchaseOrderLine.objects.filter(
        supplier_item__item_id=item_id,
        purchase_order__status__in=list(OPEN_PO_STATUSES_FOR_ON_ORDER),
        purchase_order__scope=PurchaseOrder.Scope.REPLENISHMENT,
    )
    if exclude_po_id is not None:
        qs = qs.exclude(purchase_order_id=exclude_po_id)
    total = qs.aggregate(s=Sum("qty_base"))["s"]
    return total if total is not None else Decimal("0")


def next_order_and_delivery_dates(
    supplier: Supplier,
    *,
    now: datetime | None = None,
) -> tuple[date, date]:
    """
    order_date = next supplier order day respecting cutoff.
    delivery_date = order_date + lead_time_days.
    Empty order_days → any day (unknown cadence); still respect cutoff if set.
    """
    now = now or timezone.localtime()
    today = now.date()
    local_t = now.time()
    order_days = list(supplier.order_days or [])
    lead = int(supplier.lead_time_days or 0)
    cutoff: time | None = supplier.cutoff_time

    def ok_day(d: date) -> bool:
        if order_days and d.weekday() not in order_days:
            return False
        if d == today and cutoff is not None and local_t >= cutoff:
            return False
        return True

    d = today
    for _ in range(14):
        if ok_day(d):
            return d, d + timedelta(days=lead)
        d += timedelta(days=1)
    # Fallback
    return today + timedelta(days=1), today + timedelta(days=1 + lead)


def preferred_supplier_item(item_id: int) -> SupplierItem | None:
    qs = (
        SupplierItem.objects.filter(item_id=item_id, active=True)
        .select_related("supplier", "item")
        .order_by("-preferred", "supplier_id", "id")
    )
    # Prefer rows that can pack
    with_pack = qs.exclude(pack_qty__isnull=True).exclude(pack_qty=0).first()
    if with_pack:
        return with_pack
    return qs.first()


def _ceil_packs(shortfall: Decimal, pack_qty: Decimal) -> Decimal:
    if pack_qty <= 0:
        return Decimal("0")
    if shortfall <= 0:
        return Decimal("0")
    return (shortfall / pack_qty).to_integral_value(rounding=ROUND_CEILING)


@transaction.atomic
def propose_orders_from_walk(
    walk_id: int,
    *,
    replace_drafts: bool = True,
) -> list[PurchaseOrder]:
    """
    Build draft POs from walk counts.
    Sum shortfalls across ALL areas per (item → supplier) before pack ceil.
    """
    try:
        walk = Walk.objects.select_for_update().get(pk=walk_id)
    except Walk.DoesNotExist as exc:
        raise PurchasingError(f"Walk {walk_id} not found", code="walk_not_found") from exc

    if walk.status == Walk.Status.DRAFT:
        # Allow proposal from draft after batch; optional soft submit
        pass

    lines = list(
        WalkLine.objects.filter(walk_id=walk_id)
        .select_related("item", "area")
        .order_by("sort_order", "id")
    )
    weekday = timezone.localdate().weekday()

    # Aggregate per item across areas
    # item_id -> {par_sum, counted_sum, area_rows}
    agg: dict[int, dict[str, Any]] = {}
    for ln in lines:
        if ln.skipped:
            continue
        # Typed 0 is valid counted; null without skip means not counted yet — skip order
        if ln.qty_base is None and ln.counted_qty is None:
            continue
        counted = ln.qty_base if ln.qty_base is not None else Decimal("0")
        par = par_for(ln.item_id, ln.area_id, weekday)
        if par is None:
            # No par → cannot derive shortfall; leave clean (partial catalogue)
            continue
        bucket = agg.setdefault(
            ln.item_id,
            {
                "par_sum": Decimal("0"),
                "counted_sum": Decimal("0"),
                "item": ln.item,
            },
        )
        bucket["par_sum"] += par
        bucket["counted_sum"] += counted

    # Drop existing draft POs for this walk if replacing
    if replace_drafts:
        PurchaseOrder.objects.filter(
            walk_id=walk_id, status=PurchaseOrder.Status.DRAFT
        ).delete()

    # Build lines grouped by supplier
    by_supplier: dict[int, list[dict[str, Any]]] = {}
    for item_id, bucket in agg.items():
        # Phase 5 / D12: do not PO the house-made parent as if bought.
        # Components are ordered separately when they appear on walks with pars.
        item_obj = bucket.get("item")
        if item_obj is not None and getattr(item_obj, "house_made", False):
            continue
        oo = on_order_qty(item_id)
        shortfall = bucket["par_sum"] - bucket["counted_sum"] - oo
        if shortfall < 0:
            shortfall = Decimal("0")
        si = preferred_supplier_item(item_id)
        if si is None or si.pack_qty is None or si.pack_qty <= 0:
            continue
        if not si.supplier.active:
            continue
        packs = _ceil_packs(shortfall, si.pack_qty)
        if packs <= NOISE_FLOOR_PACKS:
            continue
        qty_base = packs * si.pack_qty
        by_supplier.setdefault(si.supplier_id, []).append(
            {
                "supplier_item": si,
                "proposed_packs": packs,
                "packs": packs,
                "qty_base": qty_base,
                "price": si.price,
                "par": bucket["par_sum"],
                "counted": bucket["counted_sum"],
                "on_order": oo,
                "shortfall": shortfall,
            }
        )
        # Snapshot proposed on walk lines for this item
        WalkLine.objects.filter(walk_id=walk_id, item_id=item_id).update(
            proposed_order_qty=shortfall
        )

    pos: list[PurchaseOrder] = []
    for supplier_id, plines in by_supplier.items():
        supplier = Supplier.objects.get(pk=supplier_id)
        order_date, delivery_date = next_order_and_delivery_dates(supplier)
        total = Decimal("0")
        for pl in plines:
            if pl["price"] is not None and pl["packs"] is not None:
                total += pl["price"] * pl["packs"]
        po = PurchaseOrder.objects.create(
            supplier=supplier,
            walk=walk,
            order_date=order_date,
            delivery_date=delivery_date,
            status=PurchaseOrder.Status.DRAFT,
            scope=PurchaseOrder.Scope.REPLENISHMENT,
            total=total if total else None,
            notes="",
        )
        PurchaseOrderLine.objects.bulk_create(
            [
                PurchaseOrderLine(
                    purchase_order=po,
                    supplier_item=pl["supplier_item"],
                    proposed_packs=pl["proposed_packs"],
                    packs=pl["packs"],
                    qty_base=pl["qty_base"],
                    price=pl["price"],
                    par=pl["par"],
                    counted=pl["counted"],
                    on_order=pl["on_order"],
                    shortfall=pl["shortfall"],
                )
                for pl in plines
            ]
        )
        pos.append(po_queryset(po.pk))
    return pos


def po_queryset(po_id: int) -> PurchaseOrder:
    try:
        return (
            PurchaseOrder.objects.select_related("supplier", "walk")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=PurchaseOrderLine.objects.select_related(
                        "supplier_item",
                        "supplier_item__item",
                        "supplier_item__supplier",
                    ).order_by("id"),
                )
            )
            .get(pk=po_id)
        )
    except PurchaseOrder.DoesNotExist as exc:
        raise PurchasingError(f"PO {po_id} not found", code="po_not_found") from exc


@transaction.atomic
def send_po(po_id: int) -> PurchaseOrder:
    po = PurchaseOrder.objects.select_for_update().filter(pk=po_id).first()
    if po is None:
        raise PurchasingError(f"PO {po_id} not found", code="po_not_found")
    if po.status != PurchaseOrder.Status.DRAFT:
        raise PurchasingError(
            f"PO status is {po.status}, expected draft",
            code="invalid_po_status",
        )
    po.status = PurchaseOrder.Status.SENT
    po.sent_at = timezone.now()
    po.save(update_fields=["status", "sent_at"])
    return po_queryset(po_id)


@transaction.atomic
def create_delivery(
    po_id: int,
    *,
    received_on: date | None = None,
    lines: list[dict[str, Any]] | None = None,
    notes: str = "",
    complete: bool = False,
) -> Delivery:
    """
    Create delivery receipt. When status becomes complete, post StockMovement
    receipts + balance updates (Phase 3 inventory.services.post_receipts_for_delivery).
    """
    po = PurchaseOrder.objects.select_for_update().filter(pk=po_id).first()
    if po is None:
        raise PurchasingError(f"PO {po_id} not found", code="po_not_found")
    if po.status not in {
        PurchaseOrder.Status.SENT,
        PurchaseOrder.Status.CONFIRMED,
        PurchaseOrder.Status.RECEIVED,
    }:
        # Allow receipt path after send; draft must be sent first
        if po.status == PurchaseOrder.Status.DRAFT:
            raise PurchasingError("Send PO before delivery receipt", code="po_not_sent")

    received_on = received_on or timezone.localdate()
    delivery = Delivery.objects.create(
        purchase_order=po,
        supplier_id=po.supplier_id,
        received_on=received_on,
        status=Delivery.Status.COMPLETE if complete else Delivery.Status.OPEN,
        notes=notes or "",
    )

    po_lines = {
        ln.supplier_item_id: ln
        for ln in PurchaseOrderLine.objects.filter(purchase_order=po).select_related(
            "supplier_item"
        )
    }

    if lines:
        for raw in lines:
            si_id = raw.get("supplier_item_id")
            if si_id is None:
                raise PurchasingError("supplier_item_id required", code="invalid_line")
            si_id = int(si_id)
            pol = po_lines.get(si_id)
            packs_expected = raw.get("packs_expected")
            if packs_expected is None and pol is not None:
                packs_expected = pol.packs
            elif packs_expected is not None:
                packs_expected = Decimal(str(packs_expected))
            packs_received = raw.get("packs_received")
            if packs_received is not None and packs_received != "":
                packs_received = Decimal(str(packs_received))
            else:
                packs_received = None
            note = raw.get("note") or ""
            if note and note not in {c.value for c in DeliveryLine.NoteKind}:
                raise PurchasingError(
                    f"Invalid delivery note kind: {note}",
                    code="invalid_note",
                )
            price = raw.get("price")
            if price is not None and price != "":
                price = Decimal(str(price))
            elif pol is not None:
                price = pol.price
            else:
                price = None
            DeliveryLine.objects.create(
                delivery=delivery,
                supplier_item_id=si_id,
                packs_expected=packs_expected,
                packs_received=packs_received,
                price=price,
                note=note,
                note_text=raw.get("note_text") or "",
            )
    else:
        # Default expected lines from PO
        for pol in po_lines.values():
            DeliveryLine.objects.create(
                delivery=delivery,
                supplier_item_id=pol.supplier_item_id,
                packs_expected=pol.packs,
                packs_received=None,
                price=pol.price,
                note="",
            )

    if complete or (
        delivery.lines.exists()
        and not delivery.lines.filter(packs_received__isnull=True).exists()
    ):
        delivery.status = Delivery.Status.COMPLETE
        delivery.save(update_fields=["status"])
        if po.status != PurchaseOrder.Status.CLOSED:
            po.status = PurchaseOrder.Status.RECEIVED
            po.save(update_fields=["status"])
        from inventory.services import post_receipts_for_delivery

        post_receipts_for_delivery(delivery.pk)

    return delivery_queryset(delivery.pk)


def delivery_queryset(delivery_id: int) -> Delivery:
    try:
        return (
            Delivery.objects.select_related("supplier", "purchase_order")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=DeliveryLine.objects.select_related(
                        "supplier_item", "supplier_item__item"
                    ).order_by("id"),
                )
            )
            .get(pk=delivery_id)
        )
    except Delivery.DoesNotExist as exc:
        raise PurchasingError(
            f"Delivery {delivery_id} not found", code="delivery_not_found"
        ) from exc


@transaction.atomic
def batch_delivery_lines(delivery_id: int, lines: list[dict[str, Any]]) -> Delivery:
    delivery = Delivery.objects.select_for_update().filter(pk=delivery_id).first()
    if delivery is None:
        raise PurchasingError(
            f"Delivery {delivery_id} not found", code="delivery_not_found"
        )
    existing = {
        ln.supplier_item_id: ln
        for ln in DeliveryLine.objects.select_for_update().filter(delivery=delivery)
    }
    for raw in lines:
        si_id = int(raw["supplier_item_id"])
        ln = existing.get(si_id)
        if ln is None:
            ln = DeliveryLine(delivery=delivery, supplier_item_id=si_id)
            existing[si_id] = ln
        if "packs_expected" in raw and raw["packs_expected"] is not None:
            ln.packs_expected = Decimal(str(raw["packs_expected"]))
        if "packs_received" in raw:
            pr = raw["packs_received"]
            ln.packs_received = Decimal(str(pr)) if pr is not None and pr != "" else None
        if "note" in raw and raw["note"] is not None:
            note = raw["note"] or ""
            if note and note not in {c.value for c in DeliveryLine.NoteKind}:
                raise PurchasingError(
                    f"Invalid delivery note kind: {note}",
                    code="invalid_note",
                )
            ln.note = note
        if "note_text" in raw and raw["note_text"] is not None:
            ln.note_text = raw["note_text"] or ""
        if "price" in raw:
            p = raw["price"]
            ln.price = Decimal(str(p)) if p is not None and p != "" else None
        ln.save()

    # Auto-complete when every line has packs_received; then post ledger receipts.
    was_complete = delivery.status == Delivery.Status.COMPLETE
    if (
        delivery.lines.exists()
        and not delivery.lines.filter(packs_received__isnull=True).exists()
    ):
        if not was_complete:
            delivery.status = Delivery.Status.COMPLETE
            delivery.save(update_fields=["status"])
            po = PurchaseOrder.objects.select_for_update().filter(
                pk=delivery.purchase_order_id
            ).first()
            if po is not None and po.status != PurchaseOrder.Status.CLOSED:
                po.status = PurchaseOrder.Status.RECEIVED
                po.save(update_fields=["status"])
        from inventory.services import post_receipts_for_delivery

        post_receipts_for_delivery(delivery.pk)

    return delivery_queryset(delivery_id)
