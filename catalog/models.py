"""
Catalogue domain (Phase 1).

Items are global (never section-scoped). Par is never f(covers).
Partial catalogue is normal: missing supplier/par/price must flow cleanly.
B11: ParLevel UniqueConstraint nulls_distinct=False (PG 17.10).
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class StorageArea(models.Model):
    class Kind(models.TextChoices):
        WALKIN = "walkin", "Walk-in"
        FREEZER = "freezer", "Freezer"
        DRY = "dry", "Dry"
        BAR = "bar", "Bar"
        SECTION = "section", "Section"

    name = models.CharField(max_length=128, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    # walk_order NOT yet known — leave null/orderable; do not guess
    walk_order = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = [models.F("walk_order").asc(nulls_last=True), "name"]

    def __str__(self) -> str:
        return self.name


class Item(models.Model):
    class BaseUnit(models.TextChoices):
        G = "g", "g"
        ML = "ml", "ml"
        EA = "ea", "ea"

    code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional internal code. Name+unit is enough to exist.",
    )
    name = models.CharField(max_length=255, unique=True)
    base_unit = models.CharField(
        max_length=4,
        choices=BaseUnit.choices,
        default=BaseUnit.EA,
    )
    category = models.CharField(max_length=128, blank=True, default="")
    default_area = models.ForeignKey(
        StorageArea,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_items",
    )
    walk_order = models.PositiveIntegerField(null=True, blank=True)
    allergens = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
    )
    active = models.BooleanField(default=True)
    unverified = models.BooleanField(
        default=False,
        help_text="True when source notes say verify/uncertain — never silent.",
    )
    house_made = models.BooleanField(
        default=False,
        help_text="True when prep is made in-house (recipe-lite via ItemComponent). "
        "Not a replacement for bought SupplierItems.",
    )
    # D12: short free-text note (board payload); not a journal
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(base_unit__in=["g", "ml", "ea"]),
                name="item_base_unit_g_ml_ea",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.base_unit not in {c.value for c in self.BaseUnit}:
            raise ValidationError({"base_unit": "base_unit must be g, ml, or ea"})
        if self.notes is not None and len(self.notes) > 500:
            raise ValidationError({"notes": "notes max_length is 500"})


class ItemComponent(models.Model):
    """
    Recipe-lite component link (D12). Not full B15 explosion.
    parent Item ← component Item; deep cycle detection deferred to Phase 5.
    """

    parent = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="components",
    )
    component = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="used_in",
    )
    qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Rough qty in component base units when known; null = unverified/unknown.",
    )
    unit = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Prefer component base_unit when set.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["parent_id", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "component"],
                name="uniq_itemcomponent_parent_component",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("component")),
                name="itemcomponent_no_self_ref",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent_id}→{self.component_id}"

    def clean(self) -> None:
        if self.parent_id and self.component_id and self.parent_id == self.component_id:
            raise ValidationError(
                {"component": "component cannot be the same item as parent"}
            )
        if self.notes is not None and len(self.notes) > 500:
            raise ValidationError({"notes": "notes max_length is 500"})


class UnitConversion(models.Model):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="conversions",
    )
    unit = models.CharField(max_length=32)
    factor_to_base = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        help_text="Multiply pack qty by this to get base units (g|ml|ea).",
    )
    countable = models.BooleanField(
        default=True,
        help_text="False for continuous measures that are not pack-counted.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "unit"],
                name="uniq_unitconversion_item_unit",
            ),
            models.CheckConstraint(
                condition=~models.Q(factor_to_base=0),
                name="unitconversion_factor_nonzero",
            ),
        ]
        ordering = ["item_id", "unit"]

    def __str__(self) -> str:
        return f"{self.item_id}:{self.unit}→{self.factor_to_base}"

    def clean(self) -> None:
        if self.factor_to_base is not None and self.factor_to_base == 0:
            raise ValidationError({"factor_to_base": "factor_to_base must be non-zero"})


class Supplier(models.Model):
    name = models.CharField(max_length=128, unique=True)
    account_code = models.CharField(max_length=64, blank=True, default="")
    order_days = ArrayField(
        models.IntegerField(),
        default=list,
        blank=True,
        help_text="ISO weekday ints 0=Mon .. 6=Sun (empty = unknown).",
    )
    cutoff_time = models.TimeField(null=True, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(default=1)
    min_order_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    contact = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SupplierItem(models.Model):
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="supplier_items",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="supplier_items",
    )
    supplier_code = models.CharField(max_length=128, blank=True, default="")
    pack_description = models.CharField(max_length=255, blank=True, default="")
    pack_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Pack size in item base units. Null until known — never invent.",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Nullable. Prices last; never invent.",
    )
    preferred = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    unverified = models.BooleanField(
        default=False,
        help_text="True when code/supplier from sheet needs verify.",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "item"],
                name="uniq_supplieritem_supplier_item",
            ),
        ]
        ordering = ["supplier_id", "item_id"]

    def __str__(self) -> str:
        code = self.supplier_code or "—"
        return f"{self.supplier} / {self.item} ({code})"


class ParLevel(models.Model):
    """
    Par = throughput + storage + delivery cadence — never f(covers).
    weekday null = default for all days. B11: nulls_distinct=False.
    """

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="par_levels",
    )
    area = models.ForeignKey(
        StorageArea,
        on_delete=models.CASCADE,
        related_name="par_levels",
    )
    weekday = models.SmallIntegerField(
        null=True,
        blank=True,
        help_text="0=Mon .. 6=Sun; null = all-days default.",
    )
    qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        default=Decimal("0"),
        help_text="Par quantity in item base units.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "area", "weekday"],
                name="uniq_parlevel_item_area_weekday",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(weekday__isnull=True)
                | models.Q(weekday__gte=0, weekday__lte=6),
                name="parlevel_weekday_range",
            ),
        ]
        ordering = ["item_id", "area_id", "weekday"]

    def __str__(self) -> str:
        wd = "all" if self.weekday is None else str(self.weekday)
        return f"par {self.item_id}@{self.area_id} d={wd} qty={self.qty}"


class CatalogIngestUpload(models.Model):
    """Photo/text/csv upload → django-q2 → Mistral → proposal rows → accept."""

    class SourceKind(models.TextChoices):
        TEXT = "text", "Text"
        PHOTO = "photo", "Photo"
        CSV = "csv", "CSV"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        REVIEW = "review", "Ready for review"
        FAILED = "failed", "Failed"
        DONE = "done", "Done"

    created_at = models.DateTimeField(default=timezone.now)
    source_kind = models.CharField(
        max_length=16,
        choices=SourceKind.choices,
        default=SourceKind.TEXT,
    )
    raw_text = models.TextField(blank=True, default="")
    image = models.FileField(
        upload_to="catalog_ingest/%Y/%m/",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error = models.TextField(blank=True, default="")
    q_task_id = models.CharField(max_length=64, blank=True, default="")
    model_name = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ingest#{self.pk} {self.status}"


class CatalogIngestProposal(models.Model):
    """
    LLM/extractor proposal only — never domain state until accept handler runs.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    upload = models.ForeignKey(
        CatalogIngestUpload,
        on_delete=models.CASCADE,
        related_name="proposals",
    )
    dish = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255)
    base_unit = models.CharField(max_length=4, blank=True, default="ea")
    supplier_name = models.CharField(max_length=128, blank=True, default="")
    supplier_code = models.CharField(max_length=128, blank=True, default="")
    pack_description = models.CharField(max_length=255, blank=True, default="")
    pack_qty = models.DecimalField(
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
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    flagged_low_confidence = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    raw = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    result_item = models.ForeignKey(
        Item,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    result_supplier_item = models.ForeignKey(
        SupplierItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["upload_id", "id"]

    def __str__(self) -> str:
        return f"proposal#{self.pk} {self.name} [{self.status}]"
