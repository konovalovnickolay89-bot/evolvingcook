"""
Seed the Skybar 9 EVENT DAY menu as skybar dish templates.

Source: sheets/skybar-event-menu-2026-10.csv — transcribed from the
printed event-day menu (bar bites, sides, burgers, pizza). Prices and
V/PB flags live in the template notes; components become check-mode
ingredients so the ordering board can show "what goes in".

Conventions follow seed_dish_templates: update_or_create by
(section, name); components rebuilt idempotently; Items get_or_create
by name (case-insensitive), supplier never attached (D8); if the sheet
is missing, skip and report — never invent.

Usage:
  python manage.py seed_skybar_event_menu
"""
from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item
from planning.models import (
    DishTemplate,
    DishTemplateComponent,
    ServiceSectionCode,
)

SHEET = "skybar-event-menu-2026-10.csv"


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


class Command(BaseCommand):
    help = "Seed Skybar event-day menu dish templates from sheets/" + SHEET

    def add_arguments(self, parser):
        parser.add_argument(
            "--sheets-dir",
            default="",
            help="Override sheets directory (default: <BASE_DIR>/sheets)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        sheets_dir = Path(options["sheets_dir"] or (Path(settings.BASE_DIR) / "sheets"))
        path = sheets_dir / SHEET
        if not path.is_file():
            self.stdout.write(
                self.style.WARNING(f"{SHEET} MISSING — not inventing the menu")
            )
            return

        item_by_lname = {i.name.casefold(): i for i in Item.objects.all()}
        created_items = 0
        linked_items = 0

        def resolve_item(component_name: str) -> Item:
            nonlocal created_items, linked_items
            hit = item_by_lname.get(component_name.casefold())
            if hit is not None:
                linked_items += 1
                return hit
            item = Item.objects.create(
                name=component_name,
                base_unit=Item.BaseUnit.EA,
                active=True,
                category="skybar",
                notes="seed:" + SHEET,
            )
            item_by_lname[item.name.casefold()] = item
            created_items += 1
            return item

        dishes = 0
        components = 0
        with path.open(newline="", encoding="utf-8") as fh:
            for sort_i, row in enumerate(csv.DictReader(fh)):
                dish = _norm(row.get("dish") or "")
                if not dish:
                    continue
                tmpl, _ = DishTemplate.objects.update_or_create(
                    section=ServiceSectionCode.SKYBAR,
                    name=dish,
                    defaults={
                        "mode": DishTemplate.Mode.CHECK,
                        "kind": DishTemplate.Kind.DISH,
                        "category": _norm(row.get("category") or "") or "skybar",
                        "unit": "ea",
                        "par_level": None,
                        "supports_lounge": False,
                        "active": True,
                        "sort_order": sort_i * 10,
                        "notes": _norm(row.get("note") or ""),
                        "item": None,
                    },
                )
                dishes += 1

                tmpl.components.all().delete()
                comps = []
                for ci, raw in enumerate(
                    (row.get("components") or "").split("|")
                ):
                    comp_name = _norm(raw)
                    if not comp_name:
                        continue
                    item = resolve_item(comp_name)
                    comps.append(
                        DishTemplateComponent(
                            template=tmpl,
                            item=item,
                            supplier_item=None,  # D8: never invent supplier
                            name="",
                            planned_qty=None,  # blank ≠ 0
                            unit=item.base_unit,
                            sort_order=ci * 10,
                            notes="",
                        )
                    )
                DishTemplateComponent.objects.bulk_create(comps)
                components += len(comps)

        self.stdout.write(self.style.SUCCESS("seed_skybar_event_menu complete"))
        self.stdout.write(
            f"dishes={dishes} components={components} "
            f"items_created={created_items} items_linked={linked_items}"
        )
        self.stdout.write(
            "Note: templates feed NEW boards. For an already-open day, tap "
            "'Update menu' on the skybar board (or re-open the section) to "
            "pull the new lines."
        )
