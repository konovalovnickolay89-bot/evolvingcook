"""
Admin is a product surface (Phase 1), not scaffolding.
B6: list_editable fields must not appear in list_display_links.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.shortcuts import redirect, render

from catalog.ingest import queue_ingest_extraction
from catalog.models import (
    CatalogIngestProposal,
    CatalogIngestUpload,
    Item,
    ItemComponent,
    ParLevel,
    StorageArea,
    Supplier,
    SupplierItem,
    UnitConversion,
)
from catalog.services import accept_ingest_proposal, reject_ingest_proposal


class _BulkSetAreaForm(forms.Form):
    area = forms.ModelChoiceField(
        queryset=StorageArea.objects.filter(active=True).order_by("name"),
        required=True,
        label="Default storage area",
    )
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    action = forms.CharField(widget=forms.HiddenInput)


class UnitConversionInline(admin.TabularInline):
    model = UnitConversion
    extra = 0
    fields = ("unit", "factor_to_base", "countable")
    autocomplete_fields = ()


class SupplierItemInline(admin.TabularInline):
    model = SupplierItem
    extra = 0
    fields = (
        "supplier",
        "supplier_code",
        "pack_description",
        "pack_qty",
        "price",
        "preferred",
        "active",
        "unverified",
    )
    autocomplete_fields = ("supplier",)
    show_change_link = True


class ItemComponentInline(admin.TabularInline):
    """D12 recipe-lite components on Item change page."""

    model = ItemComponent
    fk_name = "parent"
    extra = 0
    fields = ("component", "qty", "unit", "sort_order", "notes")
    autocomplete_fields = ("component",)
    ordering = ("sort_order", "id")


@admin.register(StorageArea)
class StorageAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "walk_order", "active")
    list_editable = ("walk_order", "active")
    list_display_links = ("name",)
    list_filter = ("kind", "active")
    search_fields = ("name",)
    ordering = ("walk_order", "name")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "base_unit",
        "category",
        "default_area",
        "walk_order",
        "house_made",
        "active",
        "unverified",
    )
    list_editable = ("category", "default_area", "walk_order", "house_made", "active")
    list_display_links = ("name",)
    list_filter = (
        "active",
        "unverified",
        "house_made",
        "base_unit",
        "category",
        "default_area",
    )
    search_fields = ("name", "code", "supplier_items__supplier_code", "notes")
    autocomplete_fields = ("default_area",)
    inlines = (ItemComponentInline, UnitConversionInline, SupplierItemInline)
    actions = (
        "activate_items",
        "deactivate_items",
        "set_default_area_bulk",
    )

    @admin.action(description="Activate selected items")
    def activate_items(self, request, queryset):
        n = queryset.update(active=True)
        self.message_user(request, f"Activated {n} item(s).", messages.SUCCESS)

    @admin.action(description="Deactivate selected items")
    def deactivate_items(self, request, queryset):
        n = queryset.update(active=False)
        self.message_user(request, f"Deactivated {n} item(s).", messages.SUCCESS)

    @admin.action(description="Set default area…")
    def set_default_area_bulk(self, request, queryset):
        """Intermediate chooser — bulk set Item.default_area."""
        if "apply" in request.POST:
            form = _BulkSetAreaForm(request.POST)
            if form.is_valid():
                area = form.cleaned_data["area"]
                n = queryset.update(default_area=area)
                self.message_user(
                    request,
                    f"Set default_area={area.name!r} on {n} item(s).",
                    messages.SUCCESS,
                )
                return redirect(request.get_full_path())
        else:
            form = _BulkSetAreaForm(
                initial={
                    "_selected_action": request.POST.getlist(ACTION_CHECKBOX_NAME),
                    "action": "set_default_area_bulk",
                }
            )
        return render(
            request,
            "admin/catalog/item/bulk_set_area.html",
            {
                "items": queryset,
                "form": form,
                "title": "Set default storage area",
                "opts": self.model._meta,
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            },
        )


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "account_code",
        "lead_time_days",
        "min_order_value",
        "active",
    )
    list_editable = ("account_code", "lead_time_days", "active")
    list_display_links = ("name",)
    list_filter = ("active",)
    search_fields = ("name", "account_code")


@admin.register(SupplierItem)
class SupplierItemAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "supplier",
        "supplier_code",
        "pack_description",
        "pack_qty",
        "price",
        "preferred",
        "active",
        "unverified",
    )
    list_editable = ("pack_qty", "price", "preferred", "active")
    list_display_links = ("item", "supplier")
    list_filter = ("active", "unverified", "preferred", "supplier")
    search_fields = (
        "item__name",
        "supplier__name",
        "supplier_code",
        "pack_description",
        "notes",
    )
    autocomplete_fields = ("item", "supplier")
    actions = ("activate_si", "deactivate_si")

    @admin.action(description="Activate selected supplier items")
    def activate_si(self, request, queryset):
        n = queryset.update(active=True)
        self.message_user(request, f"Activated {n}.", messages.SUCCESS)

    @admin.action(description="Deactivate selected supplier items")
    def deactivate_si(self, request, queryset):
        n = queryset.update(active=False)
        self.message_user(request, f"Deactivated {n}.", messages.SUCCESS)


@admin.register(ParLevel)
class ParLevelAdmin(admin.ModelAdmin):
    list_display = ("item", "area", "weekday", "qty")
    list_editable = ("qty",)
    list_display_links = ("item", "area")
    list_filter = ("area", "weekday")
    search_fields = ("item__name", "area__name")
    autocomplete_fields = ("item", "area")


@admin.register(UnitConversion)
class UnitConversionAdmin(admin.ModelAdmin):
    list_display = ("item", "unit", "factor_to_base", "countable")
    list_editable = ("factor_to_base", "countable")
    list_display_links = ("item", "unit")
    search_fields = ("item__name", "unit")
    autocomplete_fields = ("item",)


class CatalogIngestProposalInline(admin.TabularInline):
    model = CatalogIngestProposal
    extra = 0
    fields = (
        "status",
        "name",
        "base_unit",
        "supplier_name",
        "supplier_code",
        "pack_qty",
        "price",
        "confidence",
        "flagged_low_confidence",
        "dish",
    )
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CatalogIngestUpload)
class CatalogIngestUploadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "source_kind",
        "status",
        "model_name",
        "q_task_id",
    )
    list_display_links = ("id", "created_at")
    list_filter = ("status", "source_kind")
    search_fields = ("raw_text", "error", "q_task_id")
    readonly_fields = ("created_at", "status", "error", "q_task_id", "model_name")
    inlines = (CatalogIngestProposalInline,)
    actions = ("queue_extraction",)

    @admin.action(description="Queue extraction job (django-q2 → Mistral)")
    def queue_extraction(self, request, queryset):
        ok = 0
        for upload in queryset:
            try:
                queue_ingest_extraction(upload.pk)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request,
                    f"Upload #{upload.pk}: {exc}",
                    messages.ERROR,
                )
        if ok:
            self.message_user(
                request,
                f"Queued {ok} upload(s). Requires qcluster worker + MISTRAL_API_KEY.",
                messages.SUCCESS,
            )


@admin.register(CatalogIngestProposal)
class CatalogIngestProposalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "upload",
        "name",
        "supplier_name",
        "supplier_code",
        "base_unit",
        "pack_qty",
        "price",
        "confidence",
        "flagged_low_confidence",
        "status",
    )
    list_editable = ("pack_qty", "price")
    list_display_links = ("id", "name")
    list_filter = ("status", "flagged_low_confidence", "base_unit", "upload")
    search_fields = (
        "name",
        "supplier_name",
        "supplier_code",
        "dish",
        "notes",
    )
    actions = ("accept_selected", "reject_selected")
    readonly_fields = (
        "result_item",
        "result_supplier_item",
        "decided_at",
        "raw",
    )

    @admin.action(description="Accept → write Item + SupplierItem (one txn each)")
    def accept_selected(self, request, queryset):
        ok = err = 0
        for prop in queryset:
            try:
                with transaction.atomic():
                    accept_ingest_proposal(prop.pk)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                err += 1
                self.message_user(
                    request,
                    f"Proposal #{prop.pk}: {exc}",
                    messages.ERROR,
                )
        self.message_user(
            request,
            f"Accepted {ok}; errors {err}.",
            messages.SUCCESS if ok else messages.WARNING,
        )

    @admin.action(description="Reject selected proposals")
    def reject_selected(self, request, queryset):
        ok = 0
        for prop in queryset:
            try:
                reject_ingest_proposal(prop.pk)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request,
                    f"Proposal #{prop.pk}: {exc}",
                    messages.ERROR,
                )
        self.message_user(request, f"Rejected {ok}.", messages.SUCCESS)
