"""Unit tests for Phase 3 ledger arithmetic and append-only guards."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError
from django.test import TestCase, TransactionTestCase

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


class LedgerArithmeticTests(TestCase):
    def setUp(self):
        self.area = StorageArea.objects.create(
            name="phase3-test-area", kind=StorageArea.Kind.DRY
        )
        self.item = Item.objects.create(
            name="phase3-test-item",
            base_unit=Item.BaseUnit.EA,
            default_area=self.area,
            active=True,
        )

    def test_apply_movement_updates_balance_with_f(self):
        m1 = apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("10"),
            kind=StockMovement.Kind.RECEIPT,
            source_type="test",
            source_id="1",
        )
        self.assertTrue(m1.pk)
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("10"))

        apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("-3"),
            kind=StockMovement.Kind.WASTE,
            source_type="test",
            source_id="2",
        )
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("7"))

    def test_waste_and_adjustment_signs(self):
        apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("100"),
            kind=StockMovement.Kind.RECEIPT,
        )
        w = post_waste(
            item_id=self.item.pk, area_id=self.area.pk, qty=Decimal("4"), note="spoil"
        )
        self.assertEqual(w.qty, Decimal("-4"))
        self.assertEqual(w.kind, StockMovement.Kind.WASTE)
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("96"))

        a = post_count_adjustment(
            item_id=self.item.pk, area_id=self.area.pk, qty=Decimal("2"), note="found"
        )
        self.assertEqual(a.kind, StockMovement.Kind.COUNT_ADJUSTMENT)
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("98"))

    def test_transfer_paired(self):
        area2 = StorageArea.objects.create(
            name="phase3-test-area-2", kind=StorageArea.Kind.DRY
        )
        apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("20"),
            kind=StockMovement.Kind.RECEIPT,
        )
        out_m, in_m = transfer_stock(
            item_id=self.item.pk,
            from_area_id=self.area.pk,
            to_area_id=area2.pk,
            qty=Decimal("5"),
        )
        self.assertEqual(out_m.kind, StockMovement.Kind.TRANSFER_OUT)
        self.assertEqual(in_m.kind, StockMovement.Kind.TRANSFER_IN)
        self.assertEqual(out_m.source_id, in_m.source_id)
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("15"))
        self.assertEqual(get_balance_qty(self.item.pk, area2.pk), Decimal("5"))

    def test_movement_append_only_app_guard(self):
        m = apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("1"),
            kind=StockMovement.Kind.RECEIPT,
        )
        m.note = "mutate"
        with self.assertRaises(ValidationError):
            m.save()
        with self.assertRaises(ValidationError):
            m.delete()

    def test_variance_unexplained_noise_floor(self):
        apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("50"),
            kind=StockMovement.Kind.RECEIPT,
        )
        walk = start_walk(kind=Walk.Kind.STOCK, area_id=self.area.pk, notes="var-test")
        line = WalkLine.objects.filter(walk=walk, item=self.item).first()
        self.assertIsNotNone(line)
        line.counted_qty = Decimal("50.0005")
        line.qty_base = Decimal("50.0005")
        line.skipped = False
        line.save()
        n = apply_walk_variance(walk.pk)
        self.assertGreaterEqual(n, 1)
        line.refresh_from_db()
        self.assertEqual(line.theoretical_qty, Decimal("50"))
        self.assertEqual(line.variance_qty, Decimal("0"))
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("50"))

        line.qty_base = Decimal("40")
        line.counted_qty = Decimal("40")
        line.save()
        apply_walk_variance(walk.pk)
        line.refresh_from_db()
        self.assertEqual(line.theoretical_qty, Decimal("50"))
        self.assertEqual(line.variance_qty, Decimal("-10"))
        self.assertEqual(get_balance_qty(self.item.pk, self.area.pk), Decimal("50"))

    def test_noise_floor_default(self):
        self.assertEqual(variance_noise_floor(), Decimal("0.001"))


class LedgerTriggerTests(TransactionTestCase):
    def setUp(self):
        self.area = StorageArea.objects.create(
            name="phase3-trigger-area", kind=StorageArea.Kind.DRY
        )
        self.item = Item.objects.create(
            name="phase3-trigger-item",
            base_unit=Item.BaseUnit.EA,
            default_area=self.area,
            active=True,
        )

    def test_movement_append_only_pg_trigger(self):
        m = apply_movement(
            item_id=self.item.pk,
            area_id=self.area.pk,
            qty=Decimal("1"),
            kind=StockMovement.Kind.RECEIPT,
        )
        with self.assertRaises((InternalError, ProgrammingError)):
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE inventory_stockmovement SET note = %s WHERE id = %s",
                    ["hacked", m.pk],
                )
