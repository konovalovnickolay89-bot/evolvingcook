"""
Switch à la carte to the Made Social menu (Oct 2026).

Source: sheets/a-la-carte-menu-2026-10.csv — transcribed from the printed
"coming soon" menu (food side only; drinks are bar stock).

Per row:
  - `replaces` names an existing ALC template (KitchenCut sheet name):
    rename it to the new dish name, keep its components and line history
    (lines link by template FK). `components` on these rows lists only
    curated ADDITIONS (catalogue names) — empty means nothing to add.
    Tagged "CHANGED" in notes.
  - no `replaces`: new template, components from the sheet. Tagged "NEW".
Old menu dishes in RETIRE are set inactive (kept, never deleted).
KIDS * and desserts are untouched (separate menus).

Conventions follow seed_skybar_event_menu: components are check-mode,
planned_qty null (blank ≠ 0), supplier never attached (D8), Items
get_or_create by name (case-insensitive). Missing sheet → skip, never invent.

Templates feed NEW boards. An already-open day keeps its lines; tap
"Update menu" on that board to pull new ones.

NB: seed_dish_templates --alc-only upserts the OLD uppercase names — do not
re-run it after this, or the retired/renamed dishes come back.

Usage:
  python manage.py seed_alc_menu_2026_10            # dry run, prints plan
  python manage.py seed_alc_menu_2026_10 --apply
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

SHEET = "a-la-carte-menu-2026-10.csv"
TAG = "Oct 26 menu"

# Old-menu dishes with no place on the new sheet (desserts / kids excluded).
RETIRE = [
    "CAVOLO NERO, GARLIC AND CHILLI",
    "CREAMED SAVOY CABBAGE WITH BACON",
    "FOCACCIA PIZZA — CHARRED AUBERGINE, WHIPPED FETA, PESTO AND ROCKET",
    "GARDEN SALAD",
    "GARLIC AND HERB FOCACCIA",
    "HOT DIP",  # pretzel rarebit — not the new Dips
    "HOUSE SALAD",
    "MALAY CURRY CHICKEN AND MANGO SALAD",
    "NDUJA AND CAVOLO NERO FIORELLI",
    "NONNA'S AND CAVOLO NERO FIORELLI",
    "NOURISH BOWL",
    "PLANET BURGER",
    "SEASONAL SOUP OF THE DAY",
    "SIGNATURE STEAK SAUCE",
    "SLOW COOKED PORK BELLY AND SALSA VERDE",
    "TRUFFLE AND PARMESAN FRIES",
]

# Kept on boards after the new menu, in their existing relative order.
KEEP_AFTER_SORT = 1000


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _key(s: str) -> str:
    return _norm(s).casefold().replace(" ", "")


class Command(BaseCommand):
    help = "Switch a_la_carte dish templates to sheets/" + SHEET

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write (default: dry run)")
        parser.add_argument(
            "--sheets-dir",
            default="",
            help="Override sheets directory (default: <BASE_DIR>/sheets)",
        )

    def handle(self, *args, **options):
        sheets_dir = Path(options["sheets_dir"] or (Path(settings.BASE_DIR) / "sheets"))
        path = sheets_dir / SHEET
        if not path.is_file():
            self.stdout.write(self.style.WARNING(f"{SHEET} MISSING — not inventing the menu"))
            return
        with path.open(newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if _norm(r.get("dish") or "")]

        apply = options["apply"]
        try:
            with transaction.atomic():
                self._run(rows, apply)
                if not apply:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written. Re-run with --apply."))
            return
        self.stdout.write(self.style.SUCCESS("seed_alc_menu_2026_10 applied"))

    def _run(self, rows: list[dict], apply: bool) -> None:
        alc = ServiceSectionCode.A_LA_CARTE
        by_name = {t.name: t for t in DishTemplate.objects.filter(section=alc)}
        item_by_lname = {i.name.casefold(): i for i in Item.objects.all()}
        counts = {"changed": 0, "new": 0, "retired": 0, "comps_added": 0, "items_created": 0}

        def resolve_item(name: str) -> Item:
            hit = item_by_lname.get(name.casefold())
            if hit is not None:
                return hit
            item = Item.objects.create(
                name=name,
                base_unit=Item.BaseUnit.EA,
                active=True,
                category="a_la_carte",
                notes="seed:" + SHEET,
            )
            item_by_lname[name.casefold()] = item
            counts["items_created"] += 1
            return item

        def comp_name(c: DishTemplateComponent) -> str:
            return c.item.name if c.item_id else c.name

        # Push everything not on the new menu (kids, desserts, own dishes) after it.
        for t in by_name.values():
            if t.sort_order < KEEP_AFTER_SORT:
                t.sort_order += KEEP_AFTER_SORT
                t.save(update_fields=["sort_order"])

        for sort_i, row in enumerate(rows):
            dish = _norm(row["dish"])
            old = _norm(row.get("replaces") or "")
            note = _norm(row.get("note") or "")
            wanted = [_norm(c) for c in (row.get("components") or "").split("|") if _norm(c)]

            if old:
                tmpl = by_name.get(old) or by_name.get(dish)
                if tmpl is None:
                    raise SystemExit(f"replaces={old!r} not found for {dish!r} — fix the sheet")
                status = "CHANGED"
                counts["changed"] += 1
                # Drop exact duplicate components (same item, no qty) on the way.
                seen: set[tuple] = set()
                for c in list(tmpl.components.order_by("sort_order", "id")):
                    k = (c.item_id, _key(c.name), c.planned_qty, c.unit)
                    if k in seen:
                        c.delete()
                    seen.add(k)
            else:
                tmpl = by_name.get(dish)
                status = "NEW"
                if tmpl is None:
                    tmpl = DishTemplate(section=alc, name=dish)
                counts["new"] += 1

            before = tmpl.name if tmpl.pk else "—"
            tmpl.name = dish
            tmpl.mode = DishTemplate.Mode.CHECK
            tmpl.kind = (
                DishTemplate.Kind.SAUCE if row.get("category") == "grill_sauces" else DishTemplate.Kind.DISH
            )
            tmpl.category = _norm(row.get("category") or "") or "a_la_carte"
            tmpl.unit = tmpl.unit or "ea"
            tmpl.active = True
            tmpl.sort_order = sort_i * 10
            tmpl.notes = f"{status} · {TAG} · {note}" if note else f"{status} · {TAG}"
            tmpl.save()

            have = [comp_name(c) for c in tmpl.components.all()] if tmpl.pk else []
            have_keys = [_key(h) for h in have]
            added = []
            next_sort = (max((c.sort_order for c in tmpl.components.all()), default=-10) + 10)
            for name in wanted:
                k = _key(name)
                # Loose match so "Lamb koftas" covers "lamb kofta", "Squid" covers "Tempura squid".
                if any(k in h or h in k for h in have_keys):
                    continue
                item = resolve_item(name)
                DishTemplateComponent.objects.create(
                    template=tmpl,
                    item=item,
                    supplier_item=None,  # D8: never invent supplier
                    name="",
                    planned_qty=None,  # blank ≠ 0
                    unit=item.base_unit,
                    sort_order=next_sort,
                    notes="",
                )
                next_sort += 10
                have_keys.append(k)
                added.append(name)
            counts["comps_added"] += len(added)

            label = f"{status:8} {dish}"
            if status == "CHANGED" and before != dish:
                label += f"   (was {before})"
            self.stdout.write(label)
            if added:
                self.stdout.write(f"           + {', '.join(added)}")

        for name in RETIRE:
            t = by_name.get(name)
            if t is None:
                self.stdout.write(self.style.WARNING(f"RETIRE   {name} — not found, skipped"))
                continue
            if t.active:
                t.active = False
                t.notes = f"off-menu · retired for {TAG}"
                t.save(update_fields=["active", "notes"])
                counts["retired"] += 1
                self.stdout.write(f"RETIRE   {name}")

        on_menu = {_norm(r["dish"]) for r in rows}
        left = sorted(
            t.name
            for t in DishTemplate.objects.filter(section=alc, active=True)
            if t.name not in on_menu
        )
        self.stdout.write(f"\nStill active, not on new menu ({len(left)}): " + " / ".join(left))
        self.stdout.write(
            " ".join(f"{k}={v}" for k, v in counts.items())
            + (" (would)" if not apply else "")
        )


class _DryRun(Exception):
    pass
