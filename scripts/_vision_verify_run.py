#!/usr/bin/env python3
"""One-shot vision ingest verification helper (kanban t_0d8c113b). Not for prod."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
django.setup()

from django.core.files import File  # noqa: E402
from catalog.ingest import queue_ingest_extraction  # noqa: E402
from catalog.models import CatalogIngestUpload  # noqa: E402

SRC = Path(
    "/home/discovery-system/.hermes/profiles/linux-wiki/skills/"
    "learning-materials/visual/Reference_Images/ordering-sheets/"
    "PXL_20260329_134247781.RAW-01.jpg"
)


def main() -> None:
    assert SRC.is_file(), SRC
    print("photo_bytes", SRC.stat().st_size)
    u = CatalogIngestUpload(
        source_kind=CatalogIngestUpload.SourceKind.PHOTO,
        raw_text="",
    )
    with SRC.open("rb") as f:
        u.image.save(SRC.name, File(f), save=True)
    print("upload_id", u.id, "status", u.status, "image", u.image.name)
    res = queue_ingest_extraction(u.id)
    print("queue_result", res)
    u.refresh_from_db()
    print(
        "after_queue",
        u.id,
        u.status,
        "q=",
        u.q_task_id,
        "model=",
        u.model_name,
        "err=",
        (u.error or "")[:300],
    )


if __name__ == "__main__":
    main()
