"""
Inventory business rules (Phase 3 ledger).

B10: append-only movements (model save guard + PG trigger).
B12: balance updates via F() inside the same atomic() as movement insert.
D13: variance = unexplained; never auto-correct pars/balances.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone

from catalog.models import Item, StorageArea
from inventory.models import StockBalance, StockMovement


class InventoryError(Exception):
    def __init__(self, message: str, code: str = "inventory_error"):
        super().__init__(message)
        self.message = message
        self.code = code


# D13 label lock — use in API descriptions/messages; never "error"
VARIANCE_LABEL = "unexplained"


def variance_noise_floor(item: Item | None = None) -> Decimal:
    """
    Absolute |gap| at or below this is treated as zero unexplained.
    Default from settings.VARIANCE_NOISE_FLOOR (sensible small Decimal).
    Optional per-item override via item.variance_noise_floor if present later.
    """
    raw = getattr(settings, "VARIANCE_NOISE_FLOOR", "0.001")
    floor = Decimal(str(raw))
    if item is not None:
        override = getattr(item, "variance_noise_floor", None)
        if override is not None:
            floor = Decimal(str(override))
    return floor


def get_balance_qty(item_id: int, area_id: int) -> Decimal:
    row = (
        StockBalance.objects.filter(item_id=item_id, area_id=area_id)
        .only("qty")
        .first()
    )
    return row.qty if row is not None else Decimal("0")


@transaction.atomic
def apply_movement(
    *,
    item_id: int,
    area_id: int,
    qty: Decimal,
    kind: str,
    source_type: str = "",
    source_id: str = "",
    note: str = "",
    occurred_at=None,
) -> StockMovement:
    """
    Insert one movement and update balance with F() in the same atomic block.
    qty is SIGNED (caller chooses sign).
    """
    if kind not in {c.value for c in StockMovement.Kind}:
        raise InventoryError(f"Invalid movement kind: {kind}", code="invalid_kind")
    qty = Decimal(str(qty))
    if qty == 0:
        raise InventoryError("Movement qty must be non-zero", code="zero_qty")

    try:
        Item.objects.get(pk=item_id)
    except Item.DoesNotExist as exc:
        raise InventoryError(f"Item {item_id} not found", code="item_not_found") from exc
    try:
        StorageArea.objects.get(pk=area_id)
    except StorageArea.DoesNotExist as exc:
        raise InventoryError(f"Area {area_id} not found", code="area_not_found") from exc

    movement = StockMovement(
        item_id=item_id,
        area_id=area_id,
        qty=qty,
        kind=kind,
        source_type=source_type or "",
        source_id=str(source_id) if source_id is not None else "",
        occurred_at=occurred_at or timezone.now(),
        note=note or "",
    )
    # insert only
    movement.save()

    # B12: ensure row then F() — never read-modify-write Python qty
    _balance, _created = StockBalance.objects.select_for_update().get_or_create(
        item_id=item_id,
        area_id=area_id,
        defaults={"qty": Decimal("0"), "updated_at": timezone.now()},
    )
    StockBalance.objects.filter(item_id=item_id, area_id=area_id).update(
        qty=F("qty") + qty,
        updated_at=timezone.now(),
    )
    return movement


def _delivery_receipts_already_posted(delivery_id: int) -> bool:
    return StockMovement.objects.filter(
        source_type="delivery",
        source_id=str(delivery_id),
        kind=StockMovement.Kind.RECEIPT,
    ).exists()


@transaction.atomic
def post_receipts_for_delivery(delivery_id: int) -> list[StockMovement]:
    """
    When a delivery is complete, write receipt movements for each line with
    packs_received. Area = item.default_area (purchasing has no area on lines).
    Idempotent per delivery_id.
    Rejected lines (note=rejected) get no receipt (or zero packs).
    """
    from purchasing.models import Delivery, DeliveryLine

    delivery = (
        Delivery.objects.select_for_update()
        .filter(pk=delivery_id)
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=DeliveryLine.objects.select_related(
                    "supplier_item",
                    "supplier_item__item",
                    "supplier_item__item__default_area",
                ),
            )
        )
        .first()
    )
    if delivery is None:
        raise InventoryError(
            f"Delivery {delivery_id} not found", code="delivery_not_found"
        )
    if delivery.status != Delivery.Status.COMPLETE:
        raise InventoryError(
            "Delivery must be complete before posting receipts",
            code="delivery_not_complete",
        )
    if _delivery_receipts_already_posted(delivery_id):
        return list(
            StockMovement.objects.filter(
                source_type="delivery",
                source_id=str(delivery_id),
                kind=StockMovement.Kind.RECEIPT,
            ).order_by("id")
        )

    posted: list[StockMovement] = []
    for ln in delivery.lines.all():
        if ln.packs_received is None:
            continue
        if ln.note == DeliveryLine.NoteKind.REJECTED:
            continue
        si = ln.supplier_item
        if si is None or si.pack_qty is None or si.pack_qty <= 0:
            continue
        item = si.item
        if item is None:
            continue
        if item.default_area_id is None:
            # Partial catalogue: cannot place stock without an area — skip cleanly
            continue
        packs = Decimal(str(ln.packs_received))
        if packs == 0:
            continue
        qty_base = packs * Decimal(str(si.pack_qty))
        mov = apply_movement(
            item_id=item.pk,
            area_id=item.default_area_id,
            qty=qty_base,
            kind=StockMovement.Kind.RECEIPT,
            source_type="delivery",
            source_id=str(delivery_id),
            note=f"delivery_line={ln.pk} packs_received={packs}",
            occurred_at=timezone.now(),
        )
        posted.append(mov)
    return posted


@transaction.atomic
def apply_walk_variance(walk_id: int) -> int:
    """
    Snapshot theoretical + unexplained variance on counted (non-skipped) lines.

    Lifecycle: called on walk **submit** and **lock** (lock may skip submit).
    Counts are already collected at those points — no second walk.

    - theoretical_qty = StockBalance(item, area) or 0
    - gap = counted_base − theoretical
    - variance_qty = unexplained gap (0 if |gap| <= noise floor)
    - NEVER adjusts balances or pars
    """
    from walks.models import Walk, WalkLine

    walk = Walk.objects.select_for_update().filter(pk=walk_id).first()
    if walk is None:
        raise InventoryError(f"Walk {walk_id} not found", code="walk_not_found")

    lines = list(
        WalkLine.objects.select_for_update()
        .select_related("item")
        .filter(walk_id=walk_id)
    )
    updated = 0
    now = timezone.now()
    for ln in lines:
        if ln.skipped or ln.qty_base is None:
            # Leave theoretical/variance null for skipped / uncounted (B3)
            continue
        if ln.area_id is None:
            theoretical = Decimal("0")
        else:
            theoretical = get_balance_qty(ln.item_id, ln.area_id)
        counted = Decimal(str(ln.qty_base))
        gap = counted - theoretical
        floor = variance_noise_floor(ln.item)
        if abs(gap) <= floor:
            unexplained = Decimal("0")
        else:
            unexplained = gap
        ln.theoretical_qty = theoretical
        ln.variance_qty = unexplained
        ln.updated_at = now
        ln.save(update_fields=["theoretical_qty", "variance_qty", "updated_at"])
        updated += 1
    return updated


@transaction.atomic
def post_waste(
    *,
    item_id: int,
    area_id: int,
    qty: Decimal,
    note: str = "",
    occurred_at=None,
) -> StockMovement:
    """
    Human waste capture. `qty` is the positive amount wasted; stored as negative.
    """
    qty = Decimal(str(qty))
    if qty <= 0:
        raise InventoryError("Waste qty must be positive", code="invalid_qty")
    return apply_movement(
        item_id=item_id,
        area_id=area_id,
        qty=-qty,
        kind=StockMovement.Kind.WASTE,
        source_type="api_waste",
        source_id="",
        note=note or "",
        occurred_at=occurred_at,
    )


@transaction.atomic
def post_count_adjustment(
    *,
    item_id: int,
    area_id: int,
    qty: Decimal,
    note: str = "",
    occurred_at=None,
) -> StockMovement:
    """
    Explicit human compensating entry (signed qty). NOT automatic from variance.
    """
    qty = Decimal(str(qty))
    if qty == 0:
        raise InventoryError("Adjustment qty must be non-zero", code="zero_qty")
    return apply_movement(
        item_id=item_id,
        area_id=area_id,
        qty=qty,
        kind=StockMovement.Kind.COUNT_ADJUSTMENT,
        source_type="api_count_adjustment",
        source_id="",
        note=note or "",
        occurred_at=occurred_at,
    )


@transaction.atomic
def transfer_stock(
    *,
    item_id: int,
    from_area_id: int,
    to_area_id: int,
    qty: Decimal,
    note: str = "",
    occurred_at=None,
) -> tuple[StockMovement, StockMovement]:
    """Paired transfer_out + transfer_in in one atomic block."""
    qty = Decimal(str(qty))
    if qty <= 0:
        raise InventoryError("Transfer qty must be positive", code="invalid_qty")
    if from_area_id == to_area_id:
        raise InventoryError("from_area and to_area must differ", code="same_area")
    occurred_at = occurred_at or timezone.now()
    # Shared source_id for pairing
    import uuid

    pair_id = uuid.uuid4().hex[:16]
    out_m = apply_movement(
        item_id=item_id,
        area_id=from_area_id,
        qty=-qty,
        kind=StockMovement.Kind.TRANSFER_OUT,
        source_type="transfer",
        source_id=pair_id,
        note=note or "",
        occurred_at=occurred_at,
    )
    in_m = apply_movement(
        item_id=item_id,
        area_id=to_area_id,
        qty=qty,
        kind=StockMovement.Kind.TRANSFER_IN,
        source_type="transfer",
        source_id=pair_id,
        note=note or "",
        occurred_at=occurred_at,
    )
    return out_m, in_m


def list_balances(
    *,
    item_id: int | None = None,
    area_id: int | None = None,
    limit: int = 200,
) -> list[StockBalance]:
    qs = StockBalance.objects.select_related("item", "area").order_by(
        "item_id", "area_id"
    )
    if item_id is not None:
        qs = qs.filter(item_id=item_id)
    if area_id is not None:
        qs = qs.filter(area_id=area_id)
    return list(qs[: max(1, min(limit, 1000))])


def list_movements(
    *,
    item_id: int | None = None,
    area_id: int | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[StockMovement]:
    qs = StockMovement.objects.select_related("item", "area").order_by(
        "-occurred_at", "-id"
    )
    if item_id is not None:
        qs = qs.filter(item_id=item_id)
    if area_id is not None:
        qs = qs.filter(area_id=area_id)
    if kind:
        qs = qs.filter(kind=kind)
    return list(qs[: max(1, min(limit, 1000))])
