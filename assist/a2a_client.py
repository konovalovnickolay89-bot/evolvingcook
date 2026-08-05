"""
Outbound Hermes A2A client (D11).

django-q2 worker calls SendMessage with push URL; stores taskId on AssistJob.
No happy-path polling.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid
from typing import Any

from django.conf import settings
from django.db import transaction

from assist.models import AssistJob
from assist.services import AssistError, build_parse_note_prompt

logger = logging.getLogger(__name__)


def _send_message(text: str, context_id: str) -> dict[str, Any]:
    base = (settings.A2A_BASE_URL or "").rstrip("/")
    token = settings.A2A_TOKEN or ""
    if not base:
        raise AssistError("A2A_BASE_URL not configured", code="a2a_unconfigured")
    if not token:
        raise AssistError("A2A_TOKEN not configured", code="a2a_unconfigured")

    push_url = settings.A2A_PUSH_CALLBACK_URL
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "contextId": str(context_id),
                "parts": [{"text": text}],
            },
            "configuration": {
                "taskPushNotificationConfig": {
                    "url": push_url,
                }
            },
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + "/",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.A2A_SEND_TIMEOUT) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        raise AssistError(
            f"A2A SendMessage HTTP {e.code}: {err_body[:500]}",
            code="a2a_http",
        ) from e
    except urllib.error.URLError as e:
        raise AssistError(f"A2A unreachable: {e}", code="a2a_unreachable") from e


def _extract_task_id(rpc: dict) -> str:
    if not isinstance(rpc, dict):
        return ""
    if rpc.get("error"):
        err = rpc["error"]
        raise AssistError(
            f"A2A RPC error: {err}",
            code="a2a_rpc",
        )
    result = rpc.get("result") or {}
    if isinstance(result, dict):
        tid = result.get("taskId") or result.get("id") or ""
        # nested task
        task = result.get("task") or {}
        if not tid and isinstance(task, dict):
            tid = task.get("taskId") or task.get("id") or ""
        return str(tid or "").strip()
    return ""


def run_assist_job(job_id: int) -> str:
    """
    django-q2 entrypoint. Sends A2A task; stores task_id; returns task_id.
    Failures mark job failed without crashing the cluster.
    """
    try:
        job = AssistJob.objects.get(pk=job_id)
    except AssistJob.DoesNotExist:
        logger.error("assist job %s missing", job_id)
        return ""

    with transaction.atomic():
        job = AssistJob.objects.select_for_update().get(pk=job_id)
        job.status = AssistJob.Status.RUNNING
        job.error = ""
        job.save(update_fields=["status", "error", "updated_at"])

    try:
        if job.kind == AssistJob.Kind.PARSE_NOTE:
            text = build_parse_note_prompt(
                job.context if isinstance(job.context, dict) else {}
            )
        else:
            raise AssistError(f"unsupported kind {job.kind}", code="bad_kind")

        rpc = _send_message(text, context_id=str(job.pk))
        task_id = _extract_task_id(rpc)
        if not task_id:
            raise AssistError(
                f"A2A response missing taskId: {str(rpc)[:400]}",
                code="a2a_no_task_id",
            )

        with transaction.atomic():
            job = AssistJob.objects.select_for_update().get(pk=job_id)
            # Only set running→awaiting if not already terminal from fast push
            if job.status == AssistJob.Status.RUNNING:
                # stay running until push; task_id stored
                pass
            job.task_id = task_id
            job.save(update_fields=["task_id", "updated_at"])
        logger.info("assist job %s a2a task_id=%s", job_id, task_id)
        return task_id
    except Exception as exc:  # noqa: BLE001
        logger.exception("assist job %s failed: %s", job_id, exc)
        with transaction.atomic():
            job = AssistJob.objects.select_for_update().get(pk=job_id)
            if job.status not in {
                AssistJob.Status.SUCCEEDED,
            }:
                job.status = AssistJob.Status.FAILED
                job.error = str(exc)[:2000]
                job.save(update_fields=["status", "error", "updated_at"])
        return ""
