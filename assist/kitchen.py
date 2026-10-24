"""
Kitchen notes and the inbox that points at existing proposal queues.

Notes are a standing store for typed, voice, and banto dictation.
They are not daily-brief tips. Inbox rows point at AssistProposal and
CatalogIngestProposal so those queues stay out of the brief.
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from assist.models import AssistProposal, KitchenInboxItem, KitchenNote

NOTE_SOURCES = frozenset({"typed", "voice", "banto"})
MAX_NOTE_TITLE = 200
MAX_NOTE_BODY = 8000


class KitchenError(RuntimeError):
    def __init__(self, detail: str, code: str = "bad_request"):
        super().__init__(detail)
        self.code = code


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return timezone.localtime(dt).isoformat()


def _note_out(note: KitchenNote) -> dict[str, Any]:
    return {
        "id": note.pk,
        "title": note.title,
        "body": note.body,
        "source": note.source,
        "created_at": _iso(note.created_at),
        "resolved_at": _iso(note.resolved_at),
    }


def _check_source(source: str) -> str:
    clean = (source or "typed").strip().lower()
    if clean not in NOTE_SOURCES:
        raise KitchenError("Source must be typed, voice, or banto.")
    return clean


def list_kitchen_notes(*, include_resolved: bool = False) -> list[dict[str, Any]]:
    qs = KitchenNote.objects.all()
    if not include_resolved:
        qs = qs.filter(resolved_at__isnull=True)
    return [_note_out(note) for note in qs]


def add_kitchen_note(
    *, title: str = "", body: str = "", source: str = "typed"
) -> dict[str, Any]:
    """Append a note. Bantō dictation uses source=banto. Not a brief tip."""
    source = _check_source(source)
    title = (title or "").strip()[:MAX_NOTE_TITLE]
    body = (body or "").strip()[:MAX_NOTE_BODY]
    if not body:
        raise KitchenError("A note needs some text.")
    note = KitchenNote.objects.create(title=title, body=body, source=source)
    return _note_out(note)


def resolve_kitchen_note(note_id: int) -> dict[str, Any]:
    try:
        note = KitchenNote.objects.get(pk=note_id)
    except KitchenNote.DoesNotExist as exc:
        raise KitchenError("Note not found.", code="not_found") from exc
    if note.resolved_at is None:
        note.resolved_at = timezone.now()
        note.save(update_fields=["resolved_at"])
    return _note_out(note)


def _clip(text: str) -> str:
    return (text or "").strip()[:500]


def attach_assist_proposal(proposal: AssistProposal) -> KitchenInboxItem:
    """Mirror one assist proposal into the kitchen inbox. Idempotent."""
    summary = _clip(proposal.rationale) or proposal.kind
    item, _created = KitchenInboxItem.objects.get_or_create(
        assist_proposal=proposal,
        defaults={
            "kind": KitchenInboxItem.Kind.ASSIST,
            "summary": summary,
        },
    )
    return item


def attach_catalog_proposal(proposal) -> KitchenInboxItem:
    """Mirror one catalogue ingest proposal into the kitchen inbox. Idempotent."""
    summary = _clip(getattr(proposal, "name", "") or "") or "catalogue proposal"
    item, _created = KitchenInboxItem.objects.get_or_create(
        catalog_proposal=proposal,
        defaults={
            "kind": KitchenInboxItem.Kind.CATALOG,
            "summary": summary,
        },
    )
    return item


def _inbox_out(item: KitchenInboxItem) -> dict[str, Any]:
    return {
        "id": item.pk,
        "kind": item.kind,
        "summary": item.summary,
        "assist_proposal_id": item.assist_proposal_id,
        "catalog_proposal_id": item.catalog_proposal_id,
        "created_at": _iso(item.created_at),
        "resolved_at": _iso(item.resolved_at),
    }


def list_kitchen_inbox(*, include_resolved: bool = False) -> list[dict[str, Any]]:
    qs = KitchenInboxItem.objects.all()
    if not include_resolved:
        qs = qs.filter(resolved_at__isnull=True)
    return [_inbox_out(item) for item in qs]


def resolve_kitchen_inbox_item(item_id: int) -> dict[str, Any]:
    """Hide an inbox row. Does not accept or reject the underlying proposal."""
    try:
        item = KitchenInboxItem.objects.get(pk=item_id)
    except KitchenInboxItem.DoesNotExist as exc:
        raise KitchenError("Inbox item not found.", code="not_found") from exc
    if item.resolved_at is None:
        item.resolved_at = timezone.now()
        item.save(update_fields=["resolved_at"])
    return _inbox_out(item)
