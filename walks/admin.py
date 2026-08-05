"""Walk admin — bulk-friendly lines."""
from django.contrib import admin

from walks.models import Walk, WalkLine


class WalkLineInline(admin.TabularInline):
    model = WalkLine
    extra = 0
    fields = (
        "sort_order",
        "item",
        "area",
        "counted_qty",
        "counted_unit",
        "qty_base",
        "skipped",
        "proposed_order_qty",
        "planned_order_qty",
        "note",
    )
    autocomplete_fields = ("item", "area")
    show_change_link = True


@admin.register(Walk)
class WalkAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "area",
        "status",
        "started_at",
        "submitted_at",
        "locked_at",
    )
    list_filter = ("kind", "status", "area")
    search_fields = ("notes", "id")
    autocomplete_fields = ("area",)
    list_display_links = ("id",)
    inlines = [WalkLineInline]
    date_hierarchy = "started_at"


@admin.register(WalkLine)
class WalkLineAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "walk",
        "item",
        "area",
        "counted_qty",
        "qty_base",
        "skipped",
        "proposed_order_qty",
        "planned_order_qty",
        "sort_order",
    )
    list_filter = ("skipped", "area", "walk__status", "walk__kind")
    search_fields = ("item__name", "note", "walk__id")
    autocomplete_fields = ("walk", "item", "area")
    list_editable = ("counted_qty", "skipped", "planned_order_qty", "sort_order")
    list_display_links = ("id", "item")
    ordering = ("walk_id", "sort_order", "id")
