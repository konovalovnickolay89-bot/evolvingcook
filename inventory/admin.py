"""
Inventory admin — inspection only.

StockMovement: read-only (no add/change/delete).
StockBalance: list/filter only — no manual qty edit surface.
Waste / count_adjustment: API POST /api/v1/inventory/* (services).
"""
from __future__ import annotations

from django.contrib import admin

from inventory.models import StockBalance, StockMovement


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "occurred_at",
        "kind",
        "item",
        "area",
        "qty",
        "source_type",
        "source_id",
        "note_short",
    )
    list_filter = ("kind", "area", "source_type")
    search_fields = ("item__name", "note", "source_id", "source_type")
    autocomplete_fields = ("item", "area")
    ordering = ("-occurred_at", "-id")
    list_display_links = ("id",)
    readonly_fields = (
        "item",
        "area",
        "qty",
        "kind",
        "source_type",
        "source_id",
        "occurred_at",
        "note",
        "created_at",
    )

    @admin.display(description="note")
    def note_short(self, obj):
        n = obj.note or ""
        return n if len(n) <= 48 else n[:45] + "..."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "area", "qty", "updated_at")
    list_filter = ("area",)
    search_fields = ("item__name", "area__name")
    autocomplete_fields = ("item", "area")
    ordering = ("item__name", "area__name")
    list_display_links = ("id",)
    readonly_fields = ("item", "area", "qty", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # No manual balance edit surface (gate)
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True
