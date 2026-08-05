"""
Planning domain (Phase 1.5 MEP/service boards).

Real schema per BACKEND_BUILD_INSTRUCTIONS §5 — no throwaways.
Covers nullable; never required to open a board (Phase 4 lock).
check lines: actual_qty stays null (no progress bar).
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ServiceSectionCode(models.TextChoices):
    """Locked section enum — lounge is outlet of ALC later, not a peer."""

    BREAKFAST_BUFFET = "breakfast_buffet", "Breakfast buffet"
    A_LA_CARTE = "a_la_carte", "A la carte"
    BANQUET_BUFFET = "banquet_buffet", "Banquet buffet"
    BANQUETING = "banqueting", "Banqueting"
    CANTEEN = "canteen", "Canteen"
    SKYBAR = "skybar", "Skybar"


class ServiceDay(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    service_date = models.DateField(unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    occupancy_rooms = models.PositiveIntegerField(null=True, blank=True)
    occupancy_guests = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Phase 4: snapshot of actuals / section summaries at close (no throwaway table)
    outturn = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-service_date"]
        verbose_name_plural = "service days"

    def __str__(self) -> str:
        return f"{self.service_date} [{self.status}]"


class ServiceSection(models.Model):
    class CoversSource(models.TextChoices):
        OCCUPANCY = "occupancy", "Occupancy"
        BOOKED = "booked", "Booked"
        BEO = "beo", "BEO"
        FORECAST = "forecast", "Forecast"
        MANUAL = "manual", "Manual"

    service_day = models.ForeignKey(
        ServiceDay,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    section = models.CharField(
        max_length=32,
        choices=ServiceSectionCode.choices,
        db_index=True,
    )
    active = models.BooleanField(default=True)
    # Nullable: covers never required to open a board
    covers = models.PositiveIntegerField(null=True, blank=True)
    covers_source = models.CharField(
        max_length=16,
        choices=CoversSource.choices,
        blank=True,
        default="",
    )
    notes = models.TextField(blank=True, default="")
    # Optional BEO event breakdown for banquet*: [{name, covers}, ...]
    beo_events = models.JSONField(default=list, blank=True)
    # Phase 4 section outturn slice captured at day close (or partial updates)
    outturn = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service_day", "section"],
                name="uniq_servicesection_day_section",
            ),
        ]
        ordering = ["service_day_id", "section"]

    def __str__(self) -> str:
        return f"{self.service_day.service_date}:{self.section}"


class DishTemplate(models.Model):
    """
    Seeded dish template for board line generation.
    Not a throwaway — source=template on ProductionLine points here by name match.
    """

    class Mode(models.TextChoices):
        PRODUCE = "produce", "Produce"
        REPLENISH = "replenish", "Replenish"
        CHECK = "check", "Check"

    class Kind(models.TextChoices):
        DISH = "dish", "Dish"
        SAUCE = "sauce", "Sauce"
        PREP = "prep", "Prep"
        STOCK = "stock", "Stock"
        BUFFET = "buffet", "Buffet"
        SERVICE = "service", "Service"

    section = models.CharField(
        max_length=32,
        choices=ServiceSectionCode.choices,
        db_index=True,
    )
    name = models.CharField(max_length=255)
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.CHECK,
    )
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.DISH,
    )
    category = models.CharField(max_length=128, blank=True, default="")
    unit = models.CharField(max_length=16, blank=True, default="ea")
    par_level = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    supports_lounge = models.BooleanField(default=False)
    active = models.BooleanField(
        default=True,
        help_text="False = off-menu; keep template + items, skip board generation.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default="")
    # Optional catalogue dish item (rare); components link ingredients
    item = models.ForeignKey(
        "catalog.Item",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dish_templates",
    )
    # Phase 4 banquet produce scaling only — never invent; null → proposed stays null
    yield_per_cover = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Optional per-cover yield for produce scaling (banquet*). Null = no auto proposed_qty.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["section", "name"],
                name="uniq_dishtemplate_section_name",
            ),
        ]
        ordering = ["section", "sort_order", "name"]

    def __str__(self) -> str:
        flag = "" if self.active else " [inactive]"
        return f"{self.section}:{self.name}{flag}"


class DishTemplateComponent(models.Model):
    template = models.ForeignKey(
        DishTemplate,
        on_delete=models.CASCADE,
        related_name="components",
    )
    item = models.ForeignKey(
        "catalog.Item",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dish_template_components",
    )
    supplier_item = models.ForeignKey(
        "catalog.SupplierItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name when item FK missing.",
    )
    planned_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    unit = models.CharField(max_length=16, blank=True, default="ea")
    sort_order = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["template_id", "sort_order", "id"]

    def __str__(self) -> str:
        label = self.name or (self.item.name if self.item_id else "?")
        return f"{self.template_id}:{label}"


class ProductionLine(models.Model):
    class Mode(models.TextChoices):
        PRODUCE = "produce", "Produce"
        REPLENISH = "replenish", "Replenish"
        CHECK = "check", "Check"

    class Kind(models.TextChoices):
        DISH = "dish", "Dish"
        SAUCE = "sauce", "Sauce"
        PREP = "prep", "Prep"
        STOCK = "stock", "Stock"
        BUFFET = "buffet", "Buffet"
        SERVICE = "service", "Service"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        PREP = "prep", "Prep"
        READY = "ready", "Ready"
        SERVED = "served", "Served"
        HELD = "held", "Held"
        EIGHTY_SIX = "eighty_six", "86"

    class Source(models.TextChoices):
        MENU = "menu", "Menu"
        TEMPLATE = "template", "Template"
        MANUAL = "manual", "Manual"
        ASSIST = "assist", "Assist"

    service_section = models.ForeignKey(
        ServiceSection,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        "catalog.Item",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="production_lines",
        help_text="Nullable — quick-add and partial catalogue OK.",
    )
    name = models.CharField(max_length=255)
    mode = models.CharField(max_length=16, choices=Mode.choices, db_index=True)
    kind = models.CharField(
        max_length=16,
        choices=Kind.choices,
        default=Kind.DISH,
    )
    category = models.CharField(max_length=128, blank=True, default="")
    unit = models.CharField(max_length=16, blank=True, default="ea")
    proposed_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    planned_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    # check mode: always null — no meaningful actual qty / no FE progress bar
    actual_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Null for mode=check (explicit: no progress bar).",
    )
    par_level = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PLANNED,
        db_index=True,
    )
    supports_lounge = models.BooleanField(default=False)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    # D12: short free-text note (included in board payload); not a journal
    notes = models.CharField(max_length=500, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    template = models.ForeignKey(
        DishTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lines",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service_section_id", "sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(mode="check", actual_qty__isnull=True)
                    | ~models.Q(mode="check")
                ),
                name="productionline_check_actual_null",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.mode}/{self.status}]"

    def clean(self) -> None:
        if self.mode == self.Mode.CHECK and self.actual_qty is not None:
            raise ValidationError(
                {"actual_qty": "check lines must keep actual_qty null"}
            )
        if self.source == self.Source.MANUAL and not (self.name or "").strip():
            raise ValidationError({"name": "name required for ad-hoc/manual lines"})
        if self.notes is not None and len(self.notes) > 500:
            raise ValidationError({"notes": "notes max_length is 500"})

    @property
    def ticked(self) -> bool:
        """Board tick = ready (check confirmed) or eighty_six."""
        return self.status in {self.Status.READY, self.Status.EIGHTY_SIX}


class LineComponent(models.Model):
    line = models.ForeignKey(
        ProductionLine,
        on_delete=models.CASCADE,
        related_name="components",
    )
    item = models.ForeignKey(
        "catalog.Item",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    supplier_item = models.ForeignKey(
        "catalog.SupplierItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    planned_qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    unit = models.CharField(max_length=16, blank=True, default="ea")
    done = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["line_id", "sort_order", "id"]

    def __str__(self) -> str:
        label = self.name or (self.item.name if self.item_id else f"comp#{self.pk}")
        return f"{self.line_id}:{label} done={self.done}"


class LineEvent(models.Model):
    """Append-ish event log on a production line (tick, status, notes)."""

    line = models.ForeignKey(
        ProductionLine,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.line_id}:{self.kind}@{self.created_at}"


class ServiceOutlet(models.Model):
    """
    Outlet of a section — not a peer section.
    v1: executive_lounge is an outlet of a_la_carte only.
    """

    class Outlet(models.TextChoices):
        EXECUTIVE_LOUNGE = "executive_lounge", "Executive lounge"

    service_section = models.ForeignKey(
        ServiceSection,
        on_delete=models.CASCADE,
        related_name="outlets",
    )
    outlet = models.CharField(max_length=32, choices=Outlet.choices, db_index=True)
    active = models.BooleanField(default=True)
    covers = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service_section", "outlet"],
                name="uniq_serviceoutlet_section_outlet",
            ),
        ]
        ordering = ["service_section_id", "outlet"]

    def __str__(self) -> str:
        return f"{self.service_section_id}:{self.outlet}"


class Wave(models.Model):
    """Banquet service wave under a section (multiple waves, one line set)."""

    service_section = models.ForeignKey(
        ServiceSection,
        on_delete=models.CASCADE,
        related_name="waves",
    )
    name = models.CharField(max_length=128)
    serve_at = models.TimeField(null=True, blank=True)
    covers = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["service_section_id", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["service_section", "name"],
                name="uniq_wave_section_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.service_section_id}:{self.name}"


class WaveAllocation(models.Model):
    """
    Allocate one ProductionLine across waves — never duplicate the line per wave.
    unique(line, wave).
    """

    line = models.ForeignKey(
        ProductionLine,
        on_delete=models.CASCADE,
        related_name="wave_allocations",
    )
    wave = models.ForeignKey(
        Wave,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    qty = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["line", "wave"],
                name="uniq_waveallocation_line_wave",
            ),
        ]
        ordering = ["line_id", "wave_id"]

    def __str__(self) -> str:
        return f"line={self.line_id} wave={self.wave_id} qty={self.qty}"

    def clean(self) -> None:
        if (
            self.line_id
            and self.wave_id
            and self.line.service_section_id != self.wave.service_section_id
        ):
            raise ValidationError(
                "WaveAllocation line and wave must share the same service_section"
            )
