"""
Seed dish templates for MEP boards (Phase 1.5).

ALC: sheets/alc-dish-sheet-p1.csv + alc-dish-sheet-p2.csv
  - one DishTemplate per distinct dish name on the sheet
  - components linked to catalogue Item by exact name when present
  - OFF MENU dishes kept inactive (sticky pigs in blankets, wild-caught crab cake)

Skybar: sheets/skybar-mep-list.csv
  - if missing, skip and report (never invent)
  - when present: one DishTemplate per dish, check-mode components
  - component Items get_or_create by name; supplier_item always null (D8)
  - never invent supplier codes/prices

Idempotent / re-runnable.

Usage:
  python manage.py seed_dish_templates
  python manage.py seed_dish_templates --alc-only
  python manage.py seed_dish_templates --skybar-only
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item, SupplierItem
from planning.models import (
    DishTemplate,
    DishTemplateComponent,
    ServiceSectionCode,
)

ALC_SHEETS = (
    "alc-dish-sheet-p1.csv",
    "alc-dish-sheet-p2.csv",
    # 2026-08-04 ordering guide + kids (p4 is catalogue-only extras, no dishes)
    "alc-dish-sheet-p3.csv",
)

# Off-menu dishes: keep template + items, inactive so boards skip them
OFF_MENU_DISH_RE = re.compile(
    r"^(STICKY PIGS IN BLANKETS|WILD-CAUGHT CRAB CAKE)$",
    re.I,
)

OFF_MENU_NOTE_RE = re.compile(r"OFF\s*MENU", re.I)


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


class Command(BaseCommand):
    help = "Seed ALC (+ optional skybar) dish templates for board generation"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sheets-dir",
            default="",
            help="Override sheets directory (default: <BASE_DIR>/sheets)",
        )
        parser.add_argument(
            "--alc-only",
            action="store_true",
            help="Only process ALC CSVs",
        )
        parser.add_argument(
            "--skybar-only",
            action="store_true",
            help="Only process skybar-mep-list.csv (no-op if missing)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        sheets_dir = Path(options["sheets_dir"] or (Path(settings.BASE_DIR) / "sheets"))
        do_alc = not options["skybar_only"]
        do_skybar = not options["alc_only"]

        stats = {
            "alc_dishes_upserted": 0,
            "alc_components": 0,
            "alc_inactive": 0,
            "skybar_dishes_upserted": 0,
            "skybar_components": 0,
            "skybar_items_created": 0,
            "skybar_items_linked": 0,
            "missing": [],
            "files": [],
        }

        if do_alc:
            self._seed_alc(sheets_dir, stats)
        if do_skybar:
            self._seed_skybar(sheets_dir, stats)

        self.stdout.write(self.style.SUCCESS("seed_dish_templates complete"))
        self.stdout.write(f"stats: {stats}")
        self.stdout.write(
            f"counts: templates={DishTemplate.objects.count()} "
            f"active={DishTemplate.objects.filter(active=True).count()} "
            f"components={DishTemplateComponent.objects.count()} "
            f"alc_active={DishTemplate.objects.filter(section='a_la_carte', active=True).count()}"
        )
        if "skybar-mep-list.csv" in stats["missing"]:
            self.stdout.write(
                self.style.WARNING(
                    "skybar-mep-list.csv MISSING — leave path ready; "
                    "drop file into sheets/ and re-run: "
                    "python manage.py seed_dish_templates --skybar-only"
                )
            )

    def _seed_alc(self, sheets_dir: Path, stats: dict) -> None:
        # dish_name -> list of component rows
        dishes: dict[str, list[dict]] = {}
        dish_off: set[str] = set()

        for fname in ALC_SHEETS:
            path = sheets_dir / fname
            if not path.is_file():
                stats["missing"].append(fname)
                self.stdout.write(self.style.ERROR(f"missing sheet: {path}"))
                continue
            stats["files"].append(fname)
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    dish = _norm(row.get("dish") or "")
                    item_name = _norm(row.get("item") or "")
                    notes = _norm(row.get("notes") or "")
                    if not dish:
                        # orphan ingredient rows without dish — skip for templates
                        continue
                    if not item_name:
                        continue
                    dishes.setdefault(dish, []).append(
                        {
                            "item_name": item_name,
                            "supplier_code": _norm(row.get("supplier_code") or ""),
                            "supplier": _norm(row.get("supplier") or ""),
                            "notes": notes,
                        }
                    )
                    if OFF_MENU_DISH_RE.match(dish) or OFF_MENU_NOTE_RE.search(notes):
                        dish_off.add(dish)

        # Always force known off-menu names inactive even if notes missing
        for name in ("STICKY PIGS IN BLANKETS", "WILD-CAUGHT CRAB CAKE"):
            if name in dishes:
                dish_off.add(name)

        item_by_name = {i.name: i for i in Item.objects.all()}

        for sort_i, dish_name in enumerate(sorted(dishes.keys())):
            active = dish_name not in dish_off
            tmpl, _ = DishTemplate.objects.update_or_create(
                section=ServiceSectionCode.A_LA_CARTE,
                name=dish_name,
                defaults={
                    "mode": DishTemplate.Mode.CHECK,
                    "kind": DishTemplate.Kind.DISH,
                    "category": "a_la_carte",
                    "unit": "ea",
                    "par_level": None,
                    "supports_lounge": False,
                    "active": active,
                    "sort_order": sort_i * 10,
                    "notes": "off-menu" if not active else "",
                    "item": None,
                },
            )
            stats["alc_dishes_upserted"] += 1
            if not active:
                stats["alc_inactive"] += 1

            # Rebuild components idempotently for this template
            tmpl.components.all().delete()
            comps = []
            for ci, crow in enumerate(dishes[dish_name]):
                item = item_by_name.get(crow["item_name"])
                si = None
                if item:
                    si = (
                        SupplierItem.objects.filter(item=item, preferred=True)
                        .order_by("id")
                        .first()
                    )
                    if si is None:
                        si = (
                            SupplierItem.objects.filter(item=item)
                            .order_by("id")
                            .first()
                        )
                comps.append(
                    DishTemplateComponent(
                        template=tmpl,
                        item=item,
                        supplier_item=si,
                        name=crow["item_name"] if item is None else "",
                        planned_qty=None,  # blank ≠ 0
                        unit=item.base_unit if item else "ea",
                        sort_order=ci * 10,
                        notes=crow["notes"],
                    )
                )
            DishTemplateComponent.objects.bulk_create(comps)
            stats["alc_components"] += len(comps)

    def _seed_skybar(self, sheets_dir: Path, stats: dict) -> None:
        path = sheets_dir / "skybar-mep-list.csv"
        if not path.is_file():
            stats["missing"].append("skybar-mep-list.csv")
            self.stdout.write(
                self.style.WARNING(
                    "skybar-mep-list.csv MISSING — not inventing skybar templates"
                )
            )
            return

        stats["files"].append("skybar-mep-list.csv")
        # Flexible columns: dish/name + optional item/component
        dishes: dict[str, list[dict]] = {}
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = [(_norm(f).lower()) for f in (reader.fieldnames or [])]
            # map original headers
            raw_headers = reader.fieldnames or []
            lower_map = {h: _norm(h).lower() for h in raw_headers}

            def col(row, *candidates):
                for c in candidates:
                    for orig, low in lower_map.items():
                        if low == c:
                            return _norm(row.get(orig) or "")
                return ""

            for row in reader:
                dish = col(row, "dish", "name", "mep", "item_dish")
                item_name = col(row, "item", "component", "ingredient")
                if not dish and item_name:
                    # flat list of components without dish grouping — each row a check line
                    dish = item_name
                    item_name = item_name
                if not dish:
                    continue
                dishes.setdefault(dish, []).append(
                    {
                        "item_name": item_name or dish,
                        "notes": col(row, "notes", "note"),
                    }
                )

        # Exact + case-insensitive lookup so re-seed does not fork near-duplicates.
        item_by_name = {i.name: i for i in Item.objects.all()}
        item_by_lname = {n.casefold(): i for n, i in item_by_name.items()}

        def resolve_item(component_name: str) -> Item:
            """Link by name; create Item if missing. Never attach supplier (D8)."""
            if not component_name:
                raise ValueError("skybar component name required")
            hit = item_by_name.get(component_name) or item_by_lname.get(
                component_name.casefold()
            )
            if hit is not None:
                stats["skybar_items_linked"] += 1
                return hit
            item = Item.objects.create(
                name=component_name,
                base_unit=Item.BaseUnit.EA,
                active=True,
                category="skybar",
                notes="seed:skybar-mep-list",
            )
            item_by_name[item.name] = item
            item_by_lname[item.name.casefold()] = item
            stats["skybar_items_created"] += 1
            stats["skybar_items_linked"] += 1
            return item

        for sort_i, dish_name in enumerate(sorted(dishes.keys())):
            tmpl, _ = DishTemplate.objects.update_or_create(
                section=ServiceSectionCode.SKYBAR,
                name=dish_name,
                defaults={
                    "mode": DishTemplate.Mode.CHECK,
                    "kind": DishTemplate.Kind.DISH,
                    "category": "skybar",
                    "unit": "ea",
                    "par_level": None,
                    "supports_lounge": False,
                    "active": True,
                    "sort_order": sort_i * 10,
                    "notes": "",
                    "item": None,
                },
            )
            stats["skybar_dishes_upserted"] += 1
            tmpl.components.all().delete()
            comps = []
            seen_comp_keys: set[str] = set()
            for ci, crow in enumerate(dishes[dish_name]):
                cname = crow["item_name"] or dish_name
                # Dedupe identical component names within one dish (CSV glitches)
                key = cname.casefold()
                if key in seen_comp_keys:
                    continue
                seen_comp_keys.add(key)
                item = resolve_item(cname)
                comps.append(
                    DishTemplateComponent(
                        template=tmpl,
                        item=item,
                        supplier_item=None,  # D8 — skybar MEP never invents supplier
                        name="",  # display via item.name
                        planned_qty=None,  # blank ≠ 0; check-mode MEP
                        unit=item.base_unit or "ea",
                        sort_order=ci * 10,
                        notes=crow.get("notes") or "",
                    )
                )
            DishTemplateComponent.objects.bulk_create(comps)
            stats["skybar_components"] += len(comps)
