#!/usr/bin/env python3
"""Phase 2 walk + ordering gate against local 127.0.0.1:8000.

Seeds minimal operational fixtures for evidence only:
  - default_area + pack_qty + par on a few real catalogue items
  - does NOT invent StorageArea.walk_order values
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction

from api.auth import issue_token
from catalog.models import Item, ParLevel, StorageArea, Supplier, SupplierItem
from purchasing.models import PurchaseOrder

BASE = "http://127.0.0.1:8000/api/v1"
HOST = "api.apidiscoverysolution.uk"


def req(method: str, path: str, token: str | None = None, body: dict | None = None):
    data = None
    headers = {"Host": HOST, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return e.code, payload, raw


def seed_viability_fixtures() -> dict:
    """
    Minimal data so order proposal can ceil packs.
    Does not set StorageArea.walk_order (unknown — leave null).
    """
    areas = list(StorageArea.objects.filter(active=True).order_by("name")[:2])
    if len(areas) < 2:
        raise SystemExit("need >=2 storage areas")
    a1, a2 = areas[0], areas[1]

    # Prefer items that already have supplier links
    sis = list(
        SupplierItem.objects.filter(active=True)
        .select_related("item", "supplier")
        .order_by("id")[:3]
    )
    if len(sis) < 2:
        raise SystemExit("need >=2 supplier items")

    # Item A: two areas with par (sum shortfalls test)
    item_a = sis[0].item
    item_b = sis[1].item
    si_a = sis[0]
    si_b = sis[1]

    with transaction.atomic():
        item_a.default_area = a1
        item_a.save(update_fields=["default_area"])
        item_b.default_area = a2
        item_b.save(update_fields=["default_area"])

        # pack sizes in base units
        si_a.pack_qty = Decimal("10")
        si_a.preferred = True
        si_a.save(update_fields=["pack_qty", "preferred"])
        si_b.pack_qty = Decimal("5")
        si_b.preferred = True
        si_b.save(update_fields=["pack_qty", "preferred"])

        # supplier order days Mon-Fri for deliver_on
        sup = si_a.supplier
        if not sup.order_days:
            sup.order_days = [0, 1, 2, 3, 4]
            sup.lead_time_days = 1
            sup.save(update_fields=["order_days", "lead_time_days"])
        sup_b = si_b.supplier
        if not sup_b.order_days:
            sup_b.order_days = [0, 1, 2, 3, 4]
            sup_b.lead_time_days = 1
            sup_b.save(update_fields=["order_days", "lead_time_days"])

        # Pars: item_a in two areas so shortfalls sum before pack ceil
        ParLevel.objects.update_or_create(
            item=item_a,
            area=a1,
            weekday=None,
            defaults={"qty": Decimal("100")},
        )
        ParLevel.objects.update_or_create(
            item=item_a,
            area=a2,
            weekday=None,
            defaults={"qty": Decimal("50")},
        )
        # Second line for item_a in a2: ensure walk can hold multi-area via generation
        # Generation uses default_area OR par presence — full walk will get a1 for default
        # and we also add explicit second walk line via batch create path.
        ParLevel.objects.update_or_create(
            item=item_b,
            area=a2,
            weekday=None,
            defaults={"qty": Decimal("40")},
        )

        # Close any open POs so on_order does not poison shortfall math across gate runs
        PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.DRAFT,
                PurchaseOrder.Status.SENT,
                PurchaseOrder.Status.CONFIRMED,
            ]
        ).update(status=PurchaseOrder.Status.CLOSED)

    return {
        "area1": {"id": a1.pk, "name": a1.name},
        "area2": {"id": a2.pk, "name": a2.name},
        "item_a": {"id": item_a.pk, "name": item_a.name, "si": si_a.pk, "pack": "10"},
        "item_b": {"id": item_b.pk, "name": item_b.name, "si": si_b.pk, "pack": "5"},
        "note": "walk_order left null on all areas (not invented)",
    }


def main() -> int:
    evidence: dict = {"fixtures": seed_viability_fixtures()}
    fx = evidence["fixtures"]
    user = get_user_model().objects.get(email="mykola@apidiscoverysolution.uk")
    token = issue_token(user)

    code, ver, raw = req("GET", "/version")
    evidence["version"] = {"http": code, "body": ver}
    print("1 version", code, ver)
    assert code == 200, ver
    assert ver.get("contract_version") == "0.1.9", ver

    # Start full walk (all areas)
    code, walk, raw = req("POST", "/walks/start", token, {"kind": "order", "notes": "phase2 gate"})
    evidence["start_walk"] = {
        "http": code,
        "id": walk.get("id"),
        "line_count": walk.get("line_count"),
        "status": walk.get("status"),
    }
    print("2 start_walk", code, evidence["start_walk"])
    assert code == 200, walk
    walk_id = walk["id"]
    lines = walk.get("lines") or []
    assert walk["line_count"] >= 1, walk

    # Find lines for fixture items; ensure multi-area for item_a
    item_a_id = fx["item_a"]["id"]
    item_b_id = fx["item_b"]["id"]
    a1_id = fx["area1"]["id"]
    a2_id = fx["area2"]["id"]

    def find_line(item_id, area_id=None):
        for ln in lines:
            if ln["item_id"] == item_id and (area_id is None or ln.get("area_id") == area_id):
                return ln
        return None

    # Batch: count item_a@a1=20, skip item_b null, and add item_a@a2=10 if missing
    batch = [
        {
            "item_id": item_a_id,
            "area_id": a1_id,
            "counted_qty": 20,
            "counted_unit": "ea",
        },
        {
            "item_id": item_b_id,
            "area_id": a2_id,
            "counted_qty": None,
            "skipped": True,
        },
        {
            "item_id": item_a_id,
            "area_id": a2_id,
            "counted_qty": 10,
            "counted_unit": "ea",
        },
    ]
    code, walk2, raw = req(
        "POST", f"/walks/{walk_id}/lines/batch", token, {"lines": batch}
    )
    evidence["batch1"] = {
        "http": code,
        "line_count": walk2.get("line_count"),
        "counted_count": walk2.get("counted_count"),
        "skipped_count": walk2.get("skipped_count"),
        "sample": [
            {
                "item_id": ln["item_id"],
                "area_id": ln.get("area_id"),
                "counted_qty": ln.get("counted_qty"),
                "skipped": ln.get("skipped"),
                "qty_base": ln.get("qty_base"),
            }
            for ln in (walk2.get("lines") or [])
            if ln["item_id"] in {item_a_id, item_b_id}
        ],
    }
    print("3 batch1", code, json.dumps(evidence["batch1"], indent=2)[:800])
    assert code == 200, walk2

    # Idempotent resubmit — same payload, no duplicate lines
    line_count_before = walk2["line_count"]
    code, walk3, raw = req(
        "POST", f"/walks/{walk_id}/lines/batch", token, {"lines": batch}
    )
    evidence["batch_idempotent"] = {
        "http": code,
        "line_count_before": line_count_before,
        "line_count_after": walk3.get("line_count"),
        "duplicate": walk3.get("line_count") != line_count_before,
    }
    print("4 idempotent", code, evidence["batch_idempotent"])
    assert code == 200, walk3
    assert walk3["line_count"] == line_count_before

    # Decimal JSON numbers check on real body (any counted_qty number)
    import re

    has_num = bool(re.search(r'"counted_qty":\s*\d', raw)) or bool(
        re.search(r'"qty_base":\s*\d', raw)
    )
    has_str = bool(re.search(r'"counted_qty":\s*"\d', raw)) or bool(
        re.search(r'"qty_base":\s*"\d', raw)
    )
    evidence["decimal_json_numbers"] = {
        "raw_snippet_has_quoted_decimal": has_str,
        "raw_has_number_qty": has_num,
    }
    print("5 decimal_numbers", evidence["decimal_json_numbers"])
    assert evidence["decimal_json_numbers"]["raw_has_number_qty"]
    assert not evidence["decimal_json_numbers"]["raw_snippet_has_quoted_decimal"]

    # Submit + lock
    code, wsub, _ = req("POST", f"/walks/{walk_id}/submit", token, {})
    evidence["submit"] = {"http": code, "status": wsub.get("status")}
    print("6 submit", code, evidence["submit"])
    assert code == 200 and wsub.get("status") == "submitted"

    code, wlock, _ = req("POST", f"/walks/{walk_id}/lock", token, {})
    evidence["lock"] = {"http": code, "status": wlock.get("status")}
    print("7 lock", code, evidence["lock"])
    assert code == 200 and wlock.get("status") == "locked"

    # Order proposal
    # item_a: par 100+50=150, counted 20+10=30, on_order 0 → shortfall 120 → ceil(120/10)=12 packs
    code, prop, raw_prop = req("POST", f"/walks/{walk_id}/order-proposal", token, {})
    evidence["order_proposal"] = {
        "http": code,
        "po_ids": prop.get("purchase_order_ids"),
        "pos": prop.get("purchase_orders"),
    }
    print("8 order_proposal", code, json.dumps(evidence["order_proposal"], indent=2)[:1200])
    assert code == 200, prop
    assert prop.get("purchase_order_ids"), "expected at least one PO"
    po0 = prop["purchase_orders"][0]
    assert po0["status"] == "draft"
    assert po0["lines"], "expected PO lines"
    line0 = next(
        (ln for ln in po0["lines"] if ln["item_id"] == item_a_id),
        po0["lines"][0],
    )
    evidence["shortfall_sum_check"] = {
        "item_id": line0["item_id"],
        "par": line0.get("par"),
        "counted": line0.get("counted"),
        "on_order": line0.get("on_order"),
        "shortfall": line0.get("shortfall"),
        "proposed_packs": line0.get("proposed_packs"),
        "expected_shortfall_item_a": 120,
        "expected_packs_item_a": 12,
        "decimal_fields_are_json_numbers": all(
            isinstance(line0.get(k), (int, float))
            for k in ("par", "counted", "on_order", "shortfall", "proposed_packs", "pack_qty")
            if line0.get(k) is not None
        ),
    }
    if line0["item_id"] == item_a_id:
        assert float(line0["shortfall"]) == 120.0, line0
        assert float(line0["proposed_packs"]) == 12.0, line0
    assert evidence["shortfall_sum_check"]["decimal_fields_are_json_numbers"], line0
    print("9 shortfall_sum", evidence["shortfall_sum_check"])
    # also assert raw body has unquoted numbers for shortfall
    assert '"shortfall": 120' in raw_prop or '"shortfall":120' in raw_prop, raw_prop[:500]

    po_id = po0["id"]
    code, sent, _ = req("POST", f"/purchasing/orders/{po_id}/send", token, {})
    evidence["po_send"] = {"http": code, "status": sent.get("status"), "sent_at": sent.get("sent_at")}
    print("10 po_send", code, evidence["po_send"])
    assert code == 200 and sent.get("status") == "sent"

    # Delivery receipt
    dlines = [
        {
            "supplier_item_id": ln["supplier_item_id"],
            "packs_expected": ln["packs"],
            "packs_received": ln["packs"],
            "note": "ok",
        }
        for ln in sent["lines"]
    ]
    # Force one short note path on last line if multiple
    if dlines:
        dlines[-1]["note"] = "short"
        dlines[-1]["packs_received"] = max(0, float(dlines[-1]["packs_expected"] or 0) - 1)

    code, delivery, _ = req(
        "POST",
        f"/purchasing/orders/{po_id}/deliveries",
        token,
        {"complete": True, "lines": dlines, "notes": "phase2 gate receipt"},
    )
    evidence["delivery"] = {
        "http": code,
        "id": delivery.get("id"),
        "status": delivery.get("status"),
        "line_count": delivery.get("line_count"),
        "notes_sample": [ln.get("note") for ln in (delivery.get("lines") or [])],
    }
    print("11 delivery", code, evidence["delivery"])
    assert code == 200, delivery

    # 401 contract smoke — bad token
    code401, body401, _ = req(
        "POST",
        f"/walks/{walk_id}/lines/batch",
        "not-a-valid-token",
        {"lines": [{"item_id": item_a_id, "counted_qty": 1}]},
    )
    evidence["batch_401"] = {"http": code401, "body": body401}
    print("12 batch_401", code401, body401)
    assert code401 == 401

    out = ROOT / "docs" / "phase2-gate-evidence.json"
    out.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print("wrote", out)
    print("PHASE2_GATE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print("PHASE2_GATE_FAIL", e, file=sys.stderr)
        raise
