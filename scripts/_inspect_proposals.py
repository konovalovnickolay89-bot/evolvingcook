#!/usr/bin/env python
import os
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from assist.models import AssistProposal, AssistJob
from django.contrib.auth import get_user_model

User = get_user_model()
print("users", list(User.objects.values_list("username", "email")[:10]))
print(
    "proposal_count",
    AssistProposal.objects.count(),
    "pending",
    AssistProposal.objects.filter(status="pending").count(),
)
for p in AssistProposal.objects.order_by("-id")[:15]:
    print("---")
    print("id", p.pk, "status", p.status, "kind", p.kind)
    print("parse_error", (p.parse_error or "")[:200])
    print("rationale", (p.rationale or "")[:200])
    print("task_id", p.task_id)
    print("job_id", p.job_id)
    ctx = p.context if isinstance(p.context, dict) else {}
    print("context_keys", list(ctx.keys())[:20])
    text = str(ctx.get("text") or ctx.get("notes") or "")[:160]
    print("context_text", text)
    print("proposal", json.dumps(p.proposal, default=str)[:400])
print("jobs recent")
for j in AssistJob.objects.order_by("-id")[:12]:
    print(
        j.pk,
        j.status,
        j.kind,
        "task",
        j.task_id,
        "err",
        (j.error or "")[:120],
    )
