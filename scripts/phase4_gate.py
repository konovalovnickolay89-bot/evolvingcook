#!/usr/bin/env python3
"""Phase 4 full planner gate against local 127.0.0.1:8000 + DB checks.

Minimum green checks:
  1. version local + public 200; contract 0.1.11
  2. open day without covers (skybar / breakfast)
  3. open banqueting + banquet_buffet; BEO covers; ≥2 waves; produce lines
  4. scale → proposed_qty (or documented null path); PATCH planned_qty
  5. WaveAllocation: one line across two waves; unique constraint
  6. canteen produce line: set planned/actual without covers
  7. day close + outturn; closed day rejects mutating board ops
  8. non-banquet board never requires covers
  9. units django+qcluster active
 10. openapi lists new paths; info.version matches
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
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
from django.db import IntegrityError, transaction

from api.auth import issue_token
from planning.models import DishTemplate, ProductionLine, WaveAllocation

BASE = "http://127.0.0.1:8000/api/v1"
HOST = "api.apidiscoverysolution.uk"
CONTRACT = "0.1.11"
GATE_DATE = "2026-08-20"  # dedicated gate day — avoid clobbering live boards


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


def seed_banquet_template() -> dict:
    """Ensure one banquet produce template with yield_per_cover for scale path."""
    tmpl, created = DishTemplate.objects.update_or_create(
        section="banqueting",
        name="Phase4 Gate Banquet Roast",
        defaults={
            "mode": DishTemplate.Mode.PRODUCE,
            "kind": DishTemplate.Kind.DISH,
            "category": "banqueting",
            "unit": "ea",
            "active": True,
            "sort_order": 1,
            "yield_per_cover": Decimal("1.0"),
            "notes": "gate-only template; yield_per_cover set for scale evidence",
        },
    )
    # null-yield template for documented null path
    null_tmpl, _ = DishTemplate.objects.update_or_create(
        section="banqueting",
        name="Phase4 Gate No-Yield Canape",
        defaults={
            "mode": DishTemplate.Mode.PRODUCE,
            "kind": DishTemplate.Kind.DISH,
            "category": "banqueting",
            "unit": "ea",
            "active": True,
            "sort_order": 2,
            "yield_per_cover": None,
            "notes": "gate null path — no yield_per_cover",
        },
    )
    # buffet section template (produce, no yield required for wave tests)
    bb, _ = DishTemplate.objects.update_or_create(
        section="banquet_buffet",
        name="Phase4 Gate Buffet Hot",
        defaults={
            "mode": DishTemplate.Mode.PRODUCE,
            "kind": DishTemplate.Kind.BUFFET,
            "category": "banquet_buffet",
            "unit": "ea",
            "active": True,
            "sort_order": 1,
            "yield_per_cover": Decimal("0.5"),
        },
    )
    return {
        "banquet_with_yield": {"id": tmpl.pk, "created": created, "ypc": str(tmpl.yield_per_cover)},
        "banquet_null_yield": {"id": null_tmpl.pk, "ypc": None},
        "buffet": {"id": bb.pk, "ypc": str(bb.yield_per_cover)},
    }


def reset_gate_day() -> None:
    """Idempotent: wipe gate day so re-runs start clean (covers/waves/outturn)."""
    from planning.models import ServiceDay

    ServiceDay.objects.filter(service_date=GATE_DATE).delete()


def main() -> int:
    evidence: dict = {"contract_expected": CONTRACT, "gate_date": GATE_DATE}

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
    assert evidence["units"]["qcluster"] == "active", evidence["units"]

    seed = seed_banquet_template()
    evidence["seed_templates"] = seed
    reset_gate_day()

    user = get_user_model().objects.get(email="mykola@apidiscoverysolution.uk")
    token = issue_token(user)

    # 1 version local + public
    code, ver, _ = req("GET", "/version")
    evidence["version_local"] = {"http": code, "body": ver}
    print("1 version_local", code, ver)
    assert code == 200, ver
    assert ver.get("contract_version") == CONTRACT, ver
    assert ver.get("app_version") == CONTRACT, ver

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

    # 2 open day without covers — skybar + breakfast
    code, day, raw = req(
        "POST",
        "/boards/days/open",
        token,
        {
            "service_date": GATE_DATE,
            "sections": ["skybar", "breakfast_buffet", "banqueting", "banquet_buffet", "canteen"],
            "generate_lines": True,
        },
    )
    evidence["open_day"] = {
        "http": code,
        "status": day.get("status"),
        "sections": [
            {
                "section": s.get("section"),
                "covers": s.get("covers"),
                "line_count": s.get("line_count"),
            }
            for s in day.get("sections", [])
        ],
    }
    print("2 open_day", code, evidence["open_day"])
    assert code == 200, day
    assert day.get("status") == "open"
    for s in day.get("sections", []):
        assert s.get("covers") is None, s

    code, sky, _ = req("GET", f"/boards/days/{GATE_DATE}/sections/skybar", token)
    evidence["skybar_board"] = {
        "http": code,
        "covers": sky.get("covers"),
        "line_count": sky.get("line_count"),
        "day_status": sky.get("day_status"),
    }
    print("2b skybar", evidence["skybar_board"])
    assert code == 200
    assert sky.get("covers") is None
    assert (sky.get("line_count") or 0) >= 1

    code, bf, _ = req(
        "POST",
        f"/boards/days/{GATE_DATE}/sections/breakfast_buffet/open",
        token,
        {"generate_lines": True},
    )
    evidence["breakfast_board"] = {
        "http": code,
        "covers": bf.get("covers"),
        "line_count": bf.get("line_count"),
    }
    print("2c breakfast", evidence["breakfast_board"])
    assert code == 200
    assert bf.get("covers") is None

    # 3 banquet covers + waves
    code, banq, _ = req(
        "PATCH",
        f"/boards/days/{GATE_DATE}/sections/banqueting/covers",
        token,
        {
            "covers": 100,
            "covers_source": "beo",
            "beo_events": [
                {"name": "Wedding lunch", "covers": 60},
                {"name": "Corp dinner", "covers": 40},
            ],
        },
    )
    evidence["banquet_covers"] = {
        "http": code,
        "covers": banq.get("covers"),
        "covers_source": banq.get("covers_source"),
        "beo_events": banq.get("beo_events"),
        "line_count": banq.get("line_count"),
    }
    print("3 banquet_covers", evidence["banquet_covers"])
    assert code == 200, banq
    assert banq.get("covers") == 100
    assert banq.get("covers_source") == "beo"
    assert len(banq.get("beo_events") or []) == 2
    assert (banq.get("line_count") or 0) >= 2

    code, bb_cov, _ = req(
        "PATCH",
        f"/boards/days/{GATE_DATE}/sections/banquet_buffet/covers",
        token,
        {"covers": 80, "covers_source": "beo", "beo_events": [{"name": "Buffet A", "covers": 80}]},
    )
    evidence["buffet_covers"] = {"http": code, "covers": bb_cov.get("covers")}
    assert code == 200, bb_cov

    code, w1, _ = req(
        "POST",
        f"/boards/days/{GATE_DATE}/sections/banqueting/waves",
        token,
        {"name": "Wave 1 lunch", "covers": 60, "serve_at": "12:30:00", "sort_order": 10},
    )
    code2, w2, _ = req(
        "POST",
        f"/boards/days/{GATE_DATE}/sections/banqueting/waves",
        token,
        {"name": "Wave 2 dinner", "covers": 40, "serve_at": "19:00:00", "sort_order": 20},
    )
    evidence["waves"] = {"w1": {"http": code, "body": w1}, "w2": {"http": code2, "body": w2}}
    print("3b waves", evidence["waves"])
    assert code == 200 and code2 == 200, evidence["waves"]
    wave_ids = [w1["id"], w2["id"]]

    code, board_b, _ = req("GET", f"/boards/days/{GATE_DATE}/sections/banqueting", token)
    assert code == 200
    produce_lines = [ln for ln in board_b.get("lines", []) if ln.get("mode") == "produce"]
    evidence["banquet_lines"] = [
        {
            "id": ln["id"],
            "name": ln["name"],
            "mode": ln["mode"],
            "yield_per_cover": ln.get("yield_per_cover"),
            "proposed_qty": ln.get("proposed_qty"),
        }
        for ln in produce_lines
    ]
    print("3c produce_lines", evidence["banquet_lines"])
    assert len(produce_lines) >= 2

    # 4 scale proposed
    code, scale, _ = req(
        "POST",
        f"/boards/days/{GATE_DATE}/sections/banqueting/scale-produce",
        token,
        None,
    )
    evidence["scale"] = {"http": code, "body": scale}
    print("4 scale", code, scale)
    assert code == 200, scale
    assert scale.get("formula")
    # with yield: sum wave covers 60+40=100 * 1.0 = 100
    updated = scale.get("updated") or []
    skipped = scale.get("skipped_null_path") or []
    assert scale.get("scaling_covers") == 100
    assert any(u.get("proposed_qty") == 100 for u in updated), updated
    assert any(s.get("reason") == "no_yield_per_cover" for s in skipped), skipped

    # pick scaled line for planned + allocations
    scaled_id = next(u["line_id"] for u in updated if u.get("proposed_qty") == 100)
    code, pl, raw = req(
        "PATCH",
        f"/boards/lines/{scaled_id}/qty",
        token,
        {"planned_qty": 95, "set_planned": True},
    )
    line_body = (pl.get("line") or pl) if isinstance(pl, dict) else {}
    evidence["patch_planned"] = {
        "http": code,
        "planned_qty": line_body.get("planned_qty"),
        "proposed_qty": line_body.get("proposed_qty"),
        "planned_qty_type": type(line_body.get("planned_qty")).__name__,
    }
    print("4b planned", evidence["patch_planned"])
    assert code == 200, pl
    assert line_body.get("planned_qty") == 95
    assert isinstance(line_body.get("planned_qty"), (int, float))
    assert line_body.get("proposed_qty") == 100

    # 5 WaveAllocation one line two waves
    code, allocs, _ = req(
        "PUT",
        f"/boards/lines/{scaled_id}/wave-allocations",
        token,
        {
            "allocations": [
                {"wave_id": wave_ids[0], "qty": 55},
                {"wave_id": wave_ids[1], "qty": 40},
            ]
        },
    )
    evidence["wave_allocations"] = {"http": code, "body": allocs}
    print("5 allocations", code, allocs)
    assert code == 200, allocs
    assert len(allocs.get("allocations") or []) == 2
    # same line id only once on board
    code, board_b2, _ = req("GET", f"/boards/days/{GATE_DATE}/sections/banqueting", token)
    names = [ln["name"] for ln in board_b2.get("lines", []) if ln["id"] == scaled_id]
    assert len(names) == 1
    line_again = next(ln for ln in board_b2["lines"] if ln["id"] == scaled_id)
    assert len(line_again.get("wave_allocations") or []) == 2

    # unique constraint at DB
    uniq_ok = False
    uniq_err = ""
    try:
        with transaction.atomic():
            WaveAllocation.objects.create(
                line_id=scaled_id, wave_id=wave_ids[0], qty=Decimal("1")
            )
    except IntegrityError as e:
        uniq_ok = True
        uniq_err = type(e).__name__
    evidence["unique_line_wave"] = {"enforced": uniq_ok, "error": uniq_err}
    print("5b unique", evidence["unique_line_wave"])
    assert uniq_ok

    # 6 canteen produce without covers
    code, canteen_open, _ = req(
        "POST",
        f"/boards/days/{GATE_DATE}/sections/canteen/open",
        token,
        {"generate_lines": True},
    )
    assert code == 200, canteen_open
    assert canteen_open.get("covers") is None
    code, qa, _ = req(
        "POST",
        "/boards/lines/quick-add",
        token,
        {
            "service_date": GATE_DATE,
            "section": "canteen",
            "name": "Staff curry pot",
            "mode": "produce",
            "kind": "dish",
        },
    )
    cline = qa.get("line") or qa
    evidence["canteen_quick_add"] = {"http": code, "id": cline.get("id"), "mode": cline.get("mode")}
    assert code == 200, qa
    cid = cline["id"]
    code, cq, _ = req(
        "PATCH",
        f"/boards/lines/{cid}/qty",
        token,
        {"planned_qty": 30, "actual_qty": 28, "set_planned": True, "set_actual": True},
    )
    cl = cq.get("line") or cq
    evidence["canteen_qty"] = {
        "http": code,
        "planned_qty": cl.get("planned_qty"),
        "actual_qty": cl.get("actual_qty"),
        "covers_on_board": None,
    }
    print("6 canteen", evidence["canteen_qty"])
    assert code == 200, cq
    assert cl.get("planned_qty") == 30
    assert cl.get("actual_qty") == 28
    code, cboard, _ = req("GET", f"/boards/days/{GATE_DATE}/sections/canteen", token)
    assert cboard.get("covers") is None

    # 8 still true before close — non-banquet never requires covers (skybar still null)
    assert sky.get("covers") is None

    # 7 day close + outturn + reject mutate
    code, closed, _ = req(
        "POST",
        f"/boards/days/{GATE_DATE}/close",
        token,
        {
            "notes": "phase4 gate close",
            "section_outturns": {"canteen": {"covers_actual_informational": 45}},
        },
    )
    evidence["close"] = {
        "http": code,
        "status": closed.get("status"),
        "closed_at": closed.get("closed_at"),
        "outturn_keys": list((closed.get("outturn") or {}).keys()),
        "has_sections_outturn": bool((closed.get("outturn") or {}).get("sections")),
    }
    print("7 close", evidence["close"])
    assert code == 200, closed
    assert closed.get("status") == "closed"
    assert closed.get("outturn")
    assert closed["outturn"].get("sections")

    code, rej, raw = req(
        "POST",
        f"/boards/lines/{cid}/tick",
        token,
        {},
    )
    evidence["closed_reject_tick"] = {"http": code, "body": rej, "raw": raw[:300]}
    print("7b reject", code, rej)
    assert code == 409, rej
    assert "day_closed" in str(rej.get("detail", raw))

    code, rej2, _ = req(
        "PATCH",
        f"/boards/lines/{cid}/qty",
        token,
        {"planned_qty": 99, "set_planned": True},
    )
    evidence["closed_reject_qty"] = {"http": code, "detail": rej2.get("detail")}
    assert code == 409

    # 9 units still active
    unit2 = subprocess.run(
        ["systemctl", "--user", "is-active", "evolving-cook-django.service"],
        capture_output=True,
        text=True,
    )
    qunit2 = subprocess.run(
        ["systemctl", "--user", "is-active", "evolving-cook-qcluster.service"],
        capture_output=True,
        text=True,
    )
    evidence["units_after"] = {
        "django": unit2.stdout.strip(),
        "qcluster": qunit2.stdout.strip(),
    }
    print("9 units_after", evidence["units_after"])
    assert evidence["units_after"]["django"] == "active"
    assert evidence["units_after"]["qcluster"] == "active"

    # 10 openapi
    openapi_path = ROOT / "docs" / "openapi.json"
    openapi = json.loads(openapi_path.read_text())
    paths = sorted(openapi.get("paths", {}))
    needed = [
        "/api/v1/boards/days/{service_date}/close",
        "/api/v1/boards/days/{service_date}/sections/{section}/covers",
        "/api/v1/boards/days/{service_date}/sections/{section}/waves",
        "/api/v1/boards/lines/{line_id}/wave-allocations",
        "/api/v1/boards/lines/{line_id}/qty",
        "/api/v1/boards/days/{service_date}/sections/{section}/scale-produce",
    ]
    missing = [p for p in needed if p not in openapi.get("paths", {})]
    evidence["openapi"] = {
        "info_version": openapi.get("info", {}).get("version"),
        "path_count": len(paths),
        "needed_present": not missing,
        "missing": missing,
        "board_paths": [p for p in paths if "/boards" in p],
    }
    print("10 openapi", evidence["openapi"]["info_version"], "missing", missing)
    assert evidence["openapi"]["info_version"] == CONTRACT
    assert not missing, missing

    # BEO rejected on non-banquet
    code, bad_beo, _ = req(
        "PATCH",
        f"/boards/days/{GATE_DATE}/sections/skybar/covers",
        token,
        {"covers": 10, "covers_source": "beo"},
    )
    # day is closed — expect 409 day_closed rather than beo; reopen to test lock
    # Re-open day
    code_ro, _, _ = req(
        "POST",
        "/boards/days/open",
        token,
        {"service_date": GATE_DATE, "sections": ["skybar"], "generate_lines": False},
    )
    evidence["reopen"] = {"http": code_ro}
    assert code_ro == 200
    code, bad_beo, _ = req(
        "PATCH",
        f"/boards/days/{GATE_DATE}/sections/skybar/covers",
        token,
        {"covers": 10, "covers_source": "beo"},
    )
    evidence["beo_on_skybar_rejected"] = {"http": code, "detail": bad_beo.get("detail")}
    print("8 beo_skybar", evidence["beo_on_skybar_rejected"])
    assert code == 400
    assert "beo_section_only" in str(bad_beo.get("detail", ""))

    # Non-banquet covers still optional — leave skybar null after failed beo
    code, sky2, _ = req("GET", f"/boards/days/{GATE_DATE}/sections/skybar", token)
    evidence["skybar_after"] = {"http": code, "covers": sky2.get("covers")}
    assert sky2.get("covers") is None

    evidence["gate"] = "ok"
    out = ROOT / "docs" / "phase4-gate-evidence.json"
    out.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    print("PHASE4_GATE_OK")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print("PHASE4_GATE_FAIL", e)
        raise
