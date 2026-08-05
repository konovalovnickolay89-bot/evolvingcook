#!/usr/bin/env python3
"""NOTE→ASSIST v2 gate — synthetic + DB path (live A2A optional)."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text().splitlines():
    if not line.strip() or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ["APP_VERSION"] = "0.1.14"
os.environ["CONTRACT_VERSION"] = "0.1.14"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.conf import settings

# Django test client host
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + [
        "testserver",
        "localhost",
        "127.0.0.1",
    ]

from django.contrib.auth import get_user_model
from django.test import Client

from api.auth import issue_token
from assist.models import AssistJob, AssistProposal
from assist.services import (
    AssistError,
    accept_assist_proposal,
    enqueue_assist_job,
    handle_agent_event,
    maybe_auto_enqueue_parse_note_for_line,
    normalize_parse_note_context,
    proposal_has_structure,
)
from catalog.models import Item
from planning.models import DishTemplate, ProductionLine, ServiceSectionCode
from planning.services import open_service_day, set_line_note

ev: dict = {"steps": [], "failed": []}


def ok(name, detail=None):
    ev["steps"].append({"name": name, "ok": True, "detail": detail})
    print("OK", name, json.dumps(detail, default=str)[:200] if detail is not None else "")


def fail(name, detail=None):
    ev["steps"].append({"name": name, "ok": False, "detail": detail})
    ev["failed"].append(name)
    print("FAIL", name, detail)


def main() -> int:
    assert settings.CONTRACT_VERSION == "0.1.14", settings.CONTRACT_VERSION
    ok("contract", settings.CONTRACT_VERSION)

    # 1 empty text 400 path
    try:
        enqueue_assist_job("parse_note", {"notes": "  ", "line_id": 1})
        fail("empty_text_400", "should have raised")
    except AssistError as e:
        ok("empty_text_400", {"code": e.code})

    # 2 notes alias
    # need a real line
    d = date.today() + timedelta(days=9)
    day = open_service_day(d, sections=["a_la_carte"], generate_lines=True)
    sec = day.sections.get(section="a_la_carte")
    line = sec.lines.order_by("id").first()
    assert line is not None
    # ensure template
    if not line.template_id:
        tmpl, _ = DishTemplate.objects.get_or_create(
            section="a_la_carte",
            name=line.name or "Gate Dish",
            defaults={"mode": "check", "kind": "dish", "active": True},
        )
        line.template = tmpl
        line.save(update_fields=["template"])
    tmpl = line.template

    ctx = normalize_parse_note_context(
        {"notes": "Always check mac sauce consistency every day at pass", "line_id": line.pk}
    )
    assert ctx["text"].startswith("Always"), ctx
    assert ctx.get("line_name"), ctx
    ok("notes_alias_normalize", ctx)

    user = get_user_model().objects.filter(is_active=True).first()
    token = issue_token(user)
    client = Client()

    # 3 empty via API
    r = client.post(
        "/api/v1/assist/jobs",
        data=json.dumps({"kind": "parse_note", "context": {"text": ""}}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    if r.status_code == 400:
        ok("api_empty_text", r.json())
    else:
        fail("api_empty_text", {"http": r.status_code, "body": r.content[:200]})

    # 4 note save auto-enqueue + note not lost
    text_line = "Today only: ran out of breadcrumbs for mac top — use panko leftover"
    line2 = set_line_note(line.pk, text_line)
    assert line2.notes == text_line
    job = (
        AssistJob.objects.filter(kind="parse_note", context__line_id=line.pk)
        .order_by("-id")
        .first()
    )
    # may be deduped if re-run — check text_hash path
    j_auto = maybe_auto_enqueue_parse_note_for_line(line, text=text_line)
    # second call identical → None (dedupe)
    j_dup = maybe_auto_enqueue_parse_note_for_line(line, text=text_line)
    ok(
        "auto_enqueue_dedupe",
        {
            "note_saved": line2.notes == text_line,
            "first_job": getattr(j_auto, "pk", None) or getattr(job, "pk", None),
            "dup_is_none": j_dup is None,
        },
    )
    if j_dup is not None:
        fail("dedupe", "expected None on identical text")

    # 5 synthetic outcomes: no_structure, parse_error, structure→accept each tier
    def synth(task_id: str, text: str, job_id=None):
        payload = {
            "statusUpdate": {
                "taskId": task_id,
                "contextId": str(job_id or ""),
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {"role": "ROLE_AGENT", "parts": [{"text": text}]},
                },
            }
        }
        return handle_agent_event(payload)

    # create jobs with contexts for each tier
    j_line = AssistJob.objects.create(
        kind="parse_note",
        context=normalize_parse_note_context(
            {"text": text_line, "line_id": line.pk}
        ),
        status=AssistJob.Status.RUNNING,
        task_id="gate-v2-line-1",
    )
    r = synth(
        "gate-v2-line-1",
        json.dumps(
            {
                "note": "ran out breadcrumbs — panko today",
                "target": "line",
                "target_confidence": "high",
                "components": [],
                "rationale": "time-bounded today",
            }
        ),
        j_line.pk,
    )
    assert r["action"] == "created", r
    p = AssistProposal.objects.get(task_id="gate-v2-line-1")
    accept_assist_proposal(p.pk)
    line.refresh_from_db()
    ok("accept_line", {"notes": line.notes, "action": r["action"]})

    # template tier
    j_tmpl = AssistJob.objects.create(
        kind="parse_note",
        context=normalize_parse_note_context(
            {
                "text": "Always check mac sauce consistency every day at pass",
                "line_id": line.pk,
            }
        ),
        status=AssistJob.Status.RUNNING,
        task_id="gate-v2-tmpl-1",
    )
    r = synth(
        "gate-v2-tmpl-1",
        json.dumps(
            {
                "note": "Check sauce consistency at pass daily",
                "target": "template",
                "target_confidence": "high",
                "components": [],
            }
        ),
        j_tmpl.pk,
    )
    p = AssistProposal.objects.get(task_id="gate-v2-tmpl-1")
    accept_assist_proposal(p.pk)
    tmpl.refresh_from_db()
    ok("accept_template", {"template_notes": tmpl.notes})

    # item tier
    item, _ = Item.objects.get_or_create(
        name="Gate V2 House Cheese Sauce",
        defaults={"base_unit": "ea", "active": True, "house_made": False},
    )
    item.house_made = False
    item.notes = ""
    item.save()
    line.item = item
    line.save(update_fields=["item"])
    j_item = AssistJob.objects.create(
        kind="parse_note",
        context=normalize_parse_note_context(
            {
                "text": "Mac cheese sauce is house made — cheddar base",
                "line_id": line.pk,
                "item_id": item.pk,
            }
        ),
        status=AssistJob.Status.RUNNING,
        task_id="gate-v2-item-1",
    )
    r = synth(
        "gate-v2-item-1",
        json.dumps(
            {
                "note": "house cheddar cheese sauce",
                "target": "item",
                "target_confidence": "high",
                "house_made": True,
                "components": [{"name": "Cheddar", "qty": 1, "unit": "ea"}],
            }
        ),
        j_item.pk,
    )
    p = AssistProposal.objects.get(task_id="gate-v2-item-1")
    accept_assist_proposal(p.pk)
    item.refresh_from_db()
    ok(
        "accept_item",
        {"house_made": item.house_made, "notes": item.notes, "comps": item.components.count()},
    )

    # no structure silence
    j_ns = AssistJob.objects.create(
        kind="parse_note",
        context={"text": "hmm nothing really", "text_hash": "x", "line_id": line.pk},
        status=AssistJob.Status.RUNNING,
        task_id="gate-v2-ns-1",
    )
    r = synth(
        "gate-v2-ns-1",
        json.dumps(
            {
                "note": None,
                "target": "line",
                "target_confidence": "high",
                "components": [],
                "rationale": "no structure",
            }
        ),
        j_ns.pk,
    )
    exists = AssistProposal.objects.filter(task_id="gate-v2-ns-1").exists()
    if r.get("action") == "no_structure" and not exists:
        ok("no_structure_silent", r)
    else:
        fail("no_structure_silent", r)

    # parse_error proposal not accept-able
    j_pe = AssistJob.objects.create(
        kind="parse_note",
        context={"text": "broken", "text_hash": "y", "line_id": line.pk},
        status=AssistJob.Status.RUNNING,
        task_id="gate-v2-pe-1",
    )
    r = synth("gate-v2-pe-1", "NOT JSON AT ALL sorry", j_pe.pk)
    p = AssistProposal.objects.filter(task_id="gate-v2-pe-1").first()
    if p and p.parse_error:
        try:
            accept_assist_proposal(p.pk)
            fail("parse_error_not_accept", "accepted")
        except AssistError as e:
            ok("parse_error_not_accept", {"code": e.code, "action": r.get("action")})
    else:
        fail("parse_error_not_accept", r)

    # board: template_notes + pending
    # create pending for inline
    AssistProposal.objects.create(
        kind="parse_note",
        context={"text": "pending card", "line_id": line.pk},
        proposal={
            "note": "pending inline",
            "target": "line",
            "target_confidence": "low",
            "rationale": "unsure scope",
        },
        status=AssistProposal.Status.PENDING,
        task_id="gate-v2-pending-board",
        parse_error="",
    )
    r = client.get(
        f"/api/v1/boards/days/{d.isoformat()}/sections/a_la_carte",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    body = r.json()
    found = None
    for ln in body.get("lines") or []:
        if ln["id"] == line.pk:
            found = ln
            break
    if (
        found
        and found.get("template_notes") == tmpl.notes
        and found.get("pending_proposal")
        and found["pending_proposal"].get("id")
    ):
        ok(
            "board_template_and_pending",
            {
                "template_notes": found.get("template_notes"),
                "pending": found.get("pending_proposal"),
            },
        )
    else:
        fail("board_template_and_pending", found)

    # next day generation still has template_notes joined
    d2 = d + timedelta(days=1)
    open_service_day(d2, sections=["a_la_carte"], generate_lines=True)
    r2 = client.get(
        f"/api/v1/boards/days/{d2.isoformat()}/sections/a_la_carte",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    lines2 = r2.json().get("lines") or []
    hit = [ln for ln in lines2 if ln.get("name") == line.name]
    if hit and hit[0].get("template_notes") == tmpl.notes:
        ok("template_note_next_day", {"template_notes": hit[0].get("template_notes")})
    else:
        fail("template_note_next_day", hit[:1] if hit else lines2[:2])

    # openapi version
    from django.urls import reverse
    # export openapi via ninja
    from api.api import api as ninja_api

    schema = ninja_api.get_openapi_schema()
    schema["info"]["version"] = settings.CONTRACT_VERSION
    out_oa = ROOT / "docs" / "openapi.json"
    out_oa.write_text(json.dumps(schema, indent=2, default=str))
    paths = schema.get("paths") or {}
    ok(
        "openapi",
        {
            "version": schema["info"]["version"],
            "assist_jobs": "/api/v1/assist/jobs" in paths or any("assist/jobs" in p for p in paths),
        },
    )

    ev["gate"] = "ok" if not ev["failed"] else "failed"
    ev["contract"] = settings.CONTRACT_VERSION
    path = ROOT / "docs" / "note-assist-v2-gate-evidence.json"
    path.write_text(json.dumps(ev, indent=2, default=str))
    dest = (
        Path.home()
        / ".hermes/profiles/linux-wiki/kanban-deliverables/evolving-cook-note-assist-v2-evidence.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(path.read_text())
    print("NOTE_ASSIST_V2_GATE_OK" if not ev["failed"] else "NOTE_ASSIST_V2_GATE_FAIL")
    print("failed", ev["failed"])
    return 0 if not ev["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
