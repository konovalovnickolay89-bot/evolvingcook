#!/usr/bin/env python3
"""
Catalogue seed from 2026-08-05 Brakes + BPM ordering docs (EXTRACT.md).

Path A: deterministic ORM upsert — Suppliers + Items + SupplierItems only.
No StockMovement / par / walk_order / area invention.

Usage (project root, venv active):
  python scripts/seed_order_docs_2026_08_05.py
  python manage.py shell < scripts/seed_order_docs_2026_08_05.py  # not needed; runs standalone via django setup
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import Q  # noqa: E402

from catalog.models import Item, Supplier, SupplierItem  # noqa: E402

SOURCE = "ordering-docs-2026-08-05"

# (priority, supplier_key, code, name, base_unit, pack_description, pack_qty|None, price|None, unverified, notes)
# supplier_key: "brakes" | "bpm"
# pack_qty only when confidently convertible to base units; else None.
ROWS: list[tuple] = [
    # --- BPM (all DN lines); none ★ on paper but 670HAL/3145N called out in acceptance ---
    (1, "bpm", "3145N", "Short Belly Pork Boned Only", "g", "Nett weight (KG priced)", None, Decimal("6.6700"), False, "weight-priced per KG; DN 657165 PO LONLWD7691"),
    (1, "bpm", "2KO4CS", "Case 50 x 10F Lamb Koftes", "ea", "Case 50 x 10F", None, Decimal("62.0400"), False, "case EACH; DN 657165 PO LONLWD7682"),
    (1, "bpm", "S24", "Cumberland Premium Sausages 4s", "g", "By weight (KG priced)", None, Decimal("4.6100"), False, "weight-priced per KG; DN 657165 PO LONLWD7682"),
    (1, "bpm", "670HAL", "Fresh Chicken Breast Fillets By Weight H", "g", "By weight (KG priced)", None, Decimal("6.7200"), False, "weight-priced per KG; DN 657165 PO LONLWD7682"),
    (1, "bpm", "S4", "Toulouse Sausages", "g", "Unit ambiguous on sheet (KG?)", None, Decimal("10.2600"), True, "check unit on accept — sheet columns crowded; DN 657165 PO LONLWD7682"),
    # --- Brakes ★ priority first ---
    (0, "brakes", "11196", "Sysco Classic Tomato Salsa 1kg", "g", "1x1kg", Decimal("1000"), Decimal("5.6400"), False, "PO LONLWD7683 ★"),
    (0, "brakes", "134773", "The Kitchen Bombay Rice Salad NM 1x2kg", "g", "1x2kg", Decimal("2000"), Decimal("10.2800"), False, "PO LONLWD7683 ★"),
    (0, "brakes", "153395", "The Kitchen Whtberry Basil Salad 1x2kg", "g", "1x2kg", Decimal("2000"), Decimal("14.3300"), False, "PO LONLWD7683 ★"),
    (0, "brakes", "132671", "Applewood Smoky Vegan Slices 1x200g", "g", "1x200g", Decimal("200"), Decimal("2.8200"), False, "PO LONLWD7683 ★"),
    (0, "brakes", "115795", "Kuhne Sauerkraut 6x810g", "g", "6x810g", Decimal("4860"), Decimal("16.1000"), False, "PO LONLWD7683 ★; pack_qty=6*810g"),
    (0, "brakes", "129192", "Sysco 96% Brit Wagyu Beefburger 24x170g", "g", "24x170g", Decimal("4080"), Decimal("49.9400"), False, "PO LONLWD7683 ★; case"),
    (0, "brakes", "130435", "LaBo 9in Vegan Brioche Hot Dog Roll 1x28", "ea", "1x28", Decimal("28"), Decimal("15.1000"), False, "PO LONLWD7683 ★"),
    (0, "brakes", "30927", "Brake 12 SSwt 1/2 Cut Corn Cobs 1x1.35kg", "g", "1x1.35kg", Decimal("1350"), Decimal("2.3000"), False, "PO LONLWD7683 ★"),
    # --- Brakes rest LONLWD7683 frozen ---
    (2, "brakes", "461567", "Judes Truly Chocolate Icecream 24x100ml", "ml", "24x100ml", Decimal("2400"), Decimal("19.9000"), False, "PO LONLWD7683"),
    (2, "brakes", "145916", "Little Judes Watermelon Rockets 24x55ml", "ml", "24x55ml", Decimal("1320"), Decimal("13.6800"), False, "PO LONLWD7683"),
    (2, "brakes", "128859", "Jude Vegan SaltCaramel Icecream 24x100ml", "ml", "24x100ml", Decimal("2400"), Decimal("23.7300"), False, "PO LONLWD7683"),
    (2, "brakes", "461566", "Judes Strawb & Cream Ice Cream 24x100ml", "ml", "24x100ml", Decimal("2400"), Decimal("19.9000"), False, "PO LONLWD7683"),
    (2, "brakes", "136754", "Judes Stickbar Triple Chocolate 20x80ml", "ml", "20x80ml", Decimal("1600"), Decimal("18.5400"), False, "PO LONLWD7683"),
    (2, "brakes", "34484", "McCain OC Beefeater 4x2.27kg", "g", "4x2.27kg", Decimal("9080"), Decimal("14.2000"), False, "PO LONLWD7683"),
    (2, "brakes", "136753", "Judes Stickbar Salted Caramel 20x80ml", "ml", "20x80ml", Decimal("1600"), Decimal("17.1500"), False, "PO LONLWD7683"),
    (2, "brakes", "5002323", "Sysco Classic Extr Virgin Olive Oil 1x5ltr", "ml", "1x5ltr", Decimal("5000"), Decimal("27.0200"), False, "PO LONLWD7683"),
    (2, "brakes", "2908", "Tilda Basmati Rice 1x20Kg", "g", "1x20Kg", Decimal("20000"), Decimal("49.9000"), False, "PO LONLWD7683"),
    (2, "brakes", "34495", "McCain OC Thin Cut 3/8 4x2.27kg", "g", "4x2.27kg", Decimal("9080"), Decimal("14.6000"), False, "PO LONLWD7683"),
    (2, "brakes", "30084", "Sysco Classic Seasoned Wedges 2.5kg", "g", "2.5kg", Decimal("2500"), Decimal("6.0200"), False, "PO LONLWD7683"),
    (2, "brakes", "4242", "Brake Crunchy Breaded Onion Rings 1kg", "g", "1kg", Decimal("1000"), Decimal("2.7400"), False, "PO LONLWD7683"),
    (2, "brakes", "145932", "LaBo Pitta Breads 6x6", "ea", "6x6", Decimal("36"), Decimal("6.3500"), False, "PO LONLWD7683; pack_qty=36 ea"),
    (2, "brakes", "151064", "Hot & Spicy Chicken Wings 1x1kg", "g", "1x1kg", Decimal("1000"), Decimal("4.8500"), False, "PO LONLWD7683"),
    (2, "brakes", "3957", "Brakes Pre Fried Potato Dice 2.5kg", "g", "2.5kg", Decimal("2500"), Decimal("2.9100"), False, "PO LONLWD7683"),
    (2, "brakes", "18422", "GVD Set Soured Cream 1x2kg", "g", "1x2kg", Decimal("2000"), Decimal("8.8400"), False, "PO LONLWD7683"),
    (2, "brakes", "71724", "Fresh Marinated Mixed Olives 1kg", "g", "1kg", Decimal("1000"), Decimal("9.1900"), False, "PO LONLWD7683"),
    (2, "brakes", "152292", "The Kitchen Med Couscous Salad 1x2kg", "g", "1x2kg", Decimal("2000"), Decimal("10.1600"), False, "PO LONLWD7683"),
    (2, "brakes", "149910", "Granarolo Parmigiano Reg Shave 1x500g", "g", "1x500g", Decimal("500"), Decimal("10.2300"), False, "PO LONLWD7683"),
    (2, "brakes", "132508", "BARISTA White Sugar Sachets 1x4000", "ea", "1x4000", Decimal("4000"), Decimal("21.7800"), False, "PO LONLWD7683"),
    (2, "brakes", "132509", "BARISTA Brown Sugar Sachets 1x4000", "ea", "1x4000", Decimal("4000"), Decimal("23.5800"), False, "PO LONLWD7683"),
    (2, "brakes", "100341", "Heinz Salad Cream Ptns 200x12g", "g", "200x12g", Decimal("2400"), Decimal("13.6900"), False, "PO LONLWD7683"),
    (2, "brakes", "145917", "Heinz Vegan Mayonnaise 5Ltr", "ml", "5Ltr", Decimal("5000"), Decimal("18.6200"), False, "PO LONLWD7683"),
    (2, "brakes", "1154", "Jacobs Cream Crackers Minipack 1x168", "ea", "1x168", Decimal("168"), Decimal("31.7600"), False, "PO LONLWD7683"),
    (2, "brakes", "89722", "Sysco Classic Black Bean Sauce 1x2.2kg", "g", "1x2.2kg", Decimal("2200"), Decimal("7.2500"), False, "PO LONLWD7683"),
    (2, "brakes", "10408", "House Recipe Mayo Sachets 1x200", "ea", "1x200", Decimal("200"), Decimal("7.3700"), False, "PO LONLWD7683"),
    (2, "brakes", "129919", "Tyrrells Mature Ched Chive Crisps 24x40g", "g", "24x40g", Decimal("960"), Decimal("11.0200"), False, "PO LONLWD7683"),
    (2, "brakes", "152634", "Sysco Sweet Biscuits Assortment 1x2kg", "g", "1x2kg", Decimal("2000"), Decimal("10.5600"), False, "PO LONLWD7683+LONLWD7673 deduped"),
    (2, "brakes", "21420", "Walkers Ready Salted 48x32.5g", "g", "48x32.5g", Decimal("1560"), Decimal("11.3000"), False, "PO LONLWD7683"),
    (2, "brakes", "135335", "Sysco Classic Guacamole Topping 1x900g", "g", "1x900g", Decimal("900"), Decimal("3.8600"), False, "PO LONLWD7683"),
    (2, "brakes", "133531", "Violife Greek White 1x200g", "g", "1x200g", Decimal("200"), Decimal("2.7500"), False, "PO LONLWD7683"),
    (2, "brakes", "118708", "Diced Butternut Squash 20mm BB 1x1kg", "g", "1x1kg", Decimal("1000"), Decimal("4.4700"), False, "PO LONLWD7683"),
    (2, "brakes", "151449", "Sysco Classic Thai Quinoa Salad 1x2kg", "g", "1x2kg", Decimal("2000"), Decimal("11.4900"), False, "PO LONLWD7683"),
    (2, "brakes", "151919", "Stokes Tomato Ketchup Sachet 80x40g", "g", "80x40g", Decimal("3200"), Decimal("16.1000"), False, "PO LONLWD7683"),
    (2, "brakes", "113253", "Nobbys Nuts Sweet Chilli 20x40g", "g", "20x40g", Decimal("800"), Decimal("9.3000"), False, "PO LONLWD7683"),
    # --- LONLWD7686 ---
    (2, "brakes", "134257", "Heinz Professional Mayonnaise 1x10L", "ml", "1x10L", Decimal("10000"), Decimal("29.8500"), False, "PO LONLWD7686"),
    (2, "brakes", "33582", "Sysco Classic Madras Curry Powder 1x500g", "g", "1x500g", Decimal("500"), Decimal("3.4400"), False, "PO LONLWD7686"),
    (2, "brakes", "450653", "Sweet Potato Wedges BB 1x1kg", "g", "1x1kg", Decimal("1000"), Decimal("5.5100"), False, "PO LONLWD7686"),
    # --- LONLWD7673 biscuits (152634 already listed) ---
    (2, "brakes", "1474", "Brakes Cream Crackers 150x2", "ea", "150x2", Decimal("300"), Decimal("30.0700"), False, "PO LONLWD7673"),
    (2, "brakes", "1475", "Sysco Minipack Biscuits 3pk(x100)", "ea", "3pk x100", Decimal("100"), Decimal("13.4600"), False, "PO LONLWD7673; pack_qty=100 multipacks"),
    (2, "brakes", "35192", "Brakes Ready Salted Crisps 12x150g", "g", "12x150g", Decimal("1800"), Decimal("16.3600"), False, "PO LONLWD7673"),
]


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _append_note(existing: str, extra: str, max_len: int | None = None) -> str:
    existing = existing or ""
    extra = _norm(extra)
    if not extra:
        return existing
    if extra in existing:
        return existing
    out = (existing + " | " + extra).strip(" |") if existing else extra
    if max_len is not None and len(out) > max_len:
        out = out[: max_len - 1].rstrip() + "…"
    return out


def upsert_suppliers() -> dict:
    """Ensure Brakes + British Premium Meats (and keep BRAKES/BPM aliases annotated)."""
    out = {}

    brakes_title, c1 = Supplier.objects.get_or_create(
        name="Brakes",
        defaults={
            "account_code": "1264991",
            "active": True,
            "contact": {
                "customer_ref": "LONLW",
                "contact_name": "Sharon Davies",
                "phone": "0344 800 4019",
                "trading_as": "Brakes / Country Choice of Sysco GB Ltd",
            },
            "notes": (
                f"{SOURCE}: customer 1264991 ref LONLW; "
                "payer WEMBLEY (HOTEL TRADING) LIMITED; site Hilton London Wembley"
            ),
        },
    )
    upd = []
    if brakes_title.account_code != "1264991":
        brakes_title.account_code = "1264991"
        upd.append("account_code")
    if not brakes_title.contact:
        brakes_title.contact = {
            "customer_ref": "LONLW",
            "contact_name": "Sharon Davies",
            "phone": "0344 800 4019",
            "trading_as": "Brakes / Country Choice of Sysco GB Ltd",
        }
        upd.append("contact")
    note = f"{SOURCE}: customer 1264991 ref LONLW"
    if note not in (brakes_title.notes or ""):
        brakes_title.notes = _append_note(brakes_title.notes, note)
        upd.append("notes")
    if upd:
        brakes_title.save(update_fields=upd)
    out["Brakes"] = {"id": brakes_title.id, "created": c1, "account_code": brakes_title.account_code}

    # Dominant existing seed name
    brakes_u = Supplier.objects.filter(name="BRAKES").first()
    if brakes_u:
        u = []
        if brakes_u.account_code != "1264991":
            brakes_u.account_code = "1264991"
            u.append("account_code")
        if SOURCE not in (brakes_u.notes or ""):
            brakes_u.notes = _append_note(
                brakes_u.notes,
                f"{SOURCE}: same account as Brakes (1264991 / LONLW); primary SI host",
            )
            u.append("notes")
        if u:
            brakes_u.save(update_fields=u)
        out["BRAKES"] = {"id": brakes_u.id, "created": False, "account_code": brakes_u.account_code}
    out["brakes_primary_id"] = brakes_u.id if brakes_u else brakes_title.id

    bpm_full, c2 = Supplier.objects.get_or_create(
        name="British Premium Meats",
        defaults={
            "account_code": "06767",
            "active": True,
            "contact": {
                "address": "2 Hyde Way, Welwyn Garden City AL7 3UQ",
                "vat": "442 0676 65",
                "phone": "01707 361 370",
            },
            "notes": (
                f"{SOURCE}: account 06767; deliver Hilton London Wembley / "
                "Wembley Hotel Trading Ltd"
            ),
        },
    )
    u = []
    if bpm_full.account_code != "06767":
        bpm_full.account_code = "06767"
        u.append("account_code")
    if not bpm_full.contact:
        bpm_full.contact = {
            "address": "2 Hyde Way, Welwyn Garden City AL7 3UQ",
            "vat": "442 0676 65",
            "phone": "01707 361 370",
        }
        u.append("contact")
    if SOURCE not in (bpm_full.notes or ""):
        bpm_full.notes = _append_note(bpm_full.notes, f"{SOURCE}: account 06767")
        u.append("notes")
    if u:
        bpm_full.save(update_fields=u)
    out["British Premium Meats"] = {
        "id": bpm_full.id,
        "created": c2,
        "account_code": bpm_full.account_code,
    }

    bpm_short = Supplier.objects.filter(name="BPM").first()
    if bpm_short:
        u = []
        if bpm_short.account_code != "06767":
            bpm_short.account_code = "06767"
            u.append("account_code")
        if SOURCE not in (bpm_short.notes or ""):
            bpm_short.notes = _append_note(
                bpm_short.notes,
                f"{SOURCE}: alias of British Premium Meats account 06767; primary SI host",
            )
            u.append("notes")
        if u:
            bpm_short.save(update_fields=u)
        out["BPM"] = {"id": bpm_short.id, "created": False, "account_code": bpm_short.account_code}
    out["bpm_primary_id"] = bpm_short.id if bpm_short else bpm_full.id

    return out


def brakes_supplier_ids() -> list[int]:
    return list(
        Supplier.objects.filter(
            Q(name__iexact="brakes") | Q(name__iexact="BRAKES")
        ).values_list("id", flat=True)
    )


def bpm_supplier_ids() -> list[int]:
    return list(
        Supplier.objects.filter(
            Q(name__iexact="bpm")
            | Q(name__iexact="British Premium Meats")
            | Q(name__icontains="Premium Meats")
        )
        .exclude(name__icontains=" or ")
        .values_list("id", flat=True)
    )


def find_si_by_code(supplier_ids: list[int], code: str) -> SupplierItem | None:
    code_u = code.strip().upper()
    qs = (
        SupplierItem.objects.filter(supplier_id__in=supplier_ids)
        .select_related("item", "supplier")
        .order_by("id")
    )
    # exact first
    for si in qs:
        if (si.supplier_code or "").strip().upper() == code_u:
            return si
    # BPM sheet 2KO4CS vs existing 2KOF4CS
    if code_u == "2KO4CS":
        for si in qs:
            c = (si.supplier_code or "").strip().upper()
            if c in {"2KOF4CS", "2KO4CS"}:
                return si
    return None


def find_item_by_name(name: str) -> Item | None:
    name_n = _norm(name)
    item = Item.objects.filter(name__iexact=name_n).first()
    if item:
        return item
    # soft matches for known aliases
    aliases = {
        "Sysco 96% Brit Wagyu Beefburger 24x170g": [
            "Wagyu Beefburgers 82% 1x24x170g",
            "Wagyu Beefburger",
        ],
        "Applewood Smoky Vegan Slices 1x200g": [
            "Vegan Applewood cheese",
            "Applewood Smoky Vegan Slices",
        ],
        "Fresh Chicken Breast Fillets By Weight H": [
            "Chicken Breast Fillet",
            "Chicken fillet 140g-170g",
        ],
        "Case 50 x 10F Lamb Koftes": [
            "Lamb koftas",
            "Lamb Koftes",
        ],
        "McCain OC Beefeater 4x2.27kg": [
            "McCain Steak Thick Cut Chips",
            "McCain OC Beefeater",
        ],
        "Short Belly Pork Boned Only": [
            "Short Belly Pork",
            "Belly Pork",
        ],
        "Cumberland Premium Sausages 4s": [
            "Cumberland sausage",
            "Cumberland Sausages",
            "Sausage",
        ],
        "Toulouse Sausages": [
            "Toulouse sausage",
            "Toulouse Sausage",
        ],
    }
    for alt in aliases.get(name_n, []):
        item = Item.objects.filter(name__iexact=alt).first()
        if item:
            return item
        item = Item.objects.filter(name__icontains=alt).first()
        if item:
            return item
    return None


def unique_item_name(desired: str) -> str:
    desired = _norm(desired)
    if not Item.objects.filter(name=desired).exists():
        return desired
    # name taken by different product — disambiguate with source tag only if needed at create time
    return desired


@transaction.atomic
def run() -> dict:
    stats = {
        "suppliers": {},
        "rows": 0,
        "items_created": 0,
        "items_matched": 0,
        "si_created": 0,
        "si_updated": 0,
        "si_unchanged": 0,
        "skipped": 0,
        "unverified_rows": 0,
        "priority_ok": {},
        "blocked": [],
        "details": [],
    }
    stats["suppliers"] = upsert_suppliers()
    brakes_ids = brakes_supplier_ids()
    bpm_ids = bpm_supplier_ids()
    brakes_primary = Supplier.objects.get(pk=stats["suppliers"]["brakes_primary_id"])
    bpm_primary = Supplier.objects.get(pk=stats["suppliers"]["bpm_primary_id"])
    # Also ensure SI can live on formal names when primary is alias
    brakes_formal = Supplier.objects.get(name="Brakes")
    bpm_formal = Supplier.objects.get(name="British Premium Meats")

    # Fix known mis-link: 670HAL on Brakes for chicken — BPM code on DN
    wrong = (
        SupplierItem.objects.filter(supplier_id__in=brakes_ids, supplier_code__iexact="670HAL")
        .select_related("item", "supplier")
    )
    for si in wrong:
        note = f"{SOURCE}: code 670HAL is BPM on DN 657165 — Brakes link needs verify"
        si.unverified = True
        si.notes = _append_note(si.notes, note)
        si.save(update_fields=["unverified", "notes"])
        stats["details"].append(
            {
                "action": "flag_mislinked_code",
                "supplier": si.supplier.name,
                "code": "670HAL",
                "item": si.item.name,
                "si_id": si.id,
            }
        )

    sorted_rows = sorted(ROWS, key=lambda r: (r[0], r[1], r[2]))
    seen_codes: set[tuple[str, str]] = set()

    for priority, sk, code, name, base_unit, pack_desc, pack_qty, price, unverified, notes in sorted_rows:
        stats["rows"] += 1
        code = _norm(code)
        name = _norm(name)
        key = (sk, code.upper())
        if key in seen_codes:
            stats["skipped"] += 1
            stats["details"].append({"action": "skip_dup_in_batch", "code": code, "sk": sk})
            continue
        seen_codes.add(key)

        if unverified:
            stats["unverified_rows"] += 1

        supplier_ids = brakes_ids if sk == "brakes" else bpm_ids
        primary = brakes_primary if sk == "brakes" else bpm_primary
        formal = brakes_formal if sk == "brakes" else bpm_formal

        existing_si = find_si_by_code(supplier_ids, code)
        item = None
        if existing_si:
            item = existing_si.item
            stats["items_matched"] += 1
        else:
            item = find_item_by_name(name)
            if item:
                stats["items_matched"] += 1
            else:
                # create with unique name
                item_name = name
                if Item.objects.filter(name=item_name).exists():
                    # should have been found — use as-is match failure path
                    item = Item.objects.get(name=item_name)
                    stats["items_matched"] += 1
                else:
                    item = Item.objects.create(
                        name=item_name,
                        base_unit=base_unit,
                        category="purchasing",
                        active=True,
                        unverified=unverified,
                        notes=_append_note("", f"{SOURCE}: {notes}", max_len=500),
                    )
                    stats["items_created"] += 1

        # Soft-update item: do not change base_unit if already set differently unless default ea and we know better
        item_upd = []
        if unverified and not item.unverified:
            item.unverified = True
            item_upd.append("unverified")
        src_note = f"{SOURCE} code {code}"
        if src_note not in (item.notes or ""):
            item.notes = _append_note(item.notes, f"{src_note}; {notes}", max_len=500)
            item_upd.append("notes")
        # Only set base_unit when item was just created path already set; if matched and unit is ea and we have g/ml confident, upgrade carefully
        if (
            item.base_unit == Item.BaseUnit.EA
            and base_unit in (Item.BaseUnit.G, Item.BaseUnit.ML)
            and pack_qty is not None
            and not existing_si
        ):
            # leave existing ALC ea items alone if they already have SI history
            if not item.supplier_items.exists():
                item.base_unit = base_unit
                item_upd.append("base_unit")
        if item_upd:
            item.save(update_fields=item_upd)

        note_blob = f"{SOURCE}: {notes}"

        def apply_si(si: SupplierItem, created: bool) -> None:
            fields = []
            if (si.supplier_code or "").strip().upper() != code.upper():
                # keep alternate code in notes if different (2KOF4CS)
                if si.supplier_code and si.supplier_code.strip().upper() != code.upper():
                    si.notes = _append_note(
                        si.notes, f"sheet_code {code} (existing {si.supplier_code})"
                    )
                    if "notes" not in fields:
                        fields.append("notes")
                    # Prefer sheet code when existing looks like OCR variant
                    if code.upper() == "2KO4CS" and si.supplier_code.strip().upper() == "2KOF4CS":
                        si.notes = _append_note(si.notes, "kept existing code 2KOF4CS; sheet also 2KO4CS")
                    else:
                        si.supplier_code = code
                        fields.append("supplier_code")
                else:
                    si.supplier_code = code
                    fields.append("supplier_code")
            elif not si.supplier_code:
                si.supplier_code = code
                fields.append("supplier_code")

            if pack_desc and pack_desc not in (si.pack_description or ""):
                if not si.pack_description:
                    si.pack_description = pack_desc
                    fields.append("pack_description")
                else:
                    si.notes = _append_note(si.notes, f"pack_seen: {pack_desc}")
                    if "notes" not in fields:
                        fields.append("notes")

            if si.pack_qty is None and pack_qty is not None:
                si.pack_qty = pack_qty
                fields.append("pack_qty")

            if price is not None:
                if si.price is None or si.price != price:
                    si.price = price
                    fields.append("price")

            if unverified and not si.unverified:
                si.unverified = True
                fields.append("unverified")

            if note_blob not in (si.notes or ""):
                si.notes = _append_note(si.notes, note_blob)
                if "notes" not in fields:
                    fields.append("notes")

            if not si.active:
                si.active = True
                fields.append("active")

            if created:
                stats["si_created"] += 1
                action = "si_created"
            elif fields:
                si.save(update_fields=fields)
                stats["si_updated"] += 1
                action = "si_updated"
            else:
                stats["si_unchanged"] += 1
                action = "si_unchanged"

            stats["details"].append(
                {
                    "action": action,
                    "priority": priority,
                    "sk": sk,
                    "code": code,
                    "si_id": si.id,
                    "supplier": si.supplier.name,
                    "item_id": item.id,
                    "item": item.name,
                    "price": str(si.price) if si.price is not None else None,
                    "pack_qty": str(si.pack_qty) if si.pack_qty is not None else None,
                    "unverified": si.unverified,
                    "fields": fields if not created else ["all_defaults"],
                }
            )

        if existing_si:
            apply_si(existing_si, created=False)
            # Ensure formal supplier also has a link to same item when different row
            if formal.id != existing_si.supplier_id:
                formal_si = SupplierItem.objects.filter(supplier=formal, item=item).first()
                if not formal_si:
                    # Don't duplicate preferred catalogs across name variants automatically —
                    # only ensure primary host holds the code. Formal name supplier is for acceptance presence.
                    pass
        else:
            # Prefer SI on primary (BRAKES / BPM) for dedupe with historic seed
            si, created = SupplierItem.objects.get_or_create(
                supplier=primary,
                item=item,
                defaults={
                    "supplier_code": code,
                    "pack_description": pack_desc or "",
                    "pack_qty": pack_qty,
                    "price": price,
                    "preferred": True,
                    "active": True,
                    "unverified": unverified or not code,
                    "notes": note_blob,
                },
            )
            if created:
                apply_si(si, created=True)
            else:
                # same supplier+item existed under different/empty code
                apply_si(si, created=False)

            # If primary is alias, also ensure formal supplier has SI (acceptance names)
            if formal.id != primary.id:
                fsi, fcreated = SupplierItem.objects.get_or_create(
                    supplier=formal,
                    item=item,
                    defaults={
                        "supplier_code": code,
                        "pack_description": pack_desc or "",
                        "pack_qty": pack_qty,
                        "price": price,
                        "preferred": False,
                        "active": True,
                        "unverified": unverified or not code,
                        "notes": note_blob + f" | mirror of {primary.name}",
                    },
                )
                if fcreated:
                    stats["si_created"] += 1
                    stats["details"].append(
                        {
                            "action": "si_created_formal_mirror",
                            "code": code,
                            "si_id": fsi.id,
                            "supplier": formal.name,
                            "item": item.name,
                        }
                    )
                else:
                    # fill blanks on mirror only
                    ffields = []
                    if not fsi.supplier_code:
                        fsi.supplier_code = code
                        ffields.append("supplier_code")
                    if fsi.price is None and price is not None:
                        fsi.price = price
                        ffields.append("price")
                    if fsi.pack_qty is None and pack_qty is not None:
                        fsi.pack_qty = pack_qty
                        ffields.append("pack_qty")
                    if ffields:
                        fsi.save(update_fields=ffields)
                        stats["si_updated"] += 1

    # Acceptance probes
    priority_codes = {
        "brakes": ["11196", "134773", "153395", "132671", "115795", "129192", "130435", "30927"],
        "bpm": ["670HAL", "3145N", "2KO4CS", "S24", "S4"],
    }
    for sk, codes in priority_codes.items():
        ids = brakes_ids if sk == "brakes" else bpm_ids
        for c in codes:
            si = find_si_by_code(ids, c)
            # also accept formal-only
            if not si:
                all_ids = list(Supplier.objects.values_list("id", flat=True))
                si = find_si_by_code(all_ids, c)
            stats["priority_ok"][f"{sk}:{c}"] = (
                {
                    "ok": True,
                    "si_id": si.id,
                    "supplier": si.supplier.name,
                    "item": si.item.name,
                    "supplier_code": si.supplier_code,
                    "price": str(si.price) if si.price is not None else None,
                }
                if si
                else {"ok": False}
            )
            if not si:
                stats["blocked"].append({"code": c, "sk": sk, "reason": "missing after upsert"})

    stats["counts_after"] = {
        "items": Item.objects.count(),
        "suppliers": Supplier.objects.count(),
        "supplier_items": SupplierItem.objects.count(),
    }
    return stats


def main() -> int:
    stats = run()
    print(json.dumps(stats, indent=2, default=str))
    # hard fail if priority missing
    bad = [k for k, v in stats["priority_ok"].items() if not v.get("ok")]
    if bad:
        print("PRIORITY_FAIL", bad, file=sys.stderr)
        return 1
    print("SEED_ORDER_DOCS_OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
