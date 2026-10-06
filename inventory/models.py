"""
Inventory domain — Phase 3 stock ledger.

Append-only StockMovement + StockBalance (B10, B12).
D13 / Phase 3 variance language:
- counted − theoretical gap = **unexplained** (never "error")
- per-item / default noise floor; below floor → zero unexplained
- variance never auto-corrects pars or balances
- corrections = human-driven compensating movements only
- no global / multi-outlet / hotel-wide inventory ambitions
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class StockMovement(models.Model):
    """Append-only ledger row. Corrections = compensating entries only (B10)."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        CONSUME = "consume", "Consume"
        YIELD = "yield", "Yield"
        WASTE = "waste", "Waste"
        TRANSFER_IN = "transfer_in", "Transfer in"
        TRANSFER_OUT = "transfer_out", "Transfer out"
        COUNT_ADJUSTMENT = "count_adjustment", "Count adjustment"

    item = models.ForeignKey(
        "catalog.Item",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    area = models.ForeignKey(
        "catalog.StorageArea",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        help_text="SIGNED base-unit delta. Receipt/yield/transfer_in usually +; "
        "waste/consume/transfer_out usually −; count_adjustment either sign.",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    source_type = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="e.g. delivery, walk, api_waste, api_count_adjustment, transfer",
    )
    source_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Stringified source pk or composite key for idempotency.",
    )
    # B4: overridable default — not auto_now_add
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["item", "area", "-occurred_at"]),
            models.Index(fields=["source_type", "source_id"]),
        ]

    def __str__(self) -> str:
        return f"mov#{self.pk} {self.kind} item={self.item_id} qty={self.qty}"

    def save(self, *args, **kwargs):
        # B10 app-level guard: no updates to existing rows
        if self.pk is not None and StockMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "StockMovement is append-only; corrections must be compensating entries."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "StockMovement is append-only; deletions are not allowed."
        )


class StockBalance(models.Model):
    """
    On-hand qty per (item, area). Written only in the same transaction as a
    StockMovement via F() expressions (B12) — never hand-set via API/admin.
    """

    item = models.ForeignKey(
        "catalog.Item",
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    area = models.ForeignKey(
        "catalog.StorageArea",
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    qty = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal("0"))
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["item_id", "area_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "area"],
                name="uniq_stockbalance_item_area",
            ),
        ]

    def __str__(self) -> str:
        return f"bal item={self.item_id} area={self.area_id} qty={self.qty}"
