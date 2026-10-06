#!/usr/bin/env python3
"""Live P5 A2A evidence + house_made board. Secrets never printed."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path("/home/discovery-system/src/evolving-cook")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

from api.auth import issue_token
from assist.a2a_client import run_assist_job
from assist.models import AssistJob, AssistProposal
from assist.services import accept_assist_proposal, enqueue_assist_job, handle_agent_event
from assist.views import verify_a2a_signature
from catalog.models import Item
from planning.models import ProductionLine, ServiceSection
from planning.services import generate_lines_from_templates, open_service_day

evidence: dict = {"steps": []}


def log(step: str, **kw):
    evidence["steps"].append({"step": step, **{k: v for k, v in kw.items()}})
    print("OK", step, json.dumps(kw, default=str)[:400], flush=True)


def sign_payload(payload: dict) -> str:
    secret = settings.WEBHOOK_SECRET or ""
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def http_signed_push(payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    sig = hmac.new(
        (settings.WEBHOOK_SECRET or "").encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    # Note: verify uses json.dumps(payload) after loads — same canonical form
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/internal/agent-events",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-A2A-Signature": sig,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            j = json.loads(body)
        except Exception:
            j = {"raw": body[:300]}
        return e.code, j


def main() -> int:
    import urllib.error

    # 1) seed house_made + templates
    from django.core.management import call_command

    call_command("seed_house_made")
    slaw = Item.objects.filter(house_made=True, name__icontains="slaw").order_by("id").first()
    aioli = Item.objects.filter(house_made=True, name__iexact="Aioli").first()
    log(
        "data_house_made",
        slaw={"id": slaw.id, "name": slaw.name, "house_made": slaw.house_made} if slaw else None,
        aioli={"id": aioli.id, "name": aioli.name, "house_made": aioli.house_made} if aioli else None,
        hm_count=Item.objects.filter(house_made=True).count(),
    )

    d = date.today() + timedelta(days=5)
    day = open_service_day(d, sections=["a_la_carte"], generate_lines=True)
    sec = ServiceSection.objects.get(service_day=day, section="a_la_carte")
    generate_lines_from_templates(sec)

    user = get_user_model().objects.filter(is_active=True).order_by("id").first()
    token = issue_token(user)
    client = Client()
    r = client.get(
        f"/api/v1/boards/days/{d.isoformat()}/sections/a_la_carte",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    body = r.json()
    lines = body.get("lines") or []
    hm_lines = [ln for ln in lines if ln.get("item_house_made") is True]
    hm_comps = []
    for ln in lines:
        for c in ln.get("components") or []:
            if c.get("item_house_made") is True:
                hm_comps.append(
                    {
                        "line_name": ln.get("name"),
                        "component": c.get("name"),
                        "item_house_made": True,
                        "item_id": c.get("item_id"),
                    }
                )
    sample = None
    if hm_lines:
        ln = hm_lines[0]
        sample = {
            "id": ln["id"],
            "name": ln["name"],
            "item_id": ln.get("item_id"),
            "item_name": ln.get("item_name"),
            "item_house_made": ln.get("item_house_made"),
        }
    log(
        "board_fetch",
        http=r.status_code,
        service_date=str(d),
        lines=len(lines),
        hm_lines=len(hm_lines),
        hm_comps=len(hm_comps),
        sample_line=sample,
        sample_comps=hm_comps[:5],
    )
    evidence["house_made_ok"] = bool(hm_lines) and r.status_code == 200
    if not evidence["house_made_ok"]:
        db = list(
            ProductionLine.objects.filter(service_section=sec, item__house_made=True)
            .select_related("item")
            .values_list("id", "name", "item_id", "item__house_made")[:10]
        )
        log("board_hm_db_fallback", rows=db)

    # 2) agent card
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:9900/.well-known/agent-card.json", timeout=5
        ) as resp:
            card = json.loads(resp.read().decode())
            log(
                "agent_card",
                http=resp.status,
                name=card.get("name"),
                push=bool((card.get("capabilities") or {}).get("pushNotifications")),
            )
    except Exception as e:
        log("agent_card_fail", error=str(e))
        evidence["a2a_live_ok"] = False
        _write()
        return 1

    # 3) live SendMessage
    target, _ = Item.objects.get_or_create(
        name="P5 Live A2A Note Target",
        defaults={"base_unit": "ea", "active": True, "house_made": False, "notes": ""},
    )
    target.notes = "before-live-a2a"
    target.house_made = False
    target.save(update_fields=["notes", "house_made"])

    job = enqueue_assist_job(
        kind="parse_note",
        context={
            "text": "Set house_made true. note: live a2a gate ok",
            "item_id": target.pk,
            "item_name": target.name,
            "section": "a_la_carte",
            "service_date": str(d),
        },
    )
    # also run sync in case qcluster slow
    tid = run_assist_job(job.pk)
    job.refresh_from_db()
    tid = tid or job.task_id or ""
    log(
        "send_message",
        job_id=job.pk,
        task_id=tid,
        job_status=job.status,
        err=(job.error or "")[:400],
    )
    if not tid:
        evidence["a2a_live_ok"] = False
        evidence["blocked"] = "SendMessage no task_id"
        _write()
        return 2

    prop = None
    waited = 0
    for i in range(90):
        prop = AssistProposal.objects.filter(task_id=tid).first()
        job.refresh_from_db()
        if prop is not None:
            waited = i * 2
            break
        if job.status == AssistJob.Status.FAILED and i >= 3:
            waited = i * 2
            break
        time.sleep(2)
    log(
        "push_wait",
        waited_s=waited,
        proposal_id=getattr(prop, "pk", None),
        prop_status=getattr(prop, "status", None),
        parse_error=(getattr(prop, "parse_error", None) or "")[:200],
        job_status=job.status,
        proposal_snippet=str(getattr(prop, "proposal", None))[:240] if prop else None,
    )
    if prop is None:
        evidence["a2a_live_ok"] = False
        evidence["blocked"] = "no AssistProposal from live push"
        _write()
        return 3

    # 4) accept domain write
    accept_assist_proposal(prop.pk)
    prop.refresh_from_db()
    target.refresh_from_db()
    log(
        "accept",
        status=prop.status,
        decided_at=str(prop.decided_at),
        item_notes=target.notes,
        item_house_made=target.house_made,
    )
    accept_ok = prop.status == AssistProposal.Status.ACCEPTED and prop.decided_at is not None

    # 5) replay same task_id via signed HTTP push — no duplicate, no clobber
    replay_payload = {
        "statusUpdate": {
            "taskId": tid,
            "contextId": str(job.pk),
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "timestamp": "2026-08-04T12:00:00Z",
                "message": {
                    "role": "ROLE_AGENT",
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "note": "SHOULD_NOT_APPLY_ON_REPLAY",
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
    # verify signer matches D11
    assert verify_a2a_signature(
        replay_payload, sign_payload(replay_payload), settings.WEBHOOK_SECRET
    )
    # also exercise handle_agent_event directly (already-verified path)
    direct = handle_agent_event(replay_payload)
    http_code, http_body = http_signed_push(replay_payload)
    count = AssistProposal.objects.filter(task_id=tid).count()
    prop.refresh_from_db()
    target.refresh_from_db()
    log(
        "replay",
        direct_action=direct.get("action"),
        http_code=http_code,
        http_action=http_body.get("action"),
        proposal_count=count,
        status=prop.status,
        notes_unchanged=target.notes != "SHOULD_NOT_APPLY_ON_REPLAY",
        notes=target.notes,
    )
    replay_ok = (
        count == 1
        and prop.status == AssistProposal.Status.ACCEPTED
        and target.notes != "SHOULD_NOT_APPLY_ON_REPLAY"
        and http_code == 200
    )

    evidence["a2a_live_ok"] = bool(tid and prop and accept_ok and replay_ok)
    evidence["send_task_id"] = tid
    evidence["proposal_id"] = prop.pk
    evidence["accept_ok"] = accept_ok
    evidence["replay_ok"] = replay_ok
    evidence["gateway_pid_note"] = "A2A on 127.0.0.1:9900 (agent-card 200; holder=gateway main)"

    _write()
    print(
        "SUMMARY",
        json.dumps(
            {
                "house_made_ok": evidence.get("house_made_ok"),
                "a2a_live_ok": evidence.get("a2a_live_ok"),
                "accept_ok": accept_ok,
                "replay_ok": replay_ok,
                "task_id": tid,
                "proposal_id": prop.pk,
            }
        ),
        flush=True,
    )
    return 0 if evidence.get("a2a_live_ok") and evidence.get("house_made_ok") else 4


def _write():
    path = ROOT / "docs" / "phase5-live-a2a-evidence.json"
    path.write_text(json.dumps(evidence, indent=2, default=str))
    dest = Path.home() / ".hermes/profiles/linux-wiki/kanban-deliverables/evolving-cook-django-phase5-live-evidence.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(path.read_text())
    print("wrote", path, "and", dest, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
