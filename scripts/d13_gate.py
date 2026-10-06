#!/usr/bin/env python3
"""
D13 gate: PO scope + on_order excludes event.

Runs against live DB via Django ORM. Optional HTTP checks if :8000 responds.
Writes evidence JSON next to this script's parent docs/ or /tmp.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from catalog.models import Item, Supplier, SupplierItem  # noqa: E402
from django.conf import settings  # noqa: E402
from purchasing.models import PurchaseOrder, PurchaseOrderLine  # noqa: E402
from purchasing.services import (  # noqa: E402
    OPEN_PO_STATUSES_FOR_ON_ORDER,
    VARIANCE_LABEL,
    on_order_qty,
)

EVIDENCE_PATH = (
    Path.home()
    / ".hermes/profiles/linux-wiki/kanban-deliverables/evolving-cook-django-d13-evidence.json"
)


def http_json(path: str, token: str | None = None) -> tuple[int, dict | list | str]:
    req = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1{path}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def main() -> int:
    evidence: dict = {
        "contract_version_settings": settings.CONTRACT_VERSION,
        "app_version_settings": settings.APP_VERSION,
        "open_statuses": list(OPEN_PO_STATUSES_FOR_ON_ORDER),
        "variance_label": VARIANCE_LABEL,
        "inventory_stub": True,
    }
    assert settings.CONTRACT_VERSION == "0.1.9", settings.CONTRACT_VERSION
    assert VARIANCE_LABEL == "unexplained"

    # Pick any active supplier_item with pack_qty
    si = (
        SupplierItem.objects.filter(active=True)
        .exclude(pack_qty__isnull=True)
        .exclude(pack_qty=0)
        .select_related("item", "supplier")
        .order_by("id")
        .first()
    )
    if si is None:
        # minimal synthetic
        supplier, _ = Supplier.objects.get_or_create(
            name="D13 Gate Supplier",
            defaults={"active": True, "lead_time_days": 1},
        )
        item, _ = Item.objects.get_or_create(
            name="D13 Gate Item",
            defaults={"base_unit": "kg", "active": True},
        )
        si, _ = SupplierItem.objects.get_or_create(
            supplier=supplier,
            item=item,
            defaults={
                "supplier_code": "D13-GATE",
                "pack_description": "1kg",
                "pack_qty": Decimal("1"),
                "price": Decimal("1.00"),
                "active": True,
                "preferred": True,
            },
        )
    item_id = si.item_id
    evidence["item_id"] = item_id
    evidence["supplier_item_id"] = si.pk

    # Close/cleanup prior D13 gate POs (notes marker)
    old = PurchaseOrder.objects.filter(notes__startswith="[d13-gate]")
    old_ids = list(old.values_list("id", flat=True))
    PurchaseOrderLine.objects.filter(purchase_order_id__in=old_ids).delete()
    old.delete()

    today = date.today()
    repl_qty = Decimal("10")
    event_qty = Decimal("99")

    po_repl = PurchaseOrder.objects.create(
        supplier_id=si.supplier_id,
        order_date=today,
        status=PurchaseOrder.Status.SENT,
        scope=PurchaseOrder.Scope.REPLENISHMENT,
        notes="[d13-gate] replenishment open",
    )
    PurchaseOrderLine.objects.create(
        purchase_order=po_repl,
        supplier_item=si,
        packs=Decimal("10"),
        qty_base=repl_qty,
        proposed_packs=Decimal("10"),
    )

    po_event = PurchaseOrder.objects.create(
        supplier_id=si.supplier_id,
        order_date=today,
        status=PurchaseOrder.Status.SENT,
        scope=PurchaseOrder.Scope.EVENT,
        notes="[d13-gate] event open",
    )
    PurchaseOrderLine.objects.create(
        purchase_order=po_event,
        supplier_item=si,
        packs=Decimal("99"),
        qty_base=event_qty,
        proposed_packs=Decimal("99"),
    )

    oo = on_order_qty(item_id)
    evidence["on_order"] = str(oo)
    evidence["repl_qty"] = str(repl_qty)
    evidence["event_qty"] = str(event_qty)
    evidence["po_repl_id"] = po_repl.pk
    evidence["po_event_id"] = po_event.pk
    evidence["po_repl_scope"] = po_repl.scope
    evidence["po_event_scope"] = po_event.scope

    assert oo == repl_qty, f"expected on_order={repl_qty}, got {oo}"
    assert oo != repl_qty + event_qty

    # Existing rows defaulted to replenishment
    scopes = list(
        PurchaseOrder.objects.exclude(notes__startswith="[d13-gate]")
        .values_list("scope", flat=True)
        .distinct()
    )
    evidence["preexisting_scopes_sample"] = scopes
    # All non-null scopes should be valid choices
    bad = PurchaseOrder.objects.exclude(
        scope__in=[
            PurchaseOrder.Scope.REPLENISHMENT,
            PurchaseOrder.Scope.EVENT,
        ]
    ).count()
    evidence["invalid_scope_count"] = bad
    assert bad == 0

    # Defaults on new proposal-style create
    assert (
        PurchaseOrder._meta.get_field("scope").default
        == PurchaseOrder.Scope.REPLENISHMENT
        or PurchaseOrder._meta.get_field("scope").default
        == PurchaseOrder.Scope.REPLENISHMENT.value
    )

    # OpenAPI
    openapi = json.loads((ROOT / "docs" / "openapi.json").read_text())
    evidence["openapi_version"] = openapi.get("info", {}).get("version")
    po_schema = openapi.get("components", {}).get("schemas", {}).get("PurchaseOrderOut", {})
    evidence["openapi_has_scope"] = "scope" in po_schema.get("properties", {})
    assert evidence["openapi_has_scope"]
    assert evidence["openapi_version"] == "0.1.9"

    # HTTP version
    code, ver = http_json("/version")
    evidence["http_version"] = {"http": code, "body": ver}
    if code == 200 and isinstance(ver, dict):
        evidence["http_contract_ok"] = ver.get("contract_version") == "0.1.9"
    else:
        evidence["http_contract_ok"] = False
        evidence["http_note"] = "unit may need restart to pick up .env 0.1.9"
    assert evidence["http_contract_ok"], evidence["http_version"]

    # HTTP PO GET includes scope (Bearer via issue_token)
    from api.auth import issue_token
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(is_active=True).order_by("id").first()
    assert user is not None, "need active user for Bearer"
    token = issue_token(user)
    code_r, po_r = http_json(f"/purchasing/orders/{po_repl.pk}", token=token)
    code_e, po_e = http_json(f"/purchasing/orders/{po_event.pk}", token=token)
    evidence["http_po_repl"] = {"http": code_r, "scope": po_r.get("scope") if isinstance(po_r, dict) else po_r}
    evidence["http_po_event"] = {"http": code_e, "scope": po_e.get("scope") if isinstance(po_e, dict) else po_e}
    assert code_r == 200 and isinstance(po_r, dict) and po_r.get("scope") == "replenishment"
    assert code_e == 200 and isinstance(po_e, dict) and po_e.get("scope") == "event"

    # Cleanup gate POs so they do not poison future proposals
    PurchaseOrderLine.objects.filter(
        purchase_order_id__in=[po_repl.pk, po_event.pk]
    ).delete()
    PurchaseOrder.objects.filter(pk__in=[po_repl.pk, po_event.pk]).delete()
    evidence["cleaned_up"] = True
    evidence["ok"] = True

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    print(json.dumps(evidence, indent=2, default=str))
    print("GATE_OK", EVIDENCE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
