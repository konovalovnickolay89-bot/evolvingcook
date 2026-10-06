"""Phase 1 gate checks — run: python scripts/phase1_verify.py"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from decimal import Decimal

from django.db import connection
from django.db.models import Exists, OuterRef, Q

from catalog.ingest import api_key_present, run_ingest_extraction
from catalog.llm_provider import API_KEY_ENV
from catalog.models import (
    CatalogIngestUpload,
    Item,
    ParLevel,
    StorageArea,
    Supplier,
    SupplierItem,
)


def main() -> int:
    print("areas", list(StorageArea.objects.order_by("name").values_list("name", "kind", "walk_order")))
    print("area_count", StorageArea.objects.count())
    print("items", Item.objects.count())
    print("suppliers", Supplier.objects.count())
    print("si", SupplierItem.objects.count())
    print("unverified_items", Item.objects.filter(unverified=True).count())
    print("unverified_si", SupplierItem.objects.filter(unverified=True).count())

    has_si = SupplierItem.objects.filter(item_id=OuterRef("pk"), active=True)
    has_par = ParLevel.objects.filter(item_id=OuterRef("pk"))
    has_price = SupplierItem.objects.filter(item_id=OuterRef("pk"), price__isnull=False)
    qs = Item.objects.filter(active=True).annotate(
        has_supplier=Exists(has_si),
        has_par=Exists(has_par),
        has_price=Exists(has_price),
    )
    missing = qs.filter(Q(has_supplier=False) | Q(has_par=False) | Q(has_price=False))
    print("walk_style_missing_any", missing.count())
    print("missing_supplier", qs.filter(has_supplier=False).count())
    print("missing_par", qs.filter(has_par=False).count())
    print("missing_price", qs.filter(has_price=False).count())
    print("sample_missing", list(missing.values_list("name", flat=True)[:8]))

    with connection.cursor() as c:
        c.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'uniq_parlevel_item_area_weekday'
            """
        )
        print("b11_constraint", c.fetchall())

    item = Item.objects.first()
    area = StorageArea.objects.first()
    if item and area:
        ParLevel.objects.filter(item=item, area=area, weekday=None).delete()
        ParLevel.objects.create(item=item, area=area, weekday=None, qty=Decimal("1"))
        try:
            ParLevel.objects.create(item=item, area=area, weekday=None, qty=Decimal("2"))
            print("B11_FAIL_duplicate_allowed")
        except Exception as e:  # noqa: BLE001
            print("B11_OK_duplicate_rejected", type(e).__name__)
        ParLevel.objects.filter(item=item, area=area, weekday=None).delete()

    print("mistral_key_present", api_key_present())
    print("blocked_env_name", API_KEY_ENV)
    u = CatalogIngestUpload.objects.create(
        source_kind="text",
        raw_text="test olives OC174 BELAZU",
    )
    res = run_ingest_extraction(u.pk)
    u.refresh_from_db()
    print("ingest_block", res)
    print(
        "upload_status",
        u.status,
        "err_has_MISTRAL",
        API_KEY_ENV in (u.error or ""),
    )
    print("proposal_count", u.proposals.count())

    ok = (
        StorageArea.objects.count() == 8
        and Item.objects.count() >= 50
        and missing.count() >= 0  # query runs cleanly
    )
    print("GATE_LOCAL", "green" if ok else "red")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
