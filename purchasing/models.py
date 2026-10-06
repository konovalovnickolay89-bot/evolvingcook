"""
Purchasing domain (Phase 2 + D13 scope).

PO: draft → sent → confirmed → received → closed.
Delivery complete → inventory receipt movements (Phase 3).

D13: scope=replenishment|event. Only replenishment open qty counts as on_order.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        CONFIRMED = "confirmed", "Confirmed"
        RECEIVED = "received", "Received"
        CLOSED = "closed", "Closed"

    class Scope(models.TextChoices):
        REPLENISHMENT = "replenishment", "Replenishment"
        EVENT = "event", "Event"

    supplier = models.ForeignKey(
        "catalog.Supplier",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    walk = models.ForeignKey(
        "walks.Walk",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    order_date = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    scope = models.CharField(
        max_length=16,
        choices=Scope.choices,
        default=Scope.REPLENISHMENT,
        db_index=True,
        help_text=(
            "replenishment (default): standing top-up; counts toward on_order. "
            "event: banquet/one-off; never reduces replenishment shortfall."
        ),
    )
    total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-order_date", "-id"]

    def __str__(self) -> str:
        return f"PO#{self.pk} {self.supplier_id} [{self.status}/{self.scope}]"


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    supplier_item = models.ForeignKey(
        "catalog.SupplierItem",
        on_delete=models.PROTECT,
        related_name="po_lines",
    )
    proposed_packs = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="System ceil(shortfall/pack_qty); never binding.",
    )
    packs = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Mykola's packs (defaults to proposed).",
    )
    qty_base = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="packs * pack_qty in item base units.",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )
    # Breakdown snapshot at proposal time (base units)
    par = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    counted = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    on_order = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    shortfall = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "supplier_item"],
                name="uniq_poline_po_supplier_item",
            ),
        ]

    def __str__(self) -> str:
        return f"POline#{self.pk} po={self.purchase_order_id}"


class Delivery(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETE = "complete", "Complete"

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    supplier = models.ForeignKey(
        "catalog.Supplier",
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    received_on = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-received_on", "-id"]
        verbose_name_plural = "deliveries"

    def __str__(self) -> str:
        return f"delivery#{self.pk} po={self.purchase_order_id}"


class DeliveryLine(models.Model):
    class NoteKind(models.TextChoices):
        SHORT = "short", "Short"
        OVER = "over", "Over"
        SUBSTITUTED = "substituted", "Substituted"
        REJECTED = "rejected", "Rejected"
        OK = "ok", "OK"

    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    supplier_item = models.ForeignKey(
        "catalog.SupplierItem",
        on_delete=models.PROTECT,
        related_name="delivery_lines",
    )
    packs_expected = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    packs_received = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )
    note = models.CharField(
        max_length=16,
        choices=NoteKind.choices,
        blank=True,
        default="",
        help_text="short|over|substituted|rejected|ok",
    )
    note_text = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "supplier_item"],
                name="uniq_deliveryline_delivery_supplier_item",
            ),
        ]

    def __str__(self) -> str:
        return f"dline#{self.pk} delivery={self.delivery_id}"
