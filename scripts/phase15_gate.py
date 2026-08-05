#!/usr/bin/env python3
"""Phase 1.5 board curl-equivalent gate against local 127.0.0.1:8000."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.contrib.auth import get_user_model

from api.auth import issue_token

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
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return e.code, payload


def main() -> int:
    user = get_user_model().objects.get(email="mykola@apidiscoverysolution.uk")
    token = issue_token(user)
    results = {}

    code, ver = req("GET", "/version")
    results["version"] = {"http": code, "body": ver}
    print("1 version", code, ver)

    code, day = req(
        "POST",
        "/boards/days/open",
        token,
        {"service_date": "2026-08-03", "sections": ["a_la_carte"]},
    )
    results["open_day"] = {
        "http": code,
        "sections": [s.get("section") for s in day.get("sections", [])],
        "status": day.get("status"),
        "line_counts": {s.get("section"): s.get("line_count") for s in day.get("sections", [])},
    }
    print("2 open_day", code, results["open_day"])

    code, board = req(
        "GET", "/boards/days/2026-08-03/sections/a_la_carte", token
    )
    lines = board.get("lines") or []
    results["board"] = {
        "http": code,
        "line_count": board.get("line_count"),
        "covers": board.get("covers"),
        "section": board.get("section"),
        "check_actual_all_null": all(
            ln.get("actual_qty") is None for ln in lines if ln.get("mode") == "check"
        ),
        "sample": [
            {
                "id": ln["id"],
                "name": ln["name"],
                "mode": ln["mode"],
                "status": ln["status"],
                "comps": len(ln.get("components") or []),
            }
            for ln in lines[:3]
        ],
    }
    print("3 board", code, results["board"])

    if not lines:
        print("FAIL: no lines on board")
        print(json.dumps(results, indent=2, default=str))
        return 1

    line_id = lines[0]["id"]
    code, tick = req("POST", f"/boards/lines/{line_id}/tick", token, {})
    tline = (tick.get("line") or tick) if isinstance(tick, dict) else {}
    results["tick"] = {
        "http": code,
        "id": tline.get("id"),
        "status": tline.get("status"),
        "ticked": tline.get("ticked"),
        "actual_qty": tline.get("actual_qty"),
    }
    print("4 tick", code, results["tick"])

    code, qa = req(
        "POST",
        "/boards/lines/quick-add",
        token,
        {
            "service_date": "2026-08-03",
            "section": "a_la_carte",
            "name": "Ad-hoc test garnish",
        },
    )
    qline = (qa.get("line") or qa) if isinstance(qa, dict) else {}
    results["quick_add"] = {
        "http": code,
        "id": qline.get("id"),
        "name": qline.get("name"),
        "source": qline.get("source"),
        "item_id": qline.get("item_id"),
        "mode": qline.get("mode"),
    }
    print("5 quick_add", code, results["quick_add"])

    # re-fetch board once more
    code, board2 = req(
        "GET", "/boards/days/2026-08-03/sections/a_la_carte", token
    )
    results["board_after"] = {
        "http": code,
        "line_count": board2.get("line_count"),
        "ticked_count": board2.get("ticked_count"),
    }
    print("6 board_after", code, results["board_after"])

    openapi = json.loads((ROOT / "docs" / "openapi.json").read_text())
    paths = sorted(openapi.get("paths", {}))
    board_paths = [p for p in paths if "/boards" in p]
    results["openapi"] = {
        "info_version": openapi.get("info", {}).get("version"),
        "board_paths": board_paths,
        "path_count": len(paths),
    }
    print("7 openapi", results["openapi"])

    ok = (
        results["version"]["http"] == 200
        and results["version"]["body"].get("contract_version") == "0.1.5"
        and results["open_day"]["http"] == 200
        and results["board"]["http"] == 200
        and (results["board"]["line_count"] or 0) >= 20
        and results["board"]["covers"] is None
        and results["board"]["check_actual_all_null"] is True
        and results["tick"]["http"] == 200
        and results["tick"]["ticked"] is True
        and results["tick"]["actual_qty"] is None
        and results["quick_add"]["http"] == 200
        and results["quick_add"]["item_id"] is None
        and results["quick_add"]["source"] == "manual"
        and len(board_paths) >= 5
    )
    results["gate"] = "ok" if ok else "fail"
    out = ROOT / "docs" / "phase1.5-gate-evidence.json"
    out.write_text(json.dumps(results, indent=2, default=str) + "\n")
    print("gate", results["gate"], "wrote", out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
