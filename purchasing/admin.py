"""Purchasing admin — bulk-friendly PO and delivery lines."""
from django.contrib import admin

from purchasing.models import Delivery, DeliveryLine, PurchaseOrder, PurchaseOrderLine


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    fields = (
        "supplier_item",
        "proposed_packs",
        "packs",
        "qty_base",
        "price",
        "par",
        "counted",
        "on_order",
        "shortfall",
        "note",
    )
    autocomplete_fields = ("supplier_item",)
    show_change_link = True


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "supplier",
        "walk",
        "order_date",
        "delivery_date",
        "status",
        "scope",
        "total",
        "sent_at",
    )
    list_filter = ("status", "scope", "supplier", "order_date")
    search_fields = ("notes", "id", "supplier__name")
    autocomplete_fields = ("supplier", "walk")
    list_display_links = ("id",)
    list_editable = ("status", "scope")
    inlines = [PurchaseOrderLineInline]
    date_hierarchy = "order_date"
    fields = (
        "supplier",
        "walk",
        "order_date",
        "delivery_date",
        "status",
        "scope",
        "total",
        "notes",
        "sent_at",
        "created_at",
    )
    readonly_fields = ("created_at", "sent_at")


@admin.register(PurchaseOrderLine)
class PurchaseOrderLineAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "purchase_order",
        "supplier_item",
        "proposed_packs",
        "packs",
        "qty_base",
        "price",
        "shortfall",
        "par",
        "counted",
        "on_order",
    )
    list_filter = ("purchase_order__status", "purchase_order__supplier")
    search_fields = (
        "supplier_item__item__name",
        "supplier_item__supplier_code",
        "note",
    )
    autocomplete_fields = ("purchase_order", "supplier_item")
    list_editable = ("packs", "price")
    list_display_links = ("id", "supplier_item")


class DeliveryLineInline(admin.TabularInline):
    model = DeliveryLine
    extra = 0
    fields = (
        "supplier_item",
        "packs_expected",
        "packs_received",
        "price",
        "note",
        "note_text",
    )
    autocomplete_fields = ("supplier_item",)


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "purchase_order",
        "supplier",
        "received_on",
        "status",
    )
    list_filter = ("status", "supplier", "received_on")
    search_fields = ("notes", "id")
    autocomplete_fields = ("purchase_order", "supplier")
    list_display_links = ("id",)
    inlines = [DeliveryLineInline]
    date_hierarchy = "received_on"


@admin.register(DeliveryLine)
class DeliveryLineAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "delivery",
        "supplier_item",
        "packs_expected",
        "packs_received",
        "note",
        "price",
    )
    list_filter = ("note", "delivery__status")
    search_fields = ("supplier_item__item__name", "note_text")
    autocomplete_fields = ("delivery", "supplier_item")
    list_editable = ("packs_received", "note")
    list_display_links = ("id", "supplier_item")
