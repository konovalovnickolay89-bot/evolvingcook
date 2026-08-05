"""
Catalogue services — business rules live here, not in views/admin.

LLM never writes domain state: accept handlers perform validated writes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from catalog.models import (
    CatalogIngestProposal,
    Item,
    Supplier,
    SupplierItem,
)


def _norm_name(value: str) -> str:
    return " ".join((value or "").strip().split())


def _base_unit_or_ea(raw: str | None) -> str:
    u = (raw or "ea").strip().lower()
    if u in {"g", "ml", "ea"}:
        return u
    return "ea"


@transaction.atomic
def accept_ingest_proposal(proposal_id: int) -> CatalogIngestProposal:
    """
    Accept one proposal row: write Item + optional SupplierItem in one txn.
    Idempotent if already accepted.
    """
    proposal = (
        CatalogIngestProposal.objects.select_for_update()
        .select_related("upload")
        .get(pk=proposal_id)
    )
    if proposal.status == CatalogIngestProposal.Status.ACCEPTED:
        return proposal
    if proposal.status == CatalogIngestProposal.Status.REJECTED:
        raise ValueError("Cannot accept a rejected proposal")

    name = _norm_name(proposal.name)
    if not name:
        raise ValueError("Proposal name is required")

    base_unit = _base_unit_or_ea(proposal.base_unit)
    unverified = bool(proposal.flagged_low_confidence) or (
        proposal.confidence is not None and proposal.confidence < Decimal("0.7")
    )

    item, created = Item.objects.get_or_create(
        name=name,
        defaults={
            "base_unit": base_unit,
            "unverified": unverified,
            "notes": proposal.notes or "",
            "active": True,
        },
    )
    if not created:
        # Never invent over existing; only OR-in unverified/notes
        update_fields: list[str] = []
        if unverified and not item.unverified:
            item.unverified = True
            update_fields.append("unverified")
        if proposal.notes and proposal.notes not in (item.notes or ""):
            item.notes = (item.notes + "\n" + proposal.notes).strip()
            update_fields.append("notes")
        if update_fields:
            item.save(update_fields=update_fields)

    supplier_item = None
    supplier_name = _norm_name(proposal.supplier_name)
    if supplier_name:
        supplier, _ = Supplier.objects.get_or_create(
            name=supplier_name,
            defaults={"active": True},
        )
        si_defaults: dict[str, Any] = {
            "supplier_code": (proposal.supplier_code or "").strip(),
            "pack_description": (proposal.pack_description or "").strip(),
            "pack_qty": proposal.pack_qty,
            "price": proposal.price,
            "unverified": unverified or not (proposal.supplier_code or "").strip(),
            "notes": proposal.notes or "",
            "active": True,
            "preferred": True,
        }
        supplier_item, si_created = SupplierItem.objects.get_or_create(
            supplier=supplier,
            item=item,
            defaults=si_defaults,
        )
        if not si_created:
            # Fill blanks only — never invent over known values
            si_fields: list[str] = []
            if not supplier_item.supplier_code and si_defaults["supplier_code"]:
                supplier_item.supplier_code = si_defaults["supplier_code"]
                si_fields.append("supplier_code")
            if supplier_item.pack_qty is None and proposal.pack_qty is not None:
                supplier_item.pack_qty = proposal.pack_qty
                si_fields.append("pack_qty")
            if supplier_item.price is None and proposal.price is not None:
                supplier_item.price = proposal.price
                si_fields.append("price")
            if unverified and not supplier_item.unverified:
                supplier_item.unverified = True
                si_fields.append("unverified")
            if si_fields:
                supplier_item.save(update_fields=si_fields)

    proposal.status = CatalogIngestProposal.Status.ACCEPTED
    proposal.decided_at = timezone.now()
    proposal.result_item = item
    proposal.result_supplier_item = supplier_item
    proposal.save(
        update_fields=[
            "status",
            "decided_at",
            "result_item",
            "result_supplier_item",
        ]
    )
    return proposal


@transaction.atomic
def reject_ingest_proposal(proposal_id: int, reason: str = "") -> CatalogIngestProposal:
    proposal = CatalogIngestProposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.status == CatalogIngestProposal.Status.ACCEPTED:
        raise ValueError("Cannot reject an accepted proposal")
    if reason:
        proposal.notes = (proposal.notes + f"\nreject: {reason}").strip()
    proposal.status = CatalogIngestProposal.Status.REJECTED
    proposal.decided_at = timezone.now()
    proposal.save(update_fields=["status", "decided_at", "notes"])
    return proposal


NOTE_MAX_LENGTH = 500


class CatalogError(Exception):
    def __init__(self, message: str, code: str = "catalog_error"):
        super().__init__(message)
        self.message = message
        self.code = code


@transaction.atomic
def set_item_note(item_id: int, notes: str | None) -> Item:
    """
    D12: set or clear Item.notes.
    None or blank string clears. Max 500 chars.
    """
    try:
        item = Item.objects.select_for_update().get(pk=item_id)
    except Item.DoesNotExist as exc:
        raise CatalogError("Item not found", code="item_not_found") from exc

    if notes is None:
        cleaned = ""
    else:
        cleaned = notes.strip() if isinstance(notes, str) else str(notes)
        if len(cleaned) > NOTE_MAX_LENGTH:
            raise CatalogError(
                f"notes max_length is {NOTE_MAX_LENGTH}",
                code="notes_too_long",
            )

    item.notes = cleaned
    item.save(update_fields=["notes"])
    return item
