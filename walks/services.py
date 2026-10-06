"""
Walk business rules (Phase 2).

Routers orchestrate; models validate; services write domain state.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.utils import timezone

from catalog.models import Item, ParLevel, StorageArea, UnitConversion
from walks.models import Walk, WalkLine


class WalkError(Exception):
    def __init__(self, message: str, code: str = "walk_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _item_qs_for_area(area: StorageArea | None):
    """
    Active items for walk generation.
    - area set: default_area=area OR has ParLevel in that area
    - area null: all active items (line.area = default_area or first par area)
    Does not invent walk_order — nulls sort last.
    """
    qs = Item.objects.filter(active=True)
    if area is not None:
        qs = qs.filter(
            Q(default_area_id=area.pk) | Q(par_levels__area_id=area.pk)
        ).distinct()
    return qs.select_related("default_area")


def _line_area_for_item(item: Item, walk_area: StorageArea | None) -> StorageArea | None:
    if walk_area is not None:
        return walk_area
    if item.default_area_id:
        return item.default_area
    # Prefer any par area if present (deterministic by area id)
    par = (
        ParLevel.objects.filter(item_id=item.pk)
        .select_related("area")
        .order_by("area_id")
        .first()
    )
    return par.area if par else None


def _sort_key_item(item: Item) -> tuple:
    area = item.default_area
    area_wo = area.walk_order if area and area.walk_order is not None else 10**9
    area_name = area.name if area else ""
    item_wo = item.walk_order if item.walk_order is not None else 10**9
    return (area_wo, area_name, item_wo, item.name.lower(), item.pk)


@transaction.atomic
def start_walk(
    *,
    kind: str = Walk.Kind.ORDER,
    area_id: int | None = None,
    notes: str = "",
) -> Walk:
    valid_kinds = {c.value for c in Walk.Kind}
    if kind not in valid_kinds:
        raise WalkError(f"Invalid walk kind: {kind}", code="invalid_kind")

    area = None
    if area_id is not None:
        try:
            area = StorageArea.objects.get(pk=area_id, active=True)
        except StorageArea.DoesNotExist as exc:
            raise WalkError(f"Area {area_id} not found", code="area_not_found") from exc

    walk = Walk.objects.create(
        kind=kind,
        area=area,
        started_at=timezone.now(),
        status=Walk.Status.DRAFT,
        notes=notes or "",
    )

    items = list(_item_qs_for_area(area))
    items.sort(key=_sort_key_item)

    bulk: list[WalkLine] = []
    seen: set[tuple[int, int | None]] = set()
    sort_order = 0
    for item in items:
        line_area = _line_area_for_item(item, area)
        key = (item.pk, line_area.pk if line_area else None)
        if key in seen:
            continue
        seen.add(key)
        bulk.append(
            WalkLine(
                walk=walk,
                item=item,
                area=line_area,
                counted_qty=None,
                counted_unit="",
                qty_base=None,
                skipped=False,
                sort_order=sort_order,
                updated_at=timezone.now(),
            )
        )
        sort_order += 1

    if bulk:
        WalkLine.objects.bulk_create(bulk)

    return walk


def walk_queryset(walk_id: int) -> Walk:
    try:
        return (
            Walk.objects.select_related("area")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=WalkLine.objects.select_related(
                        "item", "area", "item__default_area"
                    ).order_by("sort_order", "id"),
                )
            )
            .get(pk=walk_id)
        )
    except Walk.DoesNotExist as exc:
        raise WalkError(f"Walk {walk_id} not found", code="walk_not_found") from exc


def _to_base(item: Item, qty: Decimal | None, unit: str | None) -> Decimal | None:
    if qty is None:
        return None
    u = (unit or "").strip()
    if not u or u == item.base_unit:
        return qty
    conv = (
        UnitConversion.objects.filter(item_id=item.pk, unit__iexact=u)
        .only("factor_to_base")
        .first()
    )
    if conv is None:
        raise WalkError(
            f"No UnitConversion for item {item.pk} unit={u!r}",
            code="unknown_unit",
        )
    return qty * conv.factor_to_base


@transaction.atomic
def batch_submit_lines(walk_id: int, lines: list[dict[str, Any]]) -> Walk:
    """
    Idempotent upsert on (walk_id, item_id, area_id).
    B3: counted_qty null/omitted with skipped true or blank → skipped, null qty.
         counted_qty=0 → empty shelf, not skipped.
    Double submit from a phone that lost signal is normal (overwrite).
    """
    try:
        walk = Walk.objects.select_for_update().get(pk=walk_id)
    except Walk.DoesNotExist as exc:
        raise WalkError(f"Walk {walk_id} not found", code="walk_not_found") from exc
    if walk.status == Walk.Status.LOCKED:
        raise WalkError("Walk is locked", code="walk_locked")

    existing = {
        (ln.item_id, ln.area_id): ln
        for ln in WalkLine.objects.select_for_update()
        .select_related("item")
        .filter(walk_id=walk_id)
    }
    # Secondary index: single line per item (when area omitted)
    by_item: dict[int, list[WalkLine]] = {}
    for ln in existing.values():
        by_item.setdefault(ln.item_id, []).append(ln)

    now = timezone.now()
    for raw in lines:
        item_id = raw.get("item_id")
        if item_id is None:
            raise WalkError("item_id required on each line", code="invalid_line")
        item_id = int(item_id)
        area_id = raw.get("area_id", None)
        if area_id is not None:
            area_id = int(area_id)

        line = None
        line_id = raw.get("line_id")
        if line_id is not None:
            line = next((ln for ln in existing.values() if ln.pk == int(line_id)), None)
            if line is None:
                raise WalkError(f"line_id {line_id} not on walk", code="line_not_found")
        elif "area_id" in raw:
            # Explicit area (including null): exact key only — never steal another area's line
            line = existing.get((item_id, area_id))
        else:
            candidates = by_item.get(item_id) or []
            if len(candidates) == 1:
                line = candidates[0]
            elif len(candidates) == 0:
                line = None
            else:
                raise WalkError(
                    f"item_id {item_id} has multiple areas on this walk — send area_id",
                    code="ambiguous_item_area",
                )

        # B3 blank → skip
        skipped = bool(raw.get("skipped", False))
        counted_raw = raw.get("counted_qty", None)
        if "counted_qty" in raw and (counted_raw is None or counted_raw == ""):
            skipped = True
            counted_raw = None
        if skipped and counted_raw is None:
            counted_qty = None
        elif counted_raw is None and not skipped:
            # omit counted without skip flag → treat as no-op on qty if line exists
            counted_qty = line.counted_qty if line else None
        else:
            counted_qty = Decimal(str(counted_raw)) if counted_raw is not None else None
            if counted_qty is not None:
                skipped = False

        counted_unit = raw.get("counted_unit")
        if counted_unit is None:
            counted_unit = line.counted_unit if line else ""
        counted_unit = counted_unit or ""

        note = raw.get("note")
        if note is None:
            note = line.note if line else ""
        planned = raw.get("planned_order_qty", ...)
        proposed = raw.get("proposed_order_qty", ...)

        if line is None:
            try:
                item = Item.objects.get(pk=item_id, active=True)
            except Item.DoesNotExist as exc:
                raise WalkError(f"item {item_id} not found", code="item_not_found") from exc
            area_obj = None
            if area_id is not None:
                try:
                    area_obj = StorageArea.objects.get(pk=area_id)
                except StorageArea.DoesNotExist as exc:
                    raise WalkError(f"area {area_id} not found", code="area_not_found") from exc
            else:
                area_obj = item.default_area
            qty_base = _to_base(item, counted_qty, counted_unit) if not skipped else None
            line = WalkLine(
                walk=walk,
                item=item,
                area=area_obj,
                sort_order=WalkLine.objects.filter(walk=walk).count(),
            )
            existing[(item.pk, area_obj.pk if area_obj else None)] = line
            by_item.setdefault(item.pk, []).append(line)
        else:
            item = line.item
            if skipped:
                qty_base = None
                counted_qty = None
            else:
                qty_base = _to_base(item, counted_qty, counted_unit)

        line.counted_qty = counted_qty
        line.counted_unit = counted_unit
        line.qty_base = qty_base
        line.skipped = skipped
        line.note = note or ""
        if planned is not ...:
            line.planned_order_qty = (
                Decimal(str(planned)) if planned is not None and planned != "" else None
            )
        if proposed is not ...:
            line.proposed_order_qty = (
                Decimal(str(proposed)) if proposed is not None and proposed != "" else None
            )
        line.updated_at = now
        line.save()

    return walk_queryset(walk_id)


@transaction.atomic
def submit_walk(walk_id: int) -> Walk:
    walk = Walk.objects.select_for_update().filter(pk=walk_id).first()
    if walk is None:
        raise WalkError(f"Walk {walk_id} not found", code="walk_not_found")
    if walk.status == Walk.Status.LOCKED:
        raise WalkError("Walk is locked", code="walk_locked")
    walk.status = Walk.Status.SUBMITTED
    walk.submitted_at = timezone.now()
    walk.save(update_fields=["status", "submitted_at"])
    # Phase 3: snapshot theoretical + unexplained variance from ledger balances.
    # Does not rewrite balances (D13). Counts already on lines — no second walk.
    from inventory.services import apply_walk_variance

    apply_walk_variance(walk_id)
    # D15.1 soft assist card from shortfall (no PO write here)
    try:
        from planning.d15_depth import ensure_order_suggest_from_walk

        ensure_order_suggest_from_walk(walk_id=walk_id, service_date=timezone.localdate())
    except Exception:  # noqa: BLE001
        pass
    return walk_queryset(walk_id)


@transaction.atomic
def lock_walk(walk_id: int) -> Walk:
    walk = Walk.objects.select_for_update().filter(pk=walk_id).first()
    if walk is None:
        raise WalkError(f"Walk {walk_id} not found", code="walk_not_found")
    if walk.status == Walk.Status.LOCKED:
        return walk_queryset(walk_id)
    now = timezone.now()
    if walk.submitted_at is None:
        walk.submitted_at = now
    walk.status = Walk.Status.LOCKED
    walk.locked_at = now
    walk.save(update_fields=["status", "submitted_at", "locked_at"])
    # Re-snapshot if locking from draft or after further edits post-submit.
    from inventory.services import apply_walk_variance

    apply_walk_variance(walk_id)
    return walk_queryset(walk_id)


def par_for(item_id: int, area_id: int | None, weekday: int | None) -> Decimal | None:
    """Weekday-specific par first, then all-days (weekday null)."""
    if area_id is None:
        return None
    qs = ParLevel.objects.filter(item_id=item_id, area_id=area_id)
    if weekday is not None:
        row = qs.filter(weekday=weekday).first()
        if row is not None:
            return row.qty
    row = qs.filter(weekday__isnull=True).first()
    return row.qty if row else None
