"""
Seed Phase 1 catalogue:
  - storage areas (walk_order null) — includes locked 8 + meat fridge
  - ALC dish sheets (dedupe supplier+code; verify/uncertain → unverified)
  - never invent codes/prices/packs; base_unit defaults to ea (no unit on sheets)
  - skybar-mep-list.csv intentionally skipped if missing

Usage:
  python manage.py seed_catalog
  python manage.py seed_catalog --sheets-only
  python manage.py seed_catalog --areas-only
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Item, StorageArea, Supplier, SupplierItem

STORAGE_AREAS: list[tuple[str, str]] = [
    ("main freezer", StorageArea.Kind.FREEZER),
    ("veg fridge", StorageArea.Kind.WALKIN),
    ("dairy+breakfast fridge", StorageArea.Kind.WALKIN),
    ("breakfast freezer", StorageArea.Kind.FREEZER),
    ("dry store", StorageArea.Kind.DRY),
    ("fruit+pastry fridge", StorageArea.Kind.WALKIN),
    ("pastry freezer", StorageArea.Kind.FREEZER),
    ("a la carte fridge", StorageArea.Kind.SECTION),
    # Added 2026-08-03 (Mykola): protein cold hold
    ("meat fridge", StorageArea.Kind.WALKIN),
]

ALC_SHEETS = (
    "alc-dish-sheet-p1.csv",
    "alc-dish-sheet-p2.csv",
    # 2026-08-04 full ordering-guide capture (menu MEP + kids + catalog extras)
    "alc-dish-sheet-p3.csv",
    "alc-dish-sheet-p4-catalog-extras.csv",
)

VERIFY_RE = re.compile(
    r"\b(verify|uncertain|truncated|likely|alternative|or brakes|or brakes)\b",
    re.I,
)


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _looks_unverified(notes: str, supplier: str, code: str) -> bool:
    blob = f"{notes} {supplier} {code}"
    if VERIFY_RE.search(blob):
        return True
    if " / " in (code or "") and "dual" in (notes or "").lower():
        # dual code is recorded as-is; not automatically unverified unless notes say
        pass
    if re.search(r"\bor\b", supplier or "", re.I):
        return True
    if "/" in (supplier or "") and "ESSENTIAL" in (supplier or "").upper():
        return True
    return False


class Command(BaseCommand):
    help = "Seed storage areas + ALC catalogue CSVs (Phase 1)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--areas-only",
            action="store_true",
            help="Only seed storage areas (idempotent get_or_create)",
        )
        parser.add_argument(
            "--sheets-only",
            action="store_true",
            help="Only seed ALC CSVs (areas must already exist)",
        )
        parser.add_argument(
            "--sheets-dir",
            default="",
            help="Override sheets directory (default: <BASE_DIR>/sheets)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        sheets_dir = Path(options["sheets_dir"] or (Path(settings.BASE_DIR) / "sheets"))
        do_areas = not options["sheets_only"]
        do_sheets = not options["areas_only"]

        area_stats = {"created": 0, "existed": 0}
        if do_areas:
            area_stats = self._seed_areas()

        sheet_stats = {
            "rows": 0,
            "items_created": 0,
            "items_existed": 0,
            "suppliers_created": 0,
            "si_created": 0,
            "si_reused": 0,
            "skipped": 0,
            "unverified": 0,
            "files": [],
            "missing": [],
        }
        if do_sheets:
            sheet_stats = self._seed_sheets(sheets_dir)

        self.stdout.write(self.style.SUCCESS("seed_catalog complete"))
        self.stdout.write(f"areas: {area_stats}")
        self.stdout.write(f"sheets: {sheet_stats}")
        self.stdout.write(
            f"counts: items={Item.objects.count()} "
            f"suppliers={Supplier.objects.count()} "
            f"supplier_items={SupplierItem.objects.count()} "
            f"areas={StorageArea.objects.count()}"
        )

    def _seed_areas(self) -> dict:
        created = existed = 0
        for name, kind in STORAGE_AREAS:
            _, was_created = StorageArea.objects.get_or_create(
                name=name,
                defaults={
                    "kind": kind,
                    "walk_order": None,
                    "active": True,
                },
            )
            if was_created:
                created += 1
            else:
                existed += 1
        # Do not delete extras; seed is additive get_or_create
        return {"created": created, "existed": existed, "total": StorageArea.objects.count()}

    def _seed_sheets(self, sheets_dir: Path) -> dict:
        stats = {
            "rows": 0,
            "items_created": 0,
            "items_existed": 0,
            "suppliers_created": 0,
            "si_created": 0,
            "si_reused": 0,
            "skipped": 0,
            "unverified": 0,
            "files": [],
            "missing": [],
            "code_index_hits": 0,
        }
        # Dedupe map: (supplier_key, code_key) -> SupplierItem
        code_index: dict[tuple[str, str], SupplierItem] = {}
        for si in SupplierItem.objects.select_related("supplier", "item"):
            sk = si.supplier.name.strip().upper()
            ck = (si.supplier_code or "").strip().upper()
            if ck:
                code_index[(sk, ck)] = si

        skybar = sheets_dir / "skybar-mep-list.csv"
        if not skybar.is_file():
            stats["missing"].append("skybar-mep-list.csv")
            self.stdout.write(
                self.style.WARNING(
                    "skybar-mep-list.csv MISSING — seeding ALC only; not inventing skybar"
                )
            )

        for fname in ALC_SHEETS:
            path = sheets_dir / fname
            if not path.is_file():
                stats["missing"].append(fname)
                self.stdout.write(self.style.ERROR(f"missing sheet: {path}"))
                continue
            stats["files"].append(fname)
            with path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    stats["rows"] += 1
                    item_name = _norm(row.get("item") or "")
                    supplier_name = _norm(row.get("supplier") or "")
                    code = _norm(row.get("supplier_code") or "")
                    notes = _norm(row.get("notes") or "")
                    dish = _norm(row.get("dish") or "")

                    if not item_name:
                        stats["skipped"] += 1
                        continue

                    unverified = _looks_unverified(notes, supplier_name, code)
                    note_parts = []
                    if dish:
                        note_parts.append(f"dish: {dish}")
                    if notes:
                        note_parts.append(notes)
                    note_blob = " | ".join(note_parts)

                    # Dedupe on (supplier, code) when code present
                    sk = supplier_name.upper() if supplier_name else ""
                    ck = code.upper() if code else ""
                    if sk and ck and (sk, ck) in code_index:
                        si = code_index[(sk, ck)]
                        stats["si_reused"] += 1
                        stats["code_index_hits"] += 1
                        # If names differ, flag and annotate — do not invent a second code row
                        if si.item.name != item_name:
                            extra = f"also-seen-as: {item_name}"
                            if extra not in (si.notes or ""):
                                si.notes = (si.notes + " | " + extra).strip(" |")
                            if note_blob and note_blob not in (si.notes or ""):
                                si.notes = (si.notes + " | " + note_blob).strip(" |")
                            si.unverified = True
                            si.save(update_fields=["notes", "unverified"])
                            if not si.item.unverified:
                                si.item.unverified = True
                                if note_blob and note_blob not in (si.item.notes or ""):
                                    si.item.notes = (
                                        si.item.notes + " | " + note_blob
                                    ).strip(" |")
                                    si.item.save(update_fields=["unverified", "notes"])
                                else:
                                    si.item.save(update_fields=["unverified"])
                            stats["unverified"] += 1
                        continue

                    item, item_created = Item.objects.get_or_create(
                        name=item_name,
                        defaults={
                            "base_unit": Item.BaseUnit.EA,
                            "active": True,
                            "unverified": unverified,
                            "notes": note_blob,
                            "category": "a_la_carte",
                        },
                    )
                    if item_created:
                        stats["items_created"] += 1
                    else:
                        stats["items_existed"] += 1
                        upd = []
                        if unverified and not item.unverified:
                            item.unverified = True
                            upd.append("unverified")
                        if note_blob and note_blob not in (item.notes or ""):
                            item.notes = (item.notes + " | " + note_blob).strip(" |")
                            upd.append("notes")
                        if upd:
                            item.save(update_fields=upd)

                    if unverified:
                        stats["unverified"] += 1

                    if not supplier_name:
                        # Item-only row is valid (partial catalogue)
                        continue

                    supplier, sup_created = Supplier.objects.get_or_create(
                        name=supplier_name,
                        defaults={"active": True},
                    )
                    if sup_created:
                        stats["suppliers_created"] += 1

                    si, si_created = SupplierItem.objects.get_or_create(
                        supplier=supplier,
                        item=item,
                        defaults={
                            "supplier_code": code,
                            "pack_qty": None,  # never invent
                            "price": None,  # never invent
                            "preferred": True,
                            "active": True,
                            "unverified": unverified or not code,
                            "notes": note_blob,
                        },
                    )
                    if si_created:
                        stats["si_created"] += 1
                        if code:
                            code_index[(sk, ck)] = si
                    else:
                        stats["si_reused"] += 1
                        upd = []
                        if not si.supplier_code and code:
                            si.supplier_code = code
                            upd.append("supplier_code")
                        if unverified and not si.unverified:
                            si.unverified = True
                            upd.append("unverified")
                        if note_blob and note_blob not in (si.notes or ""):
                            si.notes = (si.notes + " | " + note_blob).strip(" |")
                            upd.append("notes")
                        if upd:
                            si.save(update_fields=upd)
                        if code:
                            code_index[(sk, ck)] = si

        return stats
