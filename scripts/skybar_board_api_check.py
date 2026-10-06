#!/usr/bin/env python3
"""curl-equivalent skybar board fetch for template gate evidence."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path("/home/discovery-system/src/evolving-cook")
os.chdir(ROOT)
import sys

sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import django

django.setup()
from django.contrib.auth import get_user_model

from api.auth import issue_token

user = get_user_model().objects.get(email="mykola@apidiscoverysolution.uk")
token = issue_token(user)
BASE = "http://127.0.0.1:8000/api/v1"
HOST = "api.apidiscoverysolution.uk"


def req(method, path, body=None):
    data = None
    headers = {
        "Host": HOST,
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except Exception as e:
        if hasattr(e, "read"):
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return getattr(e, "code", 0), {"detail": raw}
        return 0, {"detail": str(e)}


def main() -> int:
    c, openb = req(
        "POST",
        "/boards/days/open",
        {"service_date": "2026-08-11", "sections": ["skybar"]},
    )
    print(
        "open",
        c,
        {s.get("section"): s.get("line_count") for s in openb.get("sections", [])},
    )
    c, board = req("GET", "/boards/days/2026-08-11/sections/skybar")
    lines = board.get("lines") or []
    print("board", c, "line_count", board.get("line_count"), "lines", len(lines))
    print("modes", sorted({ln.get("mode") for ln in lines}))
    print("sources", sorted({ln.get("source") for ln in lines}))
    print("sum_comps", sum(len(ln.get("components") or []) for ln in lines))
    for ln in sorted(lines, key=lambda x: x.get("name") or ""):
        n = len(ln.get("components") or [])
        print(f"  {n:3d}  {ln.get('name')}")
    out = {
        "http_open": c if False else None,
        "http_board": c,
        "line_count": board.get("line_count"),
        "sum_comps": sum(len(ln.get("components") or []) for ln in lines),
        "per_dish": [
            {
                "name": ln.get("name"),
                "components": len(ln.get("components") or []),
                "mode": ln.get("mode"),
                "source": ln.get("source"),
            }
            for ln in sorted(lines, key=lambda x: x.get("name") or "")
        ],
    }
    # fix open status separately
    c_open, openb = req(
        "POST",
        "/boards/days/open",
        {"service_date": "2026-08-11", "sections": ["skybar"]},
    )
    out["http_open"] = c_open
    out["open_line_counts"] = {
        s.get("section"): s.get("line_count") for s in openb.get("sections", [])
    }
    path = (
        Path.home()
        / ".hermes/profiles/linux-wiki/kanban-deliverables"
        / "evolving-cook-skybar-templates-api.json"
    )
    path.write_text(json.dumps(out, indent=2) + "\n")
    print("WROTE", path)
    return 0 if c == 200 and len(lines) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
