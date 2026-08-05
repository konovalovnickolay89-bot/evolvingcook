"""Planning admin — product-usable list surfaces for boards (Phase 1.5 + 4)."""
from django.contrib import admin

from planning.models import (
    DishTemplate,
    DishTemplateComponent,
    LineComponent,
    LineEvent,
    ProductionLine,
    ServiceDay,
    ServiceOutlet,
    ServiceSection,
    Wave,
    WaveAllocation,
)


class DishTemplateComponentInline(admin.TabularInline):
    model = DishTemplateComponent
    extra = 0
    autocomplete_fields = ("item", "supplier_item")
    fields = ("item", "supplier_item", "name", "planned_qty", "unit", "sort_order", "notes")


@admin.register(DishTemplate)
class DishTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "section",
        "mode",
        "kind",
        "active",
        "supports_lounge",
        "yield_per_cover",
        "sort_order",
    )
    list_filter = ("section", "mode", "kind", "active", "supports_lounge")
    search_fields = ("name", "notes", "category")
    list_editable = ("active", "sort_order", "supports_lounge", "yield_per_cover")
    list_display_links = ("name",)
    autocomplete_fields = ("item",)
    inlines = [DishTemplateComponentInline]
    ordering = ("section", "sort_order", "name")


class ServiceSectionInline(admin.TabularInline):
    model = ServiceSection
    extra = 0
    fields = ("section", "active", "covers", "covers_source", "notes")


@admin.register(ServiceDay)
class ServiceDayAdmin(admin.ModelAdmin):
    list_display = (
        "service_date",
        "status",
        "occupancy_rooms",
        "occupancy_guests",
        "opened_at",
        "closed_at",
    )
    list_filter = ("status",)
    search_fields = ("notes",)
    date_hierarchy = "service_date"
    inlines = [ServiceSectionInline]
    readonly_fields = ("outturn",)


class WaveInline(admin.TabularInline):
    model = Wave
    extra = 0
    fields = ("name", "serve_at", "covers", "sort_order")


class ServiceOutletInline(admin.TabularInline):
    model = ServiceOutlet
    extra = 0
    fields = ("outlet", "active", "covers")


@admin.register(ServiceSection)
class ServiceSectionAdmin(admin.ModelAdmin):
    list_display = (
        "service_day",
        "section",
        "active",
        "covers",
        "covers_source",
    )
    list_filter = ("section", "active", "covers_source")
    search_fields = ("notes", "service_day__service_date")
    autocomplete_fields = ("service_day",)
    list_editable = ("active",)
    list_display_links = ("service_day", "section")
    inlines = [WaveInline, ServiceOutletInline]
    readonly_fields = ("outturn", "beo_events")


@admin.register(ServiceOutlet)
class ServiceOutletAdmin(admin.ModelAdmin):
    list_display = ("service_section", "outlet", "active", "covers")
    list_filter = ("outlet", "active")
    search_fields = ("service_section__section",)
    autocomplete_fields = ("service_section",)
    list_editable = ("active", "covers")


@admin.register(Wave)
class WaveAdmin(admin.ModelAdmin):
    list_display = ("name", "service_section", "serve_at", "covers", "sort_order")
    list_filter = ("service_section__section",)
    search_fields = ("name",)
    autocomplete_fields = ("service_section",)
    list_editable = ("covers", "sort_order")
    ordering = ("service_section", "sort_order", "name")


@admin.register(WaveAllocation)
class WaveAllocationAdmin(admin.ModelAdmin):
    list_display = ("line", "wave", "qty")
    search_fields = ("line__name", "wave__name")
    autocomplete_fields = ("line", "wave")


class LineComponentInline(admin.TabularInline):
    model = LineComponent
    extra = 0
    autocomplete_fields = ("item", "supplier_item")
    fields = ("item", "supplier_item", "name", "planned_qty", "unit", "done", "sort_order")


class LineEventInline(admin.TabularInline):
    model = LineEvent
    extra = 0
    readonly_fields = ("kind", "payload", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class WaveAllocationInline(admin.TabularInline):
    model = WaveAllocation
    extra = 0
    autocomplete_fields = ("wave",)
    fields = ("wave", "qty")


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "service_section",
        "mode",
        "status",
        "source",
        "proposed_qty",
        "planned_qty",
        "actual_qty",
        "sort_order",
    )
    list_filter = ("mode", "status", "source", "kind", "supports_lounge")
    search_fields = ("name", "notes", "category")
    list_editable = ("status", "sort_order")
    list_display_links = ("name",)
    autocomplete_fields = ("service_section", "item", "template")
    inlines = [LineComponentInline, WaveAllocationInline, LineEventInline]


@admin.register(LineComponent)
class LineComponentAdmin(admin.ModelAdmin):
    list_display = ("line", "name", "item", "planned_qty", "unit", "done", "sort_order")
    list_filter = ("done",)
    search_fields = ("name", "line__name")
    autocomplete_fields = ("line", "item", "supplier_item")
    list_editable = ("done",)


@admin.register(LineEvent)
class LineEventAdmin(admin.ModelAdmin):
    list_display = ("line", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("line__name", "kind")
    readonly_fields = ("line", "kind", "payload", "created_at")
