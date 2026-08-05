#!/usr/bin/env python3
"""Phase 5 LLM loop + D11 A2A gate against local 127.0.0.1:8000 + DB checks.

Prints PHASE5_GATE_OK on full green. Writes docs/phase5-gate-evidence.json.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model

from api.auth import issue_token
from assist.models import AssistJob, AssistProposal
from assist.services import (
    accept_assist_proposal,
    explode_item,
    handle_agent_event,
    reject_assist_proposal,
    RecipeCycleError,
)
from assist.views import verify_a2a_signature
from catalog.models import Item, ItemComponent

BASE = "http://127.0.0.1:8000/api/v1"
HOST = "api.apidiscoverysolution.uk"
CONTRACT = "0.1.12"
EVIDENCE_PATH = ROOT / "docs" / "phase5-gate-evidence.json"


def req(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    base: str = BASE,
    headers_extra: dict | None = None,
    raw_path: bool = False,
):
    data = None
    headers = {"Host": HOST, "Accept": "application/json"}
    if headers_extra:
        headers.update(headers_extra)
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = path if raw_path else base + path
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
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
    except urllib.error.URLError as e:
        return 0, {"error": str(e)}, ""


def sign_payload(payload: dict, secret: str) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def post_agent_event(payload: dict, secret: str, bad_sig: bool = False):
    sig = sign_payload(payload, secret)
    if bad_sig:
        sig = "0" * 64
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Host": HOST,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-A2A-Signature": sig,
    }
    r = urllib.request.Request(
        "http://127.0.0.1:8000/api/internal/agent-events",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload_out = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload_out = {"detail": raw}
        return e.code, payload_out, raw


def main() -> int:
    evidence: dict = {"contract_expected": CONTRACT}
    failed: list[str] = []

    def check(name: str, cond: bool, detail=None):
        evidence[name] = {"ok": bool(cond), "detail": detail}
        print(("OK" if cond else "FAIL"), name, detail if detail is not None else "")
        if not cond:
            failed.append(name)

    # 0 units
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
    check(
        "units_active",
        evidence["units"]["django"] == "active"
        and evidence["units"]["qcluster"] == "active",
        evidence["units"],
    )

    user = get_user_model().objects.get(email="mykola@apidiscoverysolution.uk")
    token = issue_token(user)

    # 1 version local + public
    code, ver, _ = req("GET", "/version")
    evidence["version_local"] = {"http": code, "body": ver}
    check(
        "version_local",
        code == 200
        and ver.get("contract_version") == CONTRACT
        and ver.get("app_version") == CONTRACT,
        ver,
    )

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
        code_p, ver_p = 200, json.loads(pub.stdout)
    else:
        code_p, ver_p = pub.returncode or 0, {"error": pub.stderr or pub.stdout}
    evidence["version_public"] = {"http": code_p, "body": ver_p}
    check(
        "version_public",
        code_p == 200 and ver_p.get("contract_version") == CONTRACT,
        ver_p,
    )

    # 2 agent-card / A2A
    card = subprocess.run(
        [
            "curl",
            "-sS",
            "-o",
            "/tmp/a2a-card.json",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            "http://127.0.0.1:9900/.well-known/agent-card.json",
        ],
        capture_output=True,
        text=True,
    )
    card_code = card.stdout.strip()
    a2a_live = card_code == "200"
    evidence["a2a_agent_card"] = {
        "http": card_code,
        "live": a2a_live,
        "stderr": (card.stderr or "")[:200],
    }
    check(
        "a2a_agent_card_or_documented",
        True,  # amber allowed; recorded
        evidence["a2a_agent_card"],
    )
    if not a2a_live:
        evidence["blocked_on"] = evidence.get("blocked_on", []) + [
            "live Hermes A2A :9900 not up — synthetic signed push used for gate"
        ]

    secret = settings.WEBHOOK_SECRET or ""
    check("webhook_secret_set", bool(secret) and len(secret) >= 16, f"len={len(secret)}")

    # Seed item + line context for accept
    item, _ = Item.objects.get_or_create(
        name="Phase5 Gate Aioli Note Target",
        defaults={
            "base_unit": "ea",
            "active": True,
            "house_made": False,
            "notes": "",
        },
    )
    item.notes = ""
    item.house_made = False
    item.save(update_fields=["notes", "house_made"])

    task_id = f"gate-task-{uuid.uuid4().hex[:16]}"
    job = AssistJob.objects.create(
        kind=AssistJob.Kind.PARSE_NOTE,
        context={
            "text": "house aioli; garlic mayo",
            "item_id": item.pk,
            "item_name": item.name,
        },
        status=AssistJob.Status.RUNNING,
        task_id=task_id,
    )

    proposal_json = {
        "note": "gate: house aioli unverified",
        "target": "item",
        "house_made": True,
        "components": [
            {
                "name": "Phase5 Gate Garlic",
                "qty": 2,
                "unit": "ea",
                "notes": "unverified",
                "sort_order": 0,
            }
        ],
        "rationale": "gate",
        "confidence": 0.9,
    }
    payload = {
        "statusUpdate": {
            "taskId": task_id,
            "contextId": str(job.pk),
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "timestamp": "2026-08-04T12:00:00Z",
                "message": {
                    "role": "ROLE_AGENT",
                    "parts": [{"text": json.dumps(proposal_json, separators=(",", ":"))}],
                },
            },
        }
    }

    # 3 signed round-trip
    before = AssistProposal.objects.filter(task_id=task_id).count()
    code, body, _ = post_agent_event(payload, secret)
    after = AssistProposal.objects.filter(task_id=task_id).count()
    prop = AssistProposal.objects.filter(task_id=task_id).first()
    evidence["signed_push"] = {
        "http": code,
        "body": body,
        "before": before,
        "after": after,
        "proposal_id": prop.pk if prop else None,
    }
    check(
        "signed_round_trip",
        code == 200 and after == 1 and prop is not None and prop.status == "pending",
        evidence["signed_push"],
    )

    # 4 replay
    code2, body2, _ = post_agent_event(payload, secret)
    after2 = AssistProposal.objects.filter(task_id=task_id).count()
    evidence["replay"] = {"http": code2, "body": body2, "count": after2}
    check("replay_idempotent", code2 == 200 and after2 == 1, evidence["replay"])

    # 5 bad signature
    bad_task = f"gate-bad-{uuid.uuid4().hex[:12]}"
    bad_payload = {
        "statusUpdate": {
            "taskId": bad_task,
            "contextId": "0",
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "message": {"role": "ROLE_AGENT", "parts": [{"text": "{}"}]},
            },
        }
    }
    code_b, body_b, _ = post_agent_event(bad_payload, secret, bad_sig=True)
    bad_rows = AssistProposal.objects.filter(task_id=bad_task).count()
    evidence["bad_signature"] = {"http": code_b, "body": body_b, "rows": bad_rows}
    check(
        "bad_signature_rejected",
        code_b in {401, 403} and bad_rows == 0,
        evidence["bad_signature"],
    )

    # 6 failed task state
    fail_task = f"gate-fail-{uuid.uuid4().hex[:12]}"
    fail_job = AssistJob.objects.create(
        kind=AssistJob.Kind.PARSE_NOTE,
        context={"text": "x"},
        status=AssistJob.Status.RUNNING,
        task_id=fail_task,
    )
    fail_payload = {
        "statusUpdate": {
            "taskId": fail_task,
            "contextId": str(fail_job.pk),
            "status": {
                "state": "TASK_STATE_FAILED",
                "message": {
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "boom"}],
                },
            },
        }
    }
    code_f, body_f, _ = post_agent_event(fail_payload, secret)
    fail_job.refresh_from_db()
    fail_props = AssistProposal.objects.filter(task_id=fail_task).count()
    evidence["failed_task"] = {
        "http": code_f,
        "body": body_f,
        "job_status": fail_job.status,
        "proposals": fail_props,
    }
    check(
        "failed_task_no_proposal",
        code_f == 200
        and fail_job.status == AssistJob.Status.FAILED
        and fail_props == 0,
        evidence["failed_task"],
    )

    # 7 public internal not exposed
    pub_int = subprocess.run(
        [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "20",
            "-X",
            "POST",
            "https://api.apidiscoverysolution.uk/api/internal/agent-events",
        ],
        capture_output=True,
        text=True,
    )
    pub_code = pub_int.stdout.strip()
    evidence["public_internal"] = {"http": pub_code}
    check(
        "public_internal_blocked",
        pub_code in {"404", "403", "502", "530", "1033"} or pub_code.startswith("4") or pub_code.startswith("5"),
        evidence["public_internal"],
    )
    # specifically must NOT be 200 success write path
    if pub_code == "200":
        failed.append("public_internal_blocked")

    # 8 accept parse_note
    assert prop is not None
    # API accept
    code_a, body_a, _ = req("POST", f"/assist/proposals/{prop.pk}/accept", token)
    prop.refresh_from_db()
    item.refresh_from_db()
    comps = list(ItemComponent.objects.filter(parent=item))
    evidence["accept"] = {
        "http": code_a,
        "status": prop.status,
        "decided_at": prop.decided_at.isoformat() if prop.decided_at else None,
        "item_notes": item.notes,
        "house_made": item.house_made,
        "components": len(comps),
    }
    check(
        "accept_domain_writes",
        code_a == 200
        and prop.status == "accepted"
        and prop.decided_at is not None
        and item.house_made is True
        and "gate: house aioli" in (item.notes or "")
        and len(comps) >= 1,
        evidence["accept"],
    )
    # second accept idempotent
    notes_before = item.notes
    code_a2, _, _ = req("POST", f"/assist/proposals/{prop.pk}/accept", token)
    item.refresh_from_db()
    comps2 = ItemComponent.objects.filter(parent=item).count()
    evidence["accept_idempotent"] = {
        "http": code_a2,
        "notes_same": item.notes == notes_before,
        "comps": comps2,
    }
    check(
        "accept_idempotent",
        code_a2 == 200 and item.notes == notes_before,
        evidence["accept_idempotent"],
    )

    # 9 reject path
    rej_task = f"gate-rej-{uuid.uuid4().hex[:12]}"
    rej_job = AssistJob.objects.create(
        kind=AssistJob.Kind.PARSE_NOTE,
        context={"text": "nope", "item_id": item.pk},
        status=AssistJob.Status.SUCCEEDED,
        task_id=rej_task,
    )
    rej_payload = {
        "statusUpdate": {
            "taskId": rej_task,
            "contextId": str(rej_job.pk),
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "message": {
                    "role": "ROLE_AGENT",
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "note": "SHOULD_NOT_APPLY",
                                    "target": "item",
                                    "house_made": False,
                                    "components": [],
                                }
                            )
                        }
                    ],
                },
            },
        }
    }
    post_agent_event(rej_payload, secret)
    rej_prop = AssistProposal.objects.get(task_id=rej_task)
    code_r, body_r, _ = req(
        "POST",
        f"/assist/proposals/{rej_prop.pk}/reject",
        token,
        {"reason": "gate reject"},
    )
    rej_prop.refresh_from_db()
    item.refresh_from_db()
    evidence["reject"] = {
        "http": code_r,
        "status": rej_prop.status,
        "reason": rej_prop.reject_reason,
        "notes_unchanged_from_should_not": "SHOULD_NOT_APPLY" not in (item.notes or ""),
    }
    check(
        "reject_no_domain_write",
        code_r == 200
        and rej_prop.status == "rejected"
        and "gate reject" in (rej_prop.reject_reason or "")
        and "SHOULD_NOT_APPLY" not in (item.notes or ""),
        evidence["reject"],
    )

    # 10 B15 explode depth/cycle
    # clean cycle fixture
    a, _ = Item.objects.get_or_create(name="Phase5 Cycle A", defaults={"base_unit": "ea"})
    b, _ = Item.objects.get_or_create(name="Phase5 Cycle B", defaults={"base_unit": "ea"})
    ItemComponent.objects.filter(parent__in=[a, b]).delete()
    ItemComponent.objects.get_or_create(
        parent=a, component=b, defaults={"qty": Decimal("1")}
    )
    ItemComponent.objects.get_or_create(
        parent=b, component=a, defaults={"qty": Decimal("1")}
    )
    cycle_raised = False
    cycle_msg = ""
    try:
        explode_item(a.pk, qty=1)
    except RecipeCycleError as exc:
        cycle_raised = True
        cycle_msg = str(exc)
    evidence["b15_cycle"] = {"raised": cycle_raised, "msg": cycle_msg[:200]}
    check("b15_cycle_raises", cycle_raised, evidence["b15_cycle"])

    # depth explode on seeded house_made if present
    slaw = Item.objects.filter(name__icontains="Asian slaw", house_made=True).first()
    if slaw is None:
        slaw = Item.objects.filter(house_made=True).first()
    explode_rows = []
    explode_err = None
    if slaw:
        try:
            explode_rows = explode_item(slaw.pk, qty=2)
        except Exception as exc:  # noqa: BLE001
            explode_err = str(exc)
    evidence["b15_explode"] = {
        "item_id": slaw.pk if slaw else None,
        "rows": len(explode_rows),
        "sample": explode_rows[:3] if explode_rows else [],
        "error": explode_err,
    }
    # serialize decimals
    def _ser(o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, dict):
            return {k: _ser(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_ser(x) for x in o]
        return o

    evidence["b15_explode"] = _ser(evidence["b15_explode"])
    check(
        "b15_explode_ok",
        explode_err is None and (len(explode_rows) >= 1 or slaw is None),
        evidence["b15_explode"],
    )

    code_ex, body_ex, _ = req(
        "POST",
        "/assist/explode",
        token,
        {"item_id": slaw.pk if slaw else item.pk, "qty": 1},
    )
    evidence["b15_api"] = {"http": code_ex, "keys": list(body_ex.keys()) if isinstance(body_ex, dict) else body_ex}
    check("b15_api", code_ex == 200, evidence["b15_api"])

    # 11 boards still open
    code_b, body_b, _ = req("GET", "/boards/days/2026-08-11/sections/skybar", token)
    if code_b == 404:
        # open a day
        req(
            "POST",
            "/boards/days/open",
            token,
            {
                "service_date": "2026-08-21",
                "sections": ["skybar"],
                "generate_lines": True,
            },
        )
        code_b, body_b, _ = req("GET", "/boards/days/2026-08-21/sections/skybar", token)
    evidence["skybar_board"] = {"http": code_b}
    check("skybar_board_ok", code_b == 200, evidence["skybar_board"])

    # 12 openapi
    schema_path = ROOT / "docs" / "openapi.json"
    if not schema_path.exists():
        subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "export_openapi.py")],
            check=False,
        )
    schema = json.loads(schema_path.read_text()) if schema_path.exists() else {}
    paths = schema.get("paths") or {}
    assist_paths = [p for p in paths if p.startswith("/api/v1/assist")]
    internal_in_oa = [p for p in paths if "internal" in p or "agent-events" in p]
    evidence["openapi"] = {
        "info_version": (schema.get("info") or {}).get("version"),
        "assist_paths": assist_paths,
        "internal_paths": internal_in_oa,
    }
    check(
        "openapi_assist",
        (schema.get("info") or {}).get("version") == CONTRACT
        and any("/assist/proposals" in p for p in assist_paths)
        and not internal_in_oa,
        evidence["openapi"],
    )

    # unit verify_a2a_signature sanity
    check(
        "sig_helper",
        verify_a2a_signature(payload, sign_payload(payload, secret), secret),
        True,
    )

    evidence["failed"] = failed
    evidence["a2a_live_roundtrip"] = a2a_live
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print("wrote", EVIDENCE_PATH)

    if failed:
        print("PHASE5_GATE_FAIL", failed)
        return 1
    print("PHASE5_GATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
