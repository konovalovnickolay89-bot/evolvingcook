#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from catalog.models import Item, Supplier, SupplierItem  # noqa: E402


def dump_sup(name: str) -> dict:
    s = Supplier.objects.get(name=name)
    return {
        "id": s.id,
        "name": s.name,
        "account_code": s.account_code,
        "contact": s.contact,
        "active": s.active,
        "supplier_items": s.supplier_items.count(),
        "notes_head": (s.notes or "")[:240],
    }


def main() -> None:
    priority_codes = [
        "11196",
        "134773",
        "153395",
        "132671",
        "115795",
        "129192",
        "130435",
        "30927",
        "670HAL",
        "3145N",
        "2KO4CS",
        "S24",
        "S4",
    ]
    priority = {}
    for code in priority_codes:
        qs = (
            SupplierItem.objects.filter(supplier_code__iexact=code)
            .select_related("supplier", "item")
            .order_by("id")
        )
        priority[code] = [
            {
                "si_id": si.id,
                "supplier_id": si.supplier_id,
                "supplier": si.supplier.name,
                "item_id": si.item_id,
                "item": si.item.name,
                "base_unit": si.item.base_unit,
                "supplier_code": si.supplier_code,
                "price": str(si.price) if si.price is not None else None,
                "pack_qty": str(si.pack_qty) if si.pack_qty is not None else None,
                "pack_description": si.pack_description,
                "unverified": si.unverified,
            }
            for si in qs
        ]

    unverified = []
    for si in SupplierItem.objects.filter(
        notes__icontains="ordering-docs-2026-08-05", unverified=True
    ).select_related("supplier", "item"):
        unverified.append(
            {
                "si_id": si.id,
                "supplier": si.supplier.name,
                "code": si.supplier_code,
                "item": si.item.name,
                "reason": si.notes,
            }
        )

    extract_codes = [
        "3145N",
        "2KO4CS",
        "S24",
        "670HAL",
        "S4",
        "129192",
        "461567",
        "145916",
        "128859",
        "461566",
        "136754",
        "34484",
        "136753",
        "5002323",
        "2908",
        "34495",
        "130435",
        "30084",
        "30927",
        "4242",
        "145932",
        "151064",
        "3957",
        "11196",
        "18422",
        "71724",
        "152292",
        "134773",
        "153395",
        "132671",
        "149910",
        "115795",
        "132508",
        "132509",
        "100341",
        "145917",
        "1154",
        "89722",
        "10408",
        "129919",
        "152634",
        "21420",
        "135335",
        "133531",
        "118708",
        "151449",
        "151919",
        "113253",
        "134257",
        "33582",
        "450653",
        "1474",
        "1475",
        "35192",
    ]
    missing = [
        c
        for c in extract_codes
        if not SupplierItem.objects.filter(supplier_code__iexact=c).exists()
    ]

    stats = json.loads(Path("/tmp/seed_order_out.json").read_text())
    data = {
        "suppliers": {
            n: dump_sup(n)
            for n in ["Brakes", "BRAKES", "British Premium Meats", "BPM"]
        },
        "priority": priority,
        "unverified": unverified,
        "meta": {
            "seed_stats_initial_run": {k: stats[k] for k in stats if k != "details"},
            "post_fix_counts": {
                "items": Item.objects.count(),
                "suppliers": Supplier.objects.count(),
                "supplier_items": SupplierItem.objects.count(),
            },
            "extract_codes": len(extract_codes),
            "extract_codes_missing": missing,
        },
    }
    Path("/tmp/report_data_clean.json").write_text(json.dumps(data, indent=2, default=str))
    print(json.dumps({"missing": missing, "unverified_n": len(unverified), "counts": data["meta"]["post_fix_counts"]}))


if __name__ == "__main__":
    main()
