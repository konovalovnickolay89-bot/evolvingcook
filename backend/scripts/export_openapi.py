#!/usr/bin/env python3
"""Export OpenAPI schema to docs/openapi.json (stable committed path)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Load .env before django setup
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from api.api import api  # noqa: E402

out = ROOT / "docs" / "openapi.json"
out.parent.mkdir(parents=True, exist_ok=True)
schema = api.get_openapi_schema()
out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {out}")
