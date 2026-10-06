#!/usr/bin/env python3
"""Live-DB unit smoke for Phase 3 ledger (no test DB create permission)."""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError

from catalog.models import Item, StorageArea
from inventory.models import StockMovement
from inventory.services import (
    apply_movement,
    apply_walk_variance,
    get_balance_qty,
    post_count_adjustment,
    post_waste,
    transfer_stock,
    variance_noise_floor,
)
from walks.models import Walk, WalkLine
from walks.services import start_walk


def main() -> int:
    assert variance_noise_floor() == Decimal("0.001")
    area, _ = StorageArea.objects.get_or_create(
        name="phase3-unit-area",
        defaults={"kind": StorageArea.Kind.DRY, "active": True},
    )
    area2, _ = StorageArea.objects.get_or_create(
        name="phase3-unit-area-2",
        defaults={"kind": StorageArea.Kind.DRY, "active": True},
    )
    item, _ = Item.objects.get_or_create(
        name="phase3-unit-item",
        defaults={
            "base_unit": Item.BaseUnit.EA,
            "default_area": area,
            "active": True,
        },
    )
    if item.default_area_id != area.pk:
        item.default_area = area
        item.save(update_fields=["default_area"])

    start = get_balance_qty(item.pk, area.pk)
    apply_movement(
        item_id=item.pk,
        area_id=area.pk,
        qty=Decimal("10"),
        kind=StockMovement.Kind.RECEIPT,
        source_type="unit",
        source_id="a",
    )
    assert get_balance_qty(item.pk, area.pk) == start + 10
    w = post_waste(item_id=item.pk, area_id=area.pk, qty=Decimal("3"), note="u")
    assert w.qty == Decimal("-3")
    assert get_balance_qty(item.pk, area.pk) == start + 7
    post_count_adjustment(item_id=item.pk, area_id=area.pk, qty=Decimal("1"), note="u")
    assert get_balance_qty(item.pk, area.pk) == start + 8
    out_m, in_m = transfer_stock(
        item_id=item.pk,
        from_area_id=area.pk,
        to_area_id=area2.pk,
        qty=Decimal("2"),
    )
    assert out_m.source_id == in_m.source_id
    assert get_balance_qty(item.pk, area.pk) == start + 6

    m = StockMovement.objects.filter(item=item).order_by("-id").first()
    assert m is not None
    try:
        m.note = "x"
        m.save()
        raise SystemExit("app update should fail")
    except ValidationError:
        pass
    try:
        m.delete()
        raise SystemExit("app delete should fail")
    except ValidationError:
        pass
    try:
        with connection.cursor() as c:
            c.execute(
                "UPDATE inventory_stockmovement SET note=%s WHERE id=%s",
                ["h", m.pk],
            )
        raise SystemExit("db update should fail")
    except (InternalError, ProgrammingError):
        transaction.rollback()

    bal = get_balance_qty(item.pk, area.pk)
    walk = start_walk(kind=Walk.Kind.STOCK, area_id=area.pk, notes="unit")
    line = WalkLine.objects.filter(walk=walk, item=item, area=area).first()
    assert line is not None
    line.qty_base = bal - Decimal("5")
    line.counted_qty = line.qty_base
    line.skipped = False
    line.save()
    apply_walk_variance(walk.pk)
    line.refresh_from_db()
    assert line.theoretical_qty == bal, (line.theoretical_qty, bal)
    assert line.variance_qty == Decimal("-5"), line.variance_qty
    assert get_balance_qty(item.pk, area.pk) == bal
    print("UNIT_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
