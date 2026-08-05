"""
Walk domain (Phase 2).

Walk lifecycle: draft → submitted → locked.
Lines generated at start by area, ordered by walk_order (nulls last — do not invent).
B3: skipped=True / null qty ≠ typed 0 (empty shelf).

Phase 3 (D13): theoretical_qty / variance_qty filled on submit and lock via
inventory.services.apply_walk_variance — gap labelled **unexplained** (never "error");
noise floor zeros small gaps; variance never auto-corrects pars/balances.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone


class Walk(models.Model):
    class Kind(models.TextChoices):
        ORDER = "order", "Order"
        STOCK = "stock", "Stock"
        BOTH = "both", "Both"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        LOCKED = "locked", "Locked"

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.ORDER)
    area = models.ForeignKey(
        "catalog.StorageArea",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="walks",
        help_text="Null = all areas (items by default_area / par presence).",
    )
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"walk#{self.pk} {self.kind} [{self.status}]"


class WalkLine(models.Model):
    """
    One count row. Same item may appear in multiple areas (unique walk+item+area).
    Batch upsert is idempotent on (walk_id, item_id, area_id).
    """

    walk = models.ForeignKey(Walk, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(
        "catalog.Item",
        on_delete=models.PROTECT,
        related_name="walk_lines",
    )
    area = models.ForeignKey(
        "catalog.StorageArea",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="walk_lines",
    )
    counted_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="As entered. Null when skipped (B3). 0 = empty shelf.",
    )
    counted_unit = models.CharField(max_length=32, blank=True, default="")
    qty_base = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="counted_qty converted to item base unit.",
    )
    proposed_order_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="System shortfall snapshot (base units); never binding.",
    )
    planned_order_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Mykola's order qty (base units); the only binding number.",
    )
    # Phase 3 — set on submit/lock from StockBalance (D13: unexplained, never "error")
    theoretical_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Theoretical on-hand from ledger balance at submit/lock (0 if none).",
    )
    variance_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Unexplained gap (counted − theoretical) after noise floor; "
            "never labelled error; never auto-corrects pars/balances."
        ),
    )
    skipped = models.BooleanField(
        default=False,
        help_text="True when blank count — skip ≠ 0.",
    )
    note = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["walk", "item", "area"],
                name="uniq_walkline_walk_item_area",
                nulls_distinct=False,
            ),
        ]

    def __str__(self) -> str:
        return f"walkline#{self.pk} walk={self.walk_id} item={self.item_id}"
