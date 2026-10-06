"""
D12 item endpoints under /api/v1/items/...

  PATCH /api/v1/items/{item_id}/notes   # set; notes=null or "" clears
"""
from __future__ import annotations

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from api.auth import BearerAuth
from catalog.services import CatalogError, set_item_note

router = Router(tags=["items"], auth=BearerAuth())


class NoteIn(Schema):
    """null or empty string clears the note."""

    notes: str | None = None


class ItemNoteOut(Schema):
    id: int
    name: str
    notes: str
    house_made: bool


class ErrorOut(Schema):
    detail: str
    code: str


def _http_catalog(exc: CatalogError) -> HttpError:
    status = 404 if exc.code.endswith("not_found") else 400
    return HttpError(status, f"{exc.code}: {exc.message}")


@router.patch(
    "/{item_id}/notes",
    response={200: ItemNoteOut, 400: ErrorOut, 404: ErrorOut},
    summary="Set or clear Item.notes (null/empty clears; max 500)",
)
def patch_item_notes(request: HttpRequest, item_id: int, body: NoteIn):
    try:
        item = set_item_note(item_id, body.notes)
    except CatalogError as exc:
        raise _http_catalog(exc) from exc
    return {
        "id": item.pk,
        "name": item.name,
        "notes": item.notes or "",
        "house_made": bool(item.house_made),
    }
