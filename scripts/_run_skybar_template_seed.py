#!/usr/bin/env python3
"""One-shot runner: seed skybar dish templates + open/fetch board + idempotency check."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.core.management import call_command
from django.db.models import Count

from catalog.models import Item, SupplierItem
from planning.models import (
    DishTemplate,
    DishTemplateComponent,
    LineComponent,
    ProductionLine,
    ServiceDay,
    ServiceSection,
)
from planning.services import board_queryset, open_service_day


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
        "per_dish": [{"name": t.name, "components": t.nc, "mode": t.mode} for t in sky],
    }


def main() -> int:
    out: dict = {"service_date": "2026-08-11"}
    print("=== SEED RUN 1 ===", flush=True)
    call_command("seed_dish_templates", skybar_only=True)
    snap1 = snapshot()
    out["after_seed_1"] = snap1
    print(json.dumps(snap1, indent=2), flush=True)

    print("=== SEED RUN 2 (idempotency) ===", flush=True)
    call_command("seed_dish_templates", skybar_only=True)
    snap2 = snapshot()
    out["after_seed_2"] = snap2
    out["idempotent"] = {
        "templates_stable": snap1["skybar_templates"] == snap2["skybar_templates"],
        "components_stable": snap1["skybar_components"] == snap2["skybar_components"],
        "per_dish_stable": snap1["per_dish"] == snap2["per_dish"],
        "no_supplier_on_components": snap2["components_with_supplier_item"] == 0,
        "all_components_linked": snap2["components_with_item"]
        == snap2["skybar_components"],
    }
    print(json.dumps(out["idempotent"], indent=2), flush=True)

    print("=== OPEN SKYBAR BOARD 2026-08-11 ===", flush=True)
    d = date(2026, 8, 11)
    # Fresh board day dedicated to this gate (avoid mixing old manual smoke lines)
    open_service_day(d, sections=["skybar"], generate_lines=True)
    day, sec = board_queryset(d, "skybar")
    lines = list(sec.lines.all())
    # Only template-sourced for per-dish report (manual lines would be source=manual)
    tmpl_lines = [ln for ln in lines if ln.source == ProductionLine.Source.TEMPLATE]
    per_dish_board = []
    for ln in sorted(tmpl_lines, key=lambda x: (x.sort_order, x.name)):
        ncomp = ln.components.count()
        per_dish_board.append(
            {
                "line_id": ln.id,
                "name": ln.name,
                "mode": ln.mode,
                "source": ln.source,
                "template_id": ln.template_id,
                "component_count": ncomp,
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
    print(json.dumps(board, indent=2, default=str), flush=True)

    # Second open/generate must not duplicate template lines
    print("=== RE-OPEN GENERATE (no dupe lines) ===", flush=True)
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
    print(json.dumps(out["reopen"], indent=2), flush=True)

    # Gate
    gate_ok = (
        snap2["skybar_templates"] >= 20
        and snap2["skybar_components"] > 0
        and board["template_lines"] > 0
        and board["template_lines"] == snap2["skybar_active"]
        and out["idempotent"]["templates_stable"]
        and out["idempotent"]["components_stable"]
        and out["idempotent"]["no_supplier_on_components"]
        and out["reopen"]["stable_vs_first"]
        and board["all_template_check"]
        and board["all_check_actual_null"]
    )
    out["gate_ok"] = gate_ok
    out_path = Path.home() / ".hermes/profiles/linux-wiki/kanban-deliverables"
    out_path.mkdir(parents=True, exist_ok=True)
    json_path = out_path / "evolving-cook-skybar-templates-evidence.json"
    json_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print("WROTE", json_path, flush=True)
    print("GATE", "OK" if gate_ok else "FAIL", flush=True)
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
