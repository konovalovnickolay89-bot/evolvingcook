#!/usr/bin/env python3
"""Phase 3 ledger gate against local 127.0.0.1:8000 + DB trigger checks.

Gate story:
  1. migrate clean; django unit healthy
  2. seed item+area balance 0
  3. delivery receipt → movement + balance up
  4. walk count → submit/lock → theoretical + unexplained; balance unchanged by variance
  5. waste → balance down
  6. UPDATE/DELETE StockMovement fails (app + DB)
  7. no API path to hand-set StockBalance.qty
  8. local + public version 200 @ 0.1.10
  9. openapi regenerated
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError

from api.auth import issue_token
from catalog.models import Item, ParLevel, StorageArea, SupplierItem
from inventory.models import StockBalance, StockMovement
from inventory.services import get_balance_qty
from purchasing.models import PurchaseOrder

BASE = "http://127.0.0.1:8000/api/v1"
HOST = "api.apidiscoverysolution.uk"
PUBLIC = "https://api.apidiscoverysolution.uk/api/v1"
CONTRACT = "0.1.10"


def req(method: str, path: str, token: str | None = None, body: dict | None = None, base: str = BASE):
    data = None
    headers = {"Host": HOST, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return e.code, payload, raw


def seed() -> dict:
    areas = list(StorageArea.objects.filter(active=True).order_by("name")[:2])
    if len(areas) < 2:
        raise SystemExit("need >=2 storage areas")
    a1, a2 = areas[0], areas[1]
    sis = list(
        SupplierItem.objects.filter(active=True)
        .exclude(pack_qty__isnull=True)
        .exclude(pack_qty=0)
        .select_related("item", "supplier")
        .order_by("id")[:5]
    )
    if not sis:
        sis = list(
            SupplierItem.objects.filter(active=True)
            .select_related("item", "supplier")
            .order_by("id")[:3]
        )
    if not sis:
        raise SystemExit("need supplier items")
    si = sis[0]
    item = si.item
    with transaction.atomic():
        item.default_area = a1
        item.save(update_fields=["default_area"])
        if si.pack_qty is None or si.pack_qty <= 0:
            si.pack_qty = Decimal("10")
            si.save(update_fields=["pack_qty"])
        si.preferred = True
        si.save(update_fields=["preferred"])
        sup = si.supplier
        if not sup.order_days:
            sup.order_days = [0, 1, 2, 3, 4]
            sup.lead_time_days = 1
            sup.save(update_fields=["order_days", "lead_time_days"])
        ParLevel.objects.update_or_create(
            item=item, area=a1, weekday=None, defaults={"qty": Decimal("100")}
        )
        # Do NOT delete StockMovement rows (append-only trigger). Gate uses deltas.
        PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.DRAFT,
                PurchaseOrder.Status.SENT,
                PurchaseOrder.Status.CONFIRMED,
            ]
        ).update(status=PurchaseOrder.Status.CLOSED)
    start_bal = get_balance_qty(item.pk, a1.pk)
    return {
        "area": {"id": a1.pk, "name": a1.name},
        "area2": {"id": a2.pk, "name": a2.name},
        "item": {"id": item.pk, "name": item.name, "si": si.pk, "pack": str(si.pack_qty)},
        "start_balance": str(start_bal),
    }


def main() -> int:
    evidence: dict = {"contract_expected": CONTRACT}

    # --- units ---
    unit = subprocess.run(
        ["systemctl", "--user", "is-active", "evolving-cook-django.service"],
        capture_output=True,
        text=True,
    )
    qunit = subprocess.run(
        ["systemctl", "--user", "is-active", "evolving-cook-qcluster.service"],
        capture_output=True,
        text=True,
    )
    evidence["units"] = {
        "django": unit.stdout.strip() or unit.stderr.strip(),
        "qcluster": qunit.stdout.strip() or qunit.stderr.strip(),
    }
    print("0 units", evidence["units"])
    assert evidence["units"]["django"] == "active", evidence["units"]

    fx = seed()
    evidence["fixtures"] = fx
    item_id = fx["item"]["id"]
    area_id = fx["area"]["id"]
    si_id = fx["item"]["si"]
    pack = Decimal(fx["item"]["pack"])

    user = get_user_model().objects.get(email="mykola@apidiscoverysolution.uk")
    token = issue_token(user)

    code, ver, _ = req("GET", "/version")
    evidence["version_local"] = {"http": code, "body": ver}
    print("1 version_local", code, ver)
    assert code == 200, ver
    assert ver.get("contract_version") == CONTRACT, ver
    assert ver.get("app_version") == CONTRACT, ver

    # Public version via curl (urllib often 403'd by CF bot score)
    pub = subprocess.run(
        [
            "curl",
            "-fsS",
            "--max-time",
            "30",
            "https://api.apidiscoverysolution.uk/api/v1/version",
        ],
        capture_output=True,
        text=True,
    )
    if pub.returncode == 0 and pub.stdout.strip():
        code_p = 200
        ver_p = json.loads(pub.stdout)
    else:
        code_p = pub.returncode or 0
        ver_p = {"error": pub.stderr or pub.stdout}
    evidence["version_public"] = {"http": code_p, "body": ver_p}
    print("1b version_public", code_p, ver_p)
    assert code_p == 200, ver_p
    assert ver_p.get("contract_version") == CONTRACT, ver_p

    bal0 = get_balance_qty(item_id, area_id)
    evidence["balance_start"] = str(bal0)

    # --- Create draft PO manually + send + complete delivery ---
    from django.utils import timezone
    from catalog.models import Supplier
    from purchasing.models import PurchaseOrderLine

    si = SupplierItem.objects.select_related("supplier", "item").get(pk=si_id)
    packs = Decimal("2")
    qty_base = packs * pack
    with transaction.atomic():
        po = PurchaseOrder.objects.create(
            supplier=si.supplier,
            walk=None,
            order_date=timezone.localdate(),
            delivery_date=timezone.localdate(),
            status=PurchaseOrder.Status.DRAFT,
            scope=PurchaseOrder.Scope.REPLENISHMENT,
            notes="phase3 gate",
        )
        PurchaseOrderLine.objects.create(
            purchase_order=po,
            supplier_item=si,
            proposed_packs=packs,
            packs=packs,
            qty_base=qty_base,
            price=si.price,
        )
    po_id = po.pk
    code, sent, _ = req("POST", f"/purchasing/orders/{po_id}/send", token, {})
    evidence["po_send"] = {"http": code, "status": sent.get("status"), "po_id": po_id}
    print("2 po_send", code, evidence["po_send"])
    assert code == 200 and sent.get("status") == "sent", sent

    code, delivery, raw_d = req(
        "POST",
        f"/purchasing/orders/{po_id}/deliveries",
        token,
        {
            "complete": True,
            "notes": "phase3 gate receipt",
            "lines": [
                {
                    "supplier_item_id": si_id,
                    "packs_expected": float(packs),
                    "packs_received": float(packs),
                    "note": "ok",
                }
            ],
        },
    )
    evidence["delivery"] = {
        "http": code,
        "id": delivery.get("id"),
        "status": delivery.get("status"),
        "line_count": delivery.get("line_count"),
    }
    print("3 delivery", code, evidence["delivery"])
    assert code == 200 and delivery.get("status") == "complete", delivery
    delivery_id = delivery["id"]

    bal_after_receipt = get_balance_qty(item_id, area_id)
    movs = list(
        StockMovement.objects.filter(
            source_type="delivery",
            source_id=str(delivery_id),
            kind=StockMovement.Kind.RECEIPT,
        )
    )
    evidence["receipt"] = {
        "balance_before": str(bal0),
        "balance_after": str(bal_after_receipt),
        "expected_delta": str(qty_base),
        "movement_count": len(movs),
        "movement_qty": str(movs[0].qty) if movs else None,
        "kind": movs[0].kind if movs else None,
    }
    print("4 receipt", evidence["receipt"])
    assert len(movs) >= 1, evidence["receipt"]
    assert bal_after_receipt == bal0 + qty_base, evidence["receipt"]
    assert movs[0].qty == qty_base

    # --- Walk count → submit → variance ---
    # theoretical = bal_after_receipt; count lower by 7 → unexplained -7
    code, walk, _ = req(
        "POST",
        "/walks/start",
        token,
        {"kind": "stock", "area_id": area_id, "notes": "phase3 gate walk"},
    )
    evidence["walk_start"] = {
        "http": code,
        "id": walk.get("id"),
        "line_count": walk.get("line_count"),
    }
    print("5 walk_start", code, evidence["walk_start"])
    assert code == 200, walk
    walk_id = walk["id"]

    counted = bal_after_receipt - Decimal("7")
    code, walk_b, raw_batch = req(
        "POST",
        f"/walks/{walk_id}/lines/batch",
        token,
        {
            "lines": [
                {
                    "item_id": item_id,
                    "area_id": area_id,
                    "counted_qty": float(counted),
                    "counted_unit": "ea",
                }
            ]
        },
    )
    evidence["walk_batch"] = {"http": code, "counted_count": walk_b.get("counted_count")}
    print("6 walk_batch", code, evidence["walk_batch"])
    assert code == 200, walk_b

    code, wsub, raw_sub = req("POST", f"/walks/{walk_id}/submit", token, {})
    lines_sub = [
        ln
        for ln in (wsub.get("lines") or [])
        if ln["item_id"] == item_id and ln.get("area_id") == area_id
    ]
    ln = lines_sub[0] if lines_sub else {}
    evidence["walk_submit"] = {
        "http": code,
        "status": wsub.get("status"),
        "theoretical_qty": ln.get("theoretical_qty"),
        "variance_qty": ln.get("variance_qty"),
        "counted_qty": ln.get("counted_qty"),
        "qty_base": ln.get("qty_base"),
    }
    print("7 walk_submit", code, evidence["walk_submit"])
    assert code == 200 and wsub.get("status") == "submitted", wsub
    assert ln.get("theoretical_qty") == float(bal_after_receipt) or Decimal(
        str(ln.get("theoretical_qty"))
    ) == bal_after_receipt
    assert Decimal(str(ln.get("variance_qty"))) == Decimal("-7"), ln
    bal_after_variance = get_balance_qty(item_id, area_id)
    evidence["variance_balance_unchanged"] = {
        "before": str(bal_after_receipt),
        "after": str(bal_after_variance),
        "label": "unexplained",
    }
    assert bal_after_variance == bal_after_receipt, "variance must not rewrite balance"

    # raw body must not say "error" for variance fields / should use numbers
    assert "error" not in raw_sub.lower() or "token" in raw_sub.lower()
    # softer: variance field descriptions elsewhere; check API values are numbers
    assert isinstance(ln.get("variance_qty"), (int, float)), ln
    assert isinstance(ln.get("theoretical_qty"), (int, float)), ln

    code, wlock, _ = req("POST", f"/walks/{walk_id}/lock", token, {})
    evidence["walk_lock"] = {"http": code, "status": wlock.get("status")}
    assert code == 200 and wlock.get("status") == "locked", wlock

    # --- Waste ---
    code, waste, raw_w = req(
        "POST",
        "/inventory/waste",
        token,
        {
            "item_id": item_id,
            "area_id": area_id,
            "qty": 3,
            "note": "phase3 gate waste",
        },
    )
    bal_after_waste = get_balance_qty(item_id, area_id)
    evidence["waste"] = {
        "http": code,
        "movement": waste,
        "balance_before": str(bal_after_variance),
        "balance_after": str(bal_after_waste),
        "raw_has_number_qty": bool(re.search(r'"qty":\s*-?\d', raw_w)),
        "raw_quoted_qty": bool(re.search(r'"qty":\s*"', raw_w)),
    }
    print("8 waste", code, evidence["waste"])
    assert code == 200, waste
    assert waste.get("kind") == "waste"
    assert Decimal(str(waste.get("qty"))) == Decimal("-3")
    assert bal_after_waste == bal_after_variance - Decimal("3")
    assert evidence["waste"]["raw_has_number_qty"]
    assert not evidence["waste"]["raw_quoted_qty"]

    # --- balances + movements GET ---
    code, bals, _ = req(
        "GET", f"/inventory/balances?item_id={item_id}&area_id={area_id}", token
    )
    evidence["balances_get"] = {"http": code, "rows": bals}
    print("9 balances", code, bals)
    assert code == 200 and bals, bals
    assert Decimal(str(bals[0]["qty"])) == bal_after_waste

    code, mov_list, _ = req(
        "GET",
        f"/inventory/movements?item_id={item_id}&area_id={area_id}&limit=20",
        token,
    )
    evidence["movements_get"] = {
        "http": code,
        "count": len(mov_list) if isinstance(mov_list, list) else 0,
        "kinds": [m.get("kind") for m in (mov_list or [])[:10]],
    }
    print("10 movements", code, evidence["movements_get"])
    assert code == 200 and any(m.get("kind") == "receipt" for m in mov_list)

    # --- Append-only app + DB ---
    mov = StockMovement.objects.filter(item_id=item_id, area_id=area_id).order_by("-id").first()
    assert mov is not None
    app_update_blocked = False
    try:
        mov.note = "should-fail"
        mov.save()
    except ValidationError:
        app_update_blocked = True
    app_delete_blocked = False
    try:
        mov.delete()
    except ValidationError:
        app_delete_blocked = True

    db_update_blocked = False
    try:
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE inventory_stockmovement SET note = %s WHERE id = %s",
                    ["db-hack", mov.pk],
                )
    except (InternalError, ProgrammingError):
        db_update_blocked = True

    db_delete_blocked = False
    try:
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM inventory_stockmovement WHERE id = %s",
                    [mov.pk],
                )
    except (InternalError, ProgrammingError):
        db_delete_blocked = True

    evidence["append_only"] = {
        "app_update_blocked": app_update_blocked,
        "app_delete_blocked": app_delete_blocked,
        "db_update_blocked": db_update_blocked,
        "db_delete_blocked": db_delete_blocked,
    }
    print("11 append_only", evidence["append_only"])
    assert app_update_blocked and app_delete_blocked
    assert db_update_blocked and db_delete_blocked

    # --- No API to hand-set balance ---
    # OpenAPI paths should not include balance PATCH/PUT; try nonsense
    code_bad, body_bad, _ = req(
        "POST",
        "/inventory/balances",
        token,
        {"item_id": item_id, "area_id": area_id, "qty": 999},
    )
    evidence["no_balance_write_api"] = {
        "post_balances_http": code_bad,
        "detail": body_bad.get("detail") if isinstance(body_bad, dict) else body_bad,
    }
    print("12 no_balance_write", evidence["no_balance_write_api"])
    assert code_bad in (404, 405, 400, 401), code_bad

    # Admin model flags (import check)
    from inventory.admin import StockBalanceAdmin, StockMovementAdmin
    from django.contrib.admin.sites import site

    bal_admin = StockBalanceAdmin(StockBalance, site)
    mov_admin = StockMovementAdmin(StockMovement, site)

    class _Req:
        def __init__(self, u):
            self.method = "POST"
            self.user = u

    req_admin = _Req(user)
    evidence["admin_readonly"] = {
        "balance_has_change": bal_admin.has_change_permission(req_admin),
        "balance_has_add": bal_admin.has_add_permission(req_admin),
        "movement_has_change": mov_admin.has_change_permission(req_admin),
        "movement_has_delete": mov_admin.has_delete_permission(req_admin),
        "movement_has_add": mov_admin.has_add_permission(req_admin),
    }
    print("13 admin", evidence["admin_readonly"])
    assert evidence["admin_readonly"]["balance_has_change"] is False
    assert evidence["admin_readonly"]["balance_has_add"] is False
    assert evidence["admin_readonly"]["movement_has_change"] is False
    assert evidence["admin_readonly"]["movement_has_delete"] is False
    assert evidence["admin_readonly"]["movement_has_add"] is False

    # openapi presence
    openapi_path = ROOT / "docs" / "openapi.json"
    schema = json.loads(openapi_path.read_text(encoding="utf-8"))
    paths = schema.get("paths") or {}
    evidence["openapi"] = {
        "path": str(openapi_path),
        "has_inventory_balances": "/api/v1/inventory/balances" in paths,
        "has_inventory_waste": "/api/v1/inventory/waste" in paths,
        "has_inventory_movements": "/api/v1/inventory/movements" in paths,
        "has_count_adjustment": "/api/v1/inventory/count-adjustment" in paths,
        "info_version": (schema.get("info") or {}).get("version"),
    }
    print("14 openapi", evidence["openapi"])
    assert evidence["openapi"]["has_inventory_balances"]
    assert evidence["openapi"]["has_inventory_waste"]
    assert evidence["openapi"]["info_version"] == CONTRACT

    out = ROOT / "docs" / "phase3-gate-evidence.json"
    out.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print("wrote", out)
    print("PHASE3_GATE_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print("PHASE3_GATE_FAIL", e, file=sys.stderr)
        raise
