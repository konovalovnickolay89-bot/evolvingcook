"""
Recipes API — Bearer /api/v1/recipes/* (D17).

Recipe cards: production spec + method. The companion drafts
(POST /recipes/draft, never saves); the chef creates/edits/owns.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema

from api.auth import BearerAuth
from assist import companion
from catalog.models import Recipe

router = Router(tags=["recipes"], auth=BearerAuth())


class ErrorOut(Schema):
    detail: str
    code: str


class RecipeIn(Schema):
    name: str
    section: str = ""
    base_covers: int | None = None
    yield_qty: float | None = None
    yield_unit: str = ""
    ingredients: list[dict[str, Any]] = []
    method: list[str] = []
    allergens: list[str] = []
    notes: str = ""
    source: str = "chef"


class RecipePatchIn(Schema):
    name: str | None = None
    section: str | None = None
    base_covers: int | None = None
    yield_qty: float | None = None
    yield_unit: str | None = None
    ingredients: list[dict[str, Any]] | None = None
    method: list[str] | None = None
    allergens: list[str] | None = None
    notes: str | None = None


class DraftIn(Schema):
    prompt: str
    covers: int | None = None


def _dec(v: float | None) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _out(r: Recipe) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "section": r.section,
        "base_covers": r.base_covers,
        "yield_qty": float(r.yield_qty) if r.yield_qty is not None else None,
        "yield_unit": r.yield_unit,
        "ingredients": r.ingredients or [],
        "method": r.method or [],
        "allergens": r.allergens or [],
        "notes": r.notes,
        "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("", response=list[dict])
def list_recipes(request: HttpRequest, q: str | None = None, limit: int = 100):
    qs = Recipe.objects.all()
    if q:
        qs = qs.filter(name__icontains=q.strip())
    limit = max(1, min(int(limit or 100), 500))
    return [_out(r) for r in qs[:limit]]


@router.post("", response={201: dict, 400: ErrorOut})
def create_recipe(request: HttpRequest, body: RecipeIn):
    name = body.name.strip()
    if not name:
        return 400, {"detail": "Recipe needs a name", "code": "missing_name"}
    r = Recipe.objects.create(
        name=name,
        section=(body.section or "").strip(),
        base_covers=body.base_covers,
        yield_qty=_dec(body.yield_qty),
        yield_unit=(body.yield_unit or "").strip(),
        ingredients=body.ingredients or [],
        method=body.method or [],
        allergens=body.allergens or [],
        notes=body.notes or "",
        source=body.source if body.source in ("chef", "companion") else "chef",
    )
    return 201, _out(r)


# Registered BEFORE /{recipe_id}: ninja path params match any segment, so
# the param route would swallow /draft (see the /log/suggest 405 fix).
@router.post("/draft", response={200: dict, 400: ErrorOut, 503: ErrorOut})
def draft_recipe(request: HttpRequest, body: DraftIn):
    try:
        return 200, companion.draft_recipe(body.prompt, body.covers)
    except companion.CompanionError as exc:
        status = 400 if exc.code == "bad_request" else 503
        return status, {"detail": str(exc), "code": exc.code}


@router.get("/{recipe_id}", response={200: dict, 404: ErrorOut})
def get_recipe(request: HttpRequest, recipe_id: int):
    try:
        return 200, _out(Recipe.objects.get(pk=recipe_id))
    except Recipe.DoesNotExist:
        return 404, {"detail": "not found", "code": "not_found"}


@router.patch("/{recipe_id}", response={200: dict, 400: ErrorOut, 404: ErrorOut})
def patch_recipe(request: HttpRequest, recipe_id: int, body: RecipePatchIn):
    try:
        r = Recipe.objects.get(pk=recipe_id)
    except Recipe.DoesNotExist:
        return 404, {"detail": "not found", "code": "not_found"}
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            return 400, {"detail": "Recipe needs a name", "code": "missing_name"}
        r.name = name
    if "section" in fields:
        r.section = (fields["section"] or "").strip()
    if "base_covers" in fields:
        r.base_covers = fields["base_covers"]
    if "yield_qty" in fields:
        r.yield_qty = _dec(fields["yield_qty"])
    if "yield_unit" in fields:
        r.yield_unit = (fields["yield_unit"] or "").strip()
    if "ingredients" in fields:
        r.ingredients = fields["ingredients"] or []
    if "method" in fields:
        r.method = fields["method"] or []
    if "allergens" in fields:
        r.allergens = fields["allergens"] or []
    if "notes" in fields:
        r.notes = fields["notes"] or ""
    r.save()
    return 200, _out(r)


@router.delete("/{recipe_id}", response={204: None, 404: ErrorOut})
def delete_recipe(request: HttpRequest, recipe_id: int):
    deleted, _ = Recipe.objects.filter(pk=recipe_id).delete()
    if not deleted:
        return 404, {"detail": "not found", "code": "not_found"}
    return 204, None
