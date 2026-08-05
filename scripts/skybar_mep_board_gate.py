#!/usr/bin/env python3
"""Skybar MEP dish-template seed + board gate (self-contained; no mgmt command name)."""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path("/home/discovery-system/src/evolving-cook")
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.db import transaction
from django.db.models import Count

from catalog.models import Item
from planning.models import (
    DishTemplate,
    DishTemplateComponent,
    LineComponent,
    ProductionLine,
    ServiceSectionCode,
)
from planning.services import board_queryset, open_service_day


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


@transaction.atomic
def seed_skybar_from_csv(csv_path: Path) -> dict:
    dishes: dict[str, list[dict]] = {}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
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

    stats = {
        "skybar_dishes_upserted": 0,
        "skybar_components": 0,
        "skybar_items_created": 0,
        "skybar_items_linked": 0,
        "csv_dishes": len(dishes),
        "csv_rows": sum(len(v) for v in dishes.values()),
    }

    item_by_name = {i.name: i for i in Item.objects.all()}
    item_by_lname = {n.casefold(): i for n, i in item_by_name.items()}

    def resolve_item(component_name: str) -> Item:
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
        seen: set[str] = set()
        for ci, crow in enumerate(dishes[dish_name]):
            cname = crow["item_name"] or dish_name
            key = cname.casefold()
            if key in seen:
                continue
            seen.add(key)
            item = resolve_item(cname)
            comps.append(
                DishTemplateComponent(
                    template=tmpl,
                    item=item,
                    supplier_item=None,
                    name="",
                    planned_qty=None,
                    unit=item.base_unit or "ea",
                    sort_order=ci * 10,
                    notes=crow.get("notes") or "",
                )
            )
        DishTemplateComponent.objects.bulk_create(comps)
        stats["skybar_components"] += len(comps)
    return stats


def snapshot() -> dict:
    sky = (
        DishTemplate.objects.filter(section="skybar")
        .annotate(nc=Count("components"))
        .order_by("sort_order", "name")
    )
    comps = DishTemplateComponent.objects.filter(template__section="skybar")
    return {
        "skybar_templates": sky.count(),
        "skybar_active": sky.filter(active=True).count(),
        "skybar_check_mode": sky.filter(mode="check").count(),
        "skybar_components": comps.count(),
        "components_with_item": comps.filter(item__isnull=False).count(),
        "components_with_supplier_item": comps.filter(
            supplier_item__isnull=False
        ).count(),
        "items_total": Item.objects.count(),
        "items_category_skybar": Item.objects.filter(category="skybar").count(),
        "per_dish": [
            {"name": t.name, "components": t.nc, "mode": t.mode} for t in sky
        ],
    }


def main() -> int:
    csv_path = ROOT / "sheets" / "skybar-mep-list.csv"
    if not csv_path.is_file():
        print("MISSING CSV", csv_path)
        return 2

    out: dict = {"service_date": "2026-08-11", "csv": str(csv_path)}

    print("=== SEED RUN 1 ===", flush=True)
    out["seed_run_1_stats"] = seed_skybar_from_csv(csv_path)
    snap1 = snapshot()
    out["after_seed_1"] = snap1
    print(json.dumps(out["seed_run_1_stats"], indent=2), flush=True)

    print("=== SEED RUN 2 ===", flush=True)
    out["seed_run_2_stats"] = seed_skybar_from_csv(csv_path)
    snap2 = snapshot()
    out["after_seed_2"] = snap2
    out["idempotent"] = {
        "templates_stable": snap1["skybar_templates"] == snap2["skybar_templates"],
        "components_stable": snap1["skybar_components"] == snap2["skybar_components"],
        "per_dish_stable": snap1["per_dish"] == snap2["per_dish"],
        "no_supplier_on_components": snap2["components_with_supplier_item"] == 0,
        "all_components_linked": snap2["components_with_item"]
        == snap2["skybar_components"],
        "run2_items_created_zero": out["seed_run_2_stats"]["skybar_items_created"]
        == 0,
    }
    print(json.dumps(out["idempotent"], indent=2), flush=True)

    print("=== OPEN BOARD ===", flush=True)
    d = date(2026, 8, 11)
    open_service_day(d, sections=["skybar"], generate_lines=True)
    day, sec = board_queryset(d, "skybar")
    lines = list(sec.lines.all())
    tmpl_lines = [ln for ln in lines if ln.source == ProductionLine.Source.TEMPLATE]
    per_dish_board = []
    for ln in sorted(tmpl_lines, key=lambda x: (x.sort_order, x.name)):
        per_dish_board.append(
            {
                "line_id": ln.id,
                "name": ln.name,
                "mode": ln.mode,
                "source": ln.source,
                "template_id": ln.template_id,
                "component_count": ln.components.count(),
                "actual_qty": ln.actual_qty,
            }
        )
    board = {
        "service_date": str(day.service_date),
        "section": sec.section,
        "day_status": day.status,
        "total_lines": len(lines),
        "template_lines": len(tmpl_lines),
        "manual_lines": sum(
            1 for ln in lines if ln.source == ProductionLine.Source.MANUAL
        ),
        "line_components_total": LineComponent.objects.filter(
            line__service_section=sec
        ).count(),
        "all_template_check": all(ln.mode == "check" for ln in tmpl_lines),
        "all_check_actual_null": all(
            ln.actual_qty is None for ln in tmpl_lines if ln.mode == "check"
        ),
        "per_dish_lines": per_dish_board,
    }
    out["board"] = board
    print(
        "board template_lines",
        board["template_lines"],
        "line_components",
        board["line_components_total"],
        flush=True,
    )

    open_service_day(d, sections=["skybar"], generate_lines=True)
    _, sec2 = board_queryset(d, "skybar")
    lines2 = list(sec2.lines.all())
    out["reopen"] = {
        "total_lines": len(lines2),
        "template_lines": sum(
            1 for ln in lines2 if ln.source == ProductionLine.Source.TEMPLATE
        ),
        "stable_vs_first": len(lines2) == len(lines),
    }

    gate_ok = (
        snap2["skybar_templates"] >= 20
        and snap2["skybar_components"] > 0
        and board["template_lines"] > 0
        and board["template_lines"] == snap2["skybar_active"]
        and out["idempotent"]["templates_stable"]
        and out["idempotent"]["components_stable"]
        and out["idempotent"]["no_supplier_on_components"]
        and out["idempotent"]["run2_items_created_zero"]
        and out["reopen"]["stable_vs_first"]
        and board["all_template_check"]
        and board["all_check_actual_null"]
    )
    out["gate_ok"] = gate_ok

    out_dir = Path.home() / ".hermes/profiles/linux-wiki/kanban-deliverables"
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / "evolving-cook-skybar-templates-evidence.json"
    jpath.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print("WROTE", jpath, flush=True)
    print("GATE", "OK" if gate_ok else "FAIL", flush=True)
    print(json.dumps({"gate_ok": gate_ok, "templates": snap2["skybar_templates"], "components": snap2["skybar_components"], "board_lines": board["template_lines"]}, indent=2))
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
