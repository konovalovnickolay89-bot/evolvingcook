#!/usr/bin/env python3
"""Smoke: create text CatalogIngestUpload, queue extraction, wait for review.

Does not accept proposals. Never prints secrets.
Usage: from repo root with venv:
  .venv/bin/python scripts/ingest_smoke.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from catalog.ingest import queue_ingest_extraction  # noqa: E402
from catalog.models import CatalogIngestProposal, CatalogIngestUpload  # noqa: E402


SAMPLE_TEXT = """Kitchen sheet sample (smoke ingest — leave proposals pending)
Dish: Breakfast
- Eggs free range 30x each — Brakes code 112724 — pack 30 ea — price 8.40
- Milk whole 2L — Booker — pack 2000 ml — price 1.85
- Butter unsalted 250g — BPM 591085 — pack 250 g — price 2.10
"""


def main() -> int:
    before_p = CatalogIngestProposal.objects.count()
    print(f"before_proposals={before_p}")
    up = CatalogIngestUpload.objects.create(
        source_kind=CatalogIngestUpload.SourceKind.TEXT,
        raw_text=SAMPLE_TEXT,
        status=CatalogIngestUpload.Status.PENDING,
    )
    print(f"upload_id={up.id}")
    task_id = queue_ingest_extraction(up.id)
    up.refresh_from_db()
    print(f"queued task_id={task_id} status={up.status}")

    deadline = time.time() + 240
    while time.time() < deadline:
        up.refresh_from_db()
        if up.status in (
            CatalogIngestUpload.Status.REVIEW,
            CatalogIngestUpload.Status.FAILED,
            CatalogIngestUpload.Status.DONE,
        ):
            break
        time.sleep(2)

    after_p = CatalogIngestProposal.objects.count()
    props = list(
        CatalogIngestProposal.objects.filter(upload=up).values(
            "id", "name", "confidence", "base_unit", "supplier_name", "status"
        )
    )
    err = (up.error or "")[:400]
    print(f"final_status={up.status}")
    print(f"model_name={up.model_name!r}")
    print(f"error={err!r}")
    print(f"after_proposals={after_p} delta={after_p - before_p}")
    print(f"proposal_count_for_upload={len(props)}")
    for p in props[:10]:
        print(
            "proposal",
            p["id"],
            p["name"],
            "conf=",
            p["confidence"],
            "unit=",
            p["base_unit"],
            "supplier=",
            p["supplier_name"],
            "status=",
            p["status"],
        )
    ok = up.status == CatalogIngestUpload.Status.REVIEW and len(props) >= 1
    print(f"INGEST_LIVE_OK={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
