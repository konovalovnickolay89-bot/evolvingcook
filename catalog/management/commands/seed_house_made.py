"""
Seed D12 house-made examples (idempotent).

  python manage.py seed_house_made

1. Asian slaw (house_made) — red/white/savoy cabbage, carrot, onion
2. Aioli (house_made) — house-prepared flag; quantities unverified
3. DishTemplates on a_la_carte linked to those Items so board lines carry
   item_id / item_house_made for the FE (prep lines + component FKs).

Does NOT strip SupplierItems. Creates missing component Items if needed.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item, ItemComponent, SupplierItem
from planning.models import DishTemplate, DishTemplateComponent, ServiceSectionCode

# Parent preferred names (first match wins among existing catalogue)
SLAW_CANDIDATES = ("Asian slaw", "Asian slaw mix")
AIOLI_CANDIDATES = ("Aioli",)

# (display name, base_unit) for components — qty left null (unverified)
SLAW_COMPONENTS: list[tuple[str, str]] = [
    ("Red cabbage", "ea"),
    ("White cabbage", "ea"),
    ("Carrot", "ea"),
    ("Savoy cabbage", "ea"),
    ("Onion", "ea"),
]

UNVERIFIED_NOTE = "D12 seed: house-made; quantities unverified"
COMPONENT_NOTE = "unverified qty"

# Board section for first-class house-made prep lines (MEP / ALC prep)
PREP_SECTION = ServiceSectionCode.A_LA_CARTE


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _find_item_ci(name: str) -> Item | None:
    """Case-insensitive exact name match."""
    n = _norm(name)
    return Item.objects.filter(name__iexact=n).first()


def _get_or_create_item(name: str, *, base_unit: str = "ea") -> tuple[Item, bool]:
    existing = _find_item_ci(name)
    if existing:
        return existing, False
    item = Item.objects.create(
        name=_norm(name),
        base_unit=base_unit,
        active=True,
        unverified=True,
        house_made=False,
        notes=COMPONENT_NOTE if name not in SLAW_CANDIDATES + AIOLI_CANDIDATES else "",
    )
    return item, True


def _resolve_parent(candidates: tuple[str, ...], *, create_name: str) -> tuple[Item, bool]:
    for cand in candidates:
        found = _find_item_ci(cand)
        if found:
            return found, False
    return _get_or_create_item(create_name)


def _ensure_prep_template(item: Item, *, sort_order: int) -> tuple[DishTemplate, bool]:
    """
    Idempotent DishTemplate for a house_made parent so board generation
    emits a ProductionLine with item FK (item_house_made=true on FE).
    Template name matches Item.name for resolve fallback.
    """
    tmpl, created = DishTemplate.objects.get_or_create(
        section=PREP_SECTION,
        name=item.name,
        defaults={
            "mode": DishTemplate.Mode.PRODUCE,
            "kind": DishTemplate.Kind.PREP,
            "category": "house_made",
            "unit": item.base_unit or "ea",
            "active": True,
            "sort_order": sort_order,
            "notes": item.notes or UNVERIFIED_NOTE,
            "item": item,
        },
    )
    fields: list[str] = []
    if tmpl.item_id != item.pk:
        tmpl.item = item
        fields.append("item")
    if tmpl.mode != DishTemplate.Mode.PRODUCE:
        tmpl.mode = DishTemplate.Mode.PRODUCE
        fields.append("mode")
    if tmpl.kind != DishTemplate.Kind.PREP:
        tmpl.kind = DishTemplate.Kind.PREP
        fields.append("kind")
    if not tmpl.active:
        tmpl.active = True
        fields.append("active")
    if fields:
        tmpl.save(update_fields=list(dict.fromkeys(fields)))

    # Mirror ItemComponent → DishTemplateComponent (by component item)
    for sort, ic in enumerate(
        ItemComponent.objects.filter(parent=item)
        .select_related("component")
        .order_by("sort_order", "id")
    ):
        DishTemplateComponent.objects.update_or_create(
            template=tmpl,
            item=ic.component,
            defaults={
                "name": ic.component.name if ic.component_id else "",
                "planned_qty": ic.qty,
                "unit": ic.unit or (ic.component.base_unit if ic.component_id else "ea"),
                "sort_order": ic.sort_order if ic.sort_order is not None else sort * 10,
                "notes": ic.notes or COMPONENT_NOTE,
                "supplier_item": None,
            },
        )
    return tmpl, created


class Command(BaseCommand):
    help = (
        "Seed Asian slaw + aioli house_made with ItemComponent + "
        "ALC prep DishTemplates (D12, idempotent)"
    )

    @transaction.atomic
    def handle(self, *args, **options):
        stats = {
            "parents": {},
            "components_created": 0,
            "components_existed": 0,
            "links_created": 0,
            "links_existed": 0,
            "templates": {},
            "supplier_items_preserved": {},
        }

        # --- Asian slaw ---
        slaw, slaw_created = _resolve_parent(SLAW_CANDIDATES, create_name="Asian slaw")
        si_slaw_before = SupplierItem.objects.filter(item=slaw).count()
        slaw.house_made = True
        slaw.unverified = True
        note = (slaw.notes or "").strip()
        if UNVERIFIED_NOTE not in note:
            slaw.notes = (note + (" | " if note else "") + UNVERIFIED_NOTE)[:500]
        slaw.active = True
        slaw.save(update_fields=["house_made", "unverified", "notes", "active"])
        stats["parents"]["slaw"] = {
            "id": slaw.pk,
            "name": slaw.name,
            "created": slaw_created,
            "house_made": slaw.house_made,
        }

        for sort, (comp_name, unit) in enumerate(SLAW_COMPONENTS):
            comp, created = _get_or_create_item(comp_name, base_unit=unit)
            if created:
                stats["components_created"] += 1
            else:
                stats["components_existed"] += 1
            link_unit = comp.base_unit or unit
            _, link_created = ItemComponent.objects.get_or_create(
                parent=slaw,
                component=comp,
                defaults={
                    "qty": None,
                    "unit": link_unit,
                    "sort_order": sort * 10,
                    "notes": COMPONENT_NOTE,
                },
            )
            if link_created:
                stats["links_created"] += 1
            else:
                stats["links_existed"] += 1
                link = ItemComponent.objects.get(parent=slaw, component=comp)
                fields: list[str] = []
                if not link.notes:
                    link.notes = COMPONENT_NOTE
                    fields.append("notes")
                if not link.unit:
                    link.unit = link_unit
                    fields.append("unit")
                if fields:
                    link.save(update_fields=fields)

        si_slaw_after = SupplierItem.objects.filter(item=slaw).count()
        stats["supplier_items_preserved"]["slaw"] = {
            "before": si_slaw_before,
            "after": si_slaw_after,
            "ok": si_slaw_after >= si_slaw_before,
        }

        # --- Aioli ---
        aioli, aioli_created = _resolve_parent(AIOLI_CANDIDATES, create_name="Aioli")
        si_aioli_before = SupplierItem.objects.filter(item=aioli).count()
        aioli.house_made = True
        aioli.unverified = True
        note = (aioli.notes or "").strip()
        house_note = "D12 seed: house-prepared; quantities unverified"
        if house_note not in note and UNVERIFIED_NOTE not in note:
            aioli.notes = (note + (" | " if note else "") + house_note)[:500]
        aioli.active = True
        aioli.save(update_fields=["house_made", "unverified", "notes", "active"])
        stats["parents"]["aioli"] = {
            "id": aioli.pk,
            "name": aioli.name,
            "created": aioli_created,
            "house_made": aioli.house_made,
            "component_count": aioli.components.count(),
        }
        si_aioli_after = SupplierItem.objects.filter(item=aioli).count()
        stats["supplier_items_preserved"]["aioli"] = {
            "before": si_aioli_before,
            "after": si_aioli_after,
            "ok": si_aioli_after >= si_aioli_before,
        }

        # --- Board templates (line-level item_house_made) ---
        slaw_tmpl, slaw_tmpl_created = _ensure_prep_template(slaw, sort_order=900)
        aioli_tmpl, aioli_tmpl_created = _ensure_prep_template(aioli, sort_order=910)
        stats["templates"]["slaw"] = {
            "id": slaw_tmpl.pk,
            "section": slaw_tmpl.section,
            "name": slaw_tmpl.name,
            "item_id": slaw_tmpl.item_id,
            "created": slaw_tmpl_created,
        }
        stats["templates"]["aioli"] = {
            "id": aioli_tmpl.pk,
            "section": aioli_tmpl.section,
            "name": aioli_tmpl.name,
            "item_id": aioli_tmpl.item_id,
            "created": aioli_tmpl_created,
        }

        self.stdout.write(self.style.SUCCESS("seed_house_made complete"))
        self.stdout.write(str(stats))
        self.stdout.write(
            f"ItemComponent total={ItemComponent.objects.count()} "
            f"house_made_items={Item.objects.filter(house_made=True).count()} "
            f"prep_templates={DishTemplate.objects.filter(item__house_made=True).count()}"
        )
