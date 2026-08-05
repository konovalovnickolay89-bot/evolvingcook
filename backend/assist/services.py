"""
Assist services — NOTE→ASSIST v2 (Phase 5 / D12+D14).

Webhook → proposal/job status only.
Accept handlers write domain by declared target: line | template | item.
B15 recipe explosion lives here as catalog-facing helper.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from catalog.models import Item, ItemComponent

logger = logging.getLogger(__name__)

NOTE_MAX = 500
EXPLODE_DEPTH_CAP = 6
PARSE_NOTE_MIN_CHARS = int(getattr(settings, "ASSIST_NOTE_MIN_CHARS", 15) or 15)
DEDUPE_SECONDS = int(getattr(settings, "ASSIST_NOTE_DEDUPE_SECONDS", 3600) or 3600)
RATE_PER_LINE_HOUR = int(getattr(settings, "ASSIST_NOTE_RATE_PER_LINE_HOUR", 12) or 12)

TERMINAL_FAIL = frozenset(
    {
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_REJECTED",
    }
)
TERMINAL_OK = "TASK_STATE_COMPLETED"
VALID_TARGETS = frozenset({"line", "template", "item"})
VALID_CONFIDENCE = frozenset({"high", "medium", "low"})


class AssistError(Exception):
    def __init__(self, message: str, code: str = "assist_error"):
        super().__init__(message)
        self.code = code


class RecipeCycleError(AssistError):
    """B15 — raise on cycle; wrong qty worse than crash."""

    def __init__(self, message: str):
        super().__init__(message, code="recipe_cycle")


class RecipeDepthError(AssistError):
    def __init__(self, message: str):
        super().__init__(message, code="recipe_depth")


def _norm_name(value: str) -> str:
    return " ".join((value or "").strip().split())


def _clip_note(value: str | None) -> str:
    s = (value or "").strip()
    if len(s) > NOTE_MAX:
        return s[:NOTE_MAX]
    return s


def _to_decimal(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def effective_parse_text(context: dict | None) -> str:
    """notes is an alias of text (FE intake)."""
    if not isinstance(context, dict):
        return ""
    for key in ("text", "notes", "note"):
        v = context.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if v is not None and not isinstance(v, str) and str(v).strip():
            return str(v).strip()
    return ""


def normalize_parse_note_context(context: dict) -> dict[str, Any]:
    """
    Normalize parse_note context for enqueue + prompt.
    Accepts notes as alias of text. Enriches line/item names from DB.
    Raises AssistError(bad_context) if effective text empty.
    """
    if not isinstance(context, dict):
        raise AssistError("context must be object", code="bad_context")

    text = effective_parse_text(context)
    if not text:
        raise AssistError(
            "parse_note requires non-empty text (or notes alias)",
            code="empty_text",
        )

    out: dict[str, Any] = {
        "text": text,
        "text_hash": _text_hash(text),
    }

    line_id = context.get("line_id")
    item_id = context.get("item_id")
    section = context.get("section")
    service_date = context.get("service_date")

    if line_id is not None and line_id != "":
        try:
            out["line_id"] = int(line_id)
        except (TypeError, ValueError) as exc:
            raise AssistError("line_id must be int", code="bad_context") from exc

    if item_id is not None and item_id != "":
        try:
            out["item_id"] = int(item_id)
        except (TypeError, ValueError) as exc:
            raise AssistError("item_id must be int", code="bad_context") from exc

    if isinstance(section, str) and section.strip():
        out["section"] = section.strip()
    if service_date is not None and str(service_date).strip():
        out["service_date"] = str(service_date).strip()

    # Enrich from DB
    if out.get("line_id") is not None:
        from planning.models import ProductionLine

        try:
            # No select_for_update here — avoid nullable outer-join FOR UPDATE
            line = (
                ProductionLine.objects.select_related(
                    "item", "template", "service_section", "service_section__service_day"
                )
                .get(pk=out["line_id"])
            )
        except ProductionLine.DoesNotExist as exc:
            raise AssistError(
                f"line_id {out['line_id']} not found", code="line_not_found"
            ) from exc
        out["line_name"] = line.name
        out["section"] = out.get("section") or line.service_section.section
        out["service_date"] = out.get("service_date") or str(
            line.service_section.service_day.service_date
        )
        if line.template_id:
            out["template_id"] = line.template_id
            out["template_name"] = line.template.name if line.template_id else None
        if line.item_id and out.get("item_id") is None:
            out["item_id"] = line.item_id
            out["item_name"] = line.item.name if line.item_id else None
        elif line.item_id and out.get("item_id") == line.item_id:
            out["item_name"] = line.item.name if line.item else out.get("item_name")

    if out.get("item_id") is not None and not out.get("item_name"):
        try:
            item = Item.objects.get(pk=out["item_id"])
            out["item_name"] = item.name
        except Item.DoesNotExist as exc:
            raise AssistError(
                f"item_id {out['item_id']} not found", code="item_not_found"
            ) from exc

    # Optional passthrough names if provided without ids
    for k in ("line_name", "item_name", "template_name"):
        if k not in out and context.get(k):
            out[k] = str(context[k])[:255]

    return out


def _extract_agent_text(status_block: dict) -> str:
    msg = status_block.get("message") or {}
    parts = msg.get("parts") or []
    chunks: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("text"):
            chunks.append(str(p["text"]))
        elif isinstance(p, str):
            chunks.append(p)
    if chunks:
        return "\n".join(chunks).strip()
    for key in ("text", "message"):
        if isinstance(status_block.get(key), str):
            return status_block[key].strip()
    return ""


def _strip_json_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def parse_proposal_json(text: str) -> tuple[dict, str]:
    """
    Parse agent text as strict JSON object.
    Returns (proposal_dict, parse_error). parse_error empty on success.
    """
    raw = _strip_json_fences(text)
    if not raw:
        return {}, "empty agent text"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not m:
            return {}, f"json_decode: {exc}"
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc2:
            return {}, f"json_decode: {exc2}"
    if not isinstance(data, dict):
        return {}, "proposal root must be object"
    return data, ""


# Hermes platform notices that are not parse_note JSON (e.g. auto-TTS on A2A).
_TRANSPORT_ERROR_MARKERS = (
    "couldn't deliver the audio attachment",
    "couldn't deliver the file attachment",
    "couldn't deliver the video attachment",
)


def is_agent_transport_error(text: str | None) -> bool:
    """
    True when agent text is empty or a Hermes delivery/system notice —
    not a model proposal. Must not create Proposals inbox cards.
    """
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    if any(m in low for m in _TRANSPORT_ERROR_MARKERS):
        return True
    # Generic warning-only payloads with no JSON object
    if t.startswith("⚠️") and "{" not in t:
        return True
    return False

def proposal_has_structure(body: dict | None) -> bool:
    """True when proposal has accept-worthy structured content."""
    if not isinstance(body, dict) or not body:
        return False
    target = str(body.get("target") or "").strip().lower()
    if target == "prep_step":
        return bool(str(body.get("title") or "").strip()) and bool(
            str(body.get("working") or "").strip()
        )
    if target == "component_fill":
        comps = body.get("components")
        return isinstance(comps, list) and len(comps) > 0
    if target == "order_packs":
        lines = body.get("lines") or body.get("order_lines")
        return bool(lines) or bool(body.get("item_id") or body.get("supplier_item_id"))
    if target == "new_line":
        return bool(str(body.get("name") or body.get("line_name") or "").strip())
    if target == "planned_qty":
        return True
    note = body.get("note")
    if isinstance(note, str) and note.strip():
        return True
    if body.get("house_made") is not None:
        return True
    comps = body.get("components")
    if isinstance(comps, list) and len(comps) > 0:
        return True
    # target alone is not structure
    return False


def _audit_list(body: dict) -> list[dict[str, Any]]:
    """Return a clean list for proposal.audit (never stuffed into rationale)."""
    raw = body.get("audit")
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict) and item.get("code"):
                out.append(
                    {
                        "code": str(item.get("code"))[:64],
                        "detail": str(item.get("detail") or "")[:500],
                    }
                )
            elif isinstance(item, str) and item.strip():
                out.append({"code": "note", "detail": item.strip()[:500]})
        return out
    if isinstance(raw, dict) and raw.get("code"):
        return [
            {
                "code": str(raw.get("code"))[:64],
                "detail": str(raw.get("detail") or "")[:500],
            }
        ]
    return []


def _append_audit(body: dict, code: str, detail: str) -> None:
    events = _audit_list(body)
    code_s = (code or "").strip()[:64]
    detail_s = (detail or "").strip()[:500]
    if not code_s:
        return
    # de-dupe identical code+detail
    for ev in events:
        if ev.get("code") == code_s and ev.get("detail") == detail_s:
            body["audit"] = events
            return
    events.append({"code": code_s, "detail": detail_s})
    body["audit"] = events


def normalize_proposal_targets(body: dict) -> dict:
    """
    Ensure target + target_confidence present with safe defaults.

    System coercion notes go to proposal.audit (list of {code, detail}).
    Human/model rationale stays free of pipeline string-splits (BE-2).
    """
    b = dict(body)
    # Preserve any existing audit; never read pipeline crumbs from rationale.
    b["audit"] = _audit_list(b)

    target = str(b.get("target") or "").strip().lower()
    if target not in VALID_TARGETS:
        # Prefer reversible default
        target = "line"
        if b.get("house_made") is not None or (b.get("components") or []):
            target = "item"
        b["target"] = target
        if not b.get("target_confidence"):
            b["target_confidence"] = "low"
        _append_audit(
            b,
            "defaulted_target",
            "missing/invalid target; preferred reversible tier",
        )
    conf = str(b.get("target_confidence") or "").strip().lower()
    if conf not in VALID_CONFIDENCE:
        b["target_confidence"] = "medium"
        if conf:
            _append_audit(
                b,
                "defaulted_confidence",
                f"invalid target_confidence={conf!r}; set medium",
            )
    else:
        b["target_confidence"] = conf
    # house_made / components never on template tier — coerce up with low conf
    if b.get("target") == "template" and (
        b.get("house_made") is not None or (b.get("components") or [])
    ):
        b["target"] = "item"
        b["target_confidence"] = "low"
        _append_audit(
            b,
            "coerced_template_to_item",
            "house_made/components are item-tier only",
        )
    # Keep rationale as model/user text only (string or empty)
    if b.get("rationale") is not None and not isinstance(b.get("rationale"), str):
        b["rationale"] = str(b.get("rationale"))[:2000]
    return b


def get_task_text(task_id: str) -> str:
    """A2A GetTask recovery — returns agent text or empty. Never raises."""
    base = (settings.A2A_BASE_URL or "").rstrip("/")
    token = settings.A2A_TOKEN or ""
    if not base or not task_id:
        return ""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "GetTask",
        "params": {"id": task_id},
    }
    # also try tasks/get style
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(
            base + "/", data=data, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            rpc = json.loads(resp.read().decode() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("GetTask failed for %s: %s", task_id, exc)
        return ""
    if not isinstance(rpc, dict) or rpc.get("error"):
        # try alternate method name
        body["method"] = "tasks/get"
        body["params"] = {"taskId": task_id}
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                base + "/", data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                rpc = json.loads(resp.read().decode() or "{}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("tasks/get failed for %s: %s", task_id, exc)
            return ""
    result = rpc.get("result") if isinstance(rpc, dict) else None
    if not isinstance(result, dict):
        return ""
    # Task shape: status.message.parts
    status = result.get("status") or {}
    if isinstance(status, dict):
        t = _extract_agent_text(status)
        if t:
            return t
    # artifacts
    for art in result.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        for p in art.get("parts") or []:
            if isinstance(p, dict) and p.get("text"):
                return str(p["text"]).strip()
    # history last agent message
    for msg in reversed(result.get("history") or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        if "AGENT" in role.upper() or role.lower() == "agent":
            parts = msg.get("parts") or []
            chunks = []
            for p in parts:
                if isinstance(p, dict) and p.get("text"):
                    chunks.append(str(p["text"]))
            if chunks:
                return "\n".join(chunks).strip()
    return ""


@transaction.atomic
def handle_agent_event(payload: dict) -> dict[str, Any]:
    """
    Process verified A2A statusUpdate push.
    Never writes domain (notes/items/stock). Proposal/job only.

    Outcomes:
    - structure found → proposal pending
    - nothing structured → job succeeded, NO proposal
    - parse failure (after GetTask) → proposal with parse_error (not accept-able)
    """
    su = payload.get("statusUpdate") or payload.get("status_update") or {}
    if not isinstance(su, dict):
        raise AssistError("missing statusUpdate", code="bad_payload")

    task_id = str(su.get("taskId") or su.get("task_id") or "").strip()
    context_id = str(su.get("contextId") or su.get("context_id") or "").strip()
    status_block = su.get("status") or {}
    state = str(status_block.get("state") or "").strip()
    if not task_id:
        raise AssistError("taskId required", code="bad_payload")
    if not state:
        raise AssistError("status.state required", code="bad_payload")

    job = None
    if context_id.isdigit():
        job = AssistJob.objects.select_for_update().filter(pk=int(context_id)).first()
    if job is None:
        job = AssistJob.objects.select_for_update().filter(task_id=task_id).first()

    if state in TERMINAL_FAIL:
        reason = _extract_agent_text(status_block) or state
        if job is not None:
            if job.status != AssistJob.Status.SUCCEEDED:
                job.status = AssistJob.Status.FAILED
                job.error = (reason or "")[:2000]
                if not job.task_id:
                    job.task_id = task_id
                job.save(update_fields=["status", "error", "task_id", "updated_at"])
        return {
            "ok": True,
            "action": "job_failed",
            "task_id": task_id,
            "job_id": job.pk if job else None,
        }

    if state != TERMINAL_OK:
        return {
            "ok": True,
            "action": "ignored_state",
            "state": state,
            "task_id": task_id,
        }

    agent_text = _extract_agent_text(status_block)
    proposal_body, parse_err = parse_proposal_json(agent_text)

    # GetTask recovery when push body fails JSON
    if parse_err:
        recovered = get_task_text(task_id)
        if recovered and recovered != agent_text:
            proposal_body, parse_err2 = parse_proposal_json(recovered)
            if not parse_err2:
                agent_text = recovered
                parse_err = ""
            else:
                parse_err = f"{parse_err}; gettask: {parse_err2}"
                # Prefer recovered text for transport classification
                if is_agent_transport_error(recovered):
                    agent_text = recovered

    kind = AssistJob.Kind.PARSE_NOTE
    context: dict = {}
    if job is not None:
        kind = job.kind
        context = job.context if isinstance(job.context, dict) else {}
        if not job.task_id:
            job.task_id = task_id

    # Existing decided proposal: never clobber
    existing = (
        AssistProposal.objects.select_for_update().filter(task_id=task_id).first()
    )
    if existing is not None and existing.status != AssistProposal.Status.PENDING:
        if job is not None and job.status == AssistJob.Status.RUNNING:
            job.status = AssistJob.Status.SUCCEEDED
            job.error = ""
            job.save(update_fields=["status", "task_id", "error", "updated_at"])
        return {
            "ok": True,
            "action": "noop_decided",
            "proposal_id": existing.pk,
            "task_id": task_id,
        }

    # Transport / Hermes system notices (auto-TTS audio fail, empty body) →
    # fail job, no inbox poison. B1 kitchen policy.
    if parse_err and is_agent_transport_error(agent_text):
        err_msg = (parse_err + ": " + (agent_text or "")[:400]).strip(": ")[:2000]
        if job is not None:
            job.status = AssistJob.Status.FAILED
            job.error = err_msg or "agent_transport_error"
            job.save(update_fields=["status", "task_id", "error", "updated_at"])
        if existing is not None and existing.status == AssistProposal.Status.PENDING:
            existing.status = AssistProposal.Status.REJECTED
            existing.decided_at = timezone.now()
            existing.reject_reason = "auto: agent transport/system error (not JSON)"
            existing.parse_error = parse_err
            existing.save(
                update_fields=[
                    "status",
                    "decided_at",
                    "reject_reason",
                    "parse_error",
                    "updated_at",
                ]
            )
        logger.warning(
            "assist transport error task=%s job=%s err=%s",
            task_id,
            job.pk if job else None,
            err_msg[:200],
        )
        return {
            "ok": True,
            "action": "agent_transport_error",
            "task_id": task_id,
            "job_id": job.pk if job else None,
            "parse_error": parse_err,
        }

    # Success path for job when we have real agent content (JSON ok or rare parse mess)
    if job is not None:
        if not parse_err:
            if job.status != AssistJob.Status.FAILED:
                job.status = AssistJob.Status.SUCCEEDED
            job.error = ""
        else:
            # Non-transport parse failure — job failed; may still inbox below
            job.status = AssistJob.Status.FAILED
            job.error = (parse_err or "parse_error")[:2000]
        job.save(update_fields=["status", "task_id", "error", "updated_at"])

    # Nothing structured + valid JSON empty → silence (no proposal)
    if not parse_err and not proposal_has_structure(proposal_body):
        if existing is not None and existing.status == AssistProposal.Status.PENDING:
            # refresh to empty structured → delete? keep as parse noise — drop pending empty
            existing.delete()
        return {
            "ok": True,
            "action": "no_structure",
            "task_id": task_id,
            "job_id": job.pk if job else None,
        }

    if not parse_err and proposal_has_structure(proposal_body):
        proposal_body = normalize_proposal_targets(proposal_body)
        # B3 stamp
        try:
            from planning.section_modes import PROMPT_VERSION

            if isinstance(proposal_body, dict):
                proposal_body.setdefault("prompt_version", PROMPT_VERSION)
        except Exception:  # noqa: BLE001
            if isinstance(proposal_body, dict):
                proposal_body.setdefault("prompt_version", "section-modes-v1")

    rationale = ""
    if isinstance(proposal_body, dict):
        rationale = str(proposal_body.get("rationale") or "")[:2000]

    if existing is not None:
        existing.proposal = proposal_body
        existing.rationale = rationale or existing.rationale
        existing.parse_error = parse_err
        if job is not None and existing.job_id is None:
            existing.job = job
        if not existing.kind:
            existing.kind = kind
        if not existing.context and context:
            existing.context = context
        existing.save()
        return {
            "ok": True,
            "action": "refreshed",
            "proposal_id": existing.pk,
            "task_id": task_id,
            "parse_error": parse_err or None,
        }

    # Rare non-transport parse failure → proposal inbox-only (not accept-able)
    # Valid structured → pending accept-worthy
    prop = AssistProposal.objects.create(
        kind=kind,
        context=context,
        proposal=proposal_body if isinstance(proposal_body, dict) else {},
        rationale=rationale,
        model="",
        status=AssistProposal.Status.PENDING,
        task_id=task_id,
        job=job,
        parse_error=parse_err,
    )
    return {
        "ok": True,
        "action": "created",
        "proposal_id": prop.pk,
        "task_id": task_id,
        "parse_error": parse_err or None,
    }

def build_parse_note_prompt(context: dict) -> str:
    """Compact agent task body — strict JSON only, fit ~2k push."""
    # Ensure normalized
    try:
        ctx = normalize_parse_note_context(context)
    except AssistError:
        ctx = dict(context or {})
        t = effective_parse_text(ctx)
        if t:
            ctx["text"] = t

    compact = {
        k: ctx.get(k)
        for k in (
            "text",
            "line_id",
            "line_name",
            "item_id",
            "item_name",
            "template_id",
            "template_name",
            "service_date",
            "section",
        )
        if ctx.get(k) is not None and ctx.get(k) != ""
    }
    # B3: catalogue candidates — never invent item names
    candidates: list[dict] = []
    try:
        from planning.prep_plan import catalogue_candidates_for_section
        from planning.section_modes import PROMPT_VERSION

        sec = compact.get("section")
        if sec:
            candidates = catalogue_candidates_for_section(str(sec), limit=40)
        else:
            candidates = catalogue_candidates_for_section("a_la_carte", limit=40)
        prompt_version = PROMPT_VERSION
    except Exception:  # noqa: BLE001
        prompt_version = "section-modes-v1"
        candidates = []

    return (
        "TASK kind=parse_note\n"
        f"prompt_version={prompt_version}\n"
        "Return STRICT JSON only. No markdown fences. No prose. No TTS.\n"
        "Schema:{"
        '"note":string|null,'
        '"target":"line"|"template"|"item",'
        '"target_confidence":"high"|"medium"|"low",'
        '"house_made":bool|null,'
        '"components":[{"name":string,"item_id":int|null,"qty":number|null,'
        '"unit":string|null,"notes":string|null,"sort_order":int|null}],'
        '"rationale":string|null,"confidence":number|null,'
        '"prompt_version":string}\n'
        "Tiers: line=today only (ProductionLine); "
        "template=dish template note every future day (NOT house_made/components); "
        "item=catalogue Item permanent (house_made + components live ONLY here).\n"
        "Inference: recurring (always/every day/check daily)→template; "
        "identity (is house made/we buy/supplier)→item; "
        "time-bounded (today/this week/ran out) or unsure→line.\n"
        "When unsure between item and line, prefer line (reversible). "
        "If target_confidence is low, set it and explain why in rationale one line.\n"
        "If nothing structured to propose, return "
        '{"note":null,"target":"line","target_confidence":"high","components":[],'
        '"rationale":"no structure"}.\n'
        "Rules: note max 500; qty JSON numbers; never self-parent; keep compact.\n"
        "ONLY use component/item names from candidates (or exact note text). "
        "Never invent catalogue codes.\n"
        f"candidates={json.dumps(candidates, ensure_ascii=False, separators=(',', ':'))}\n"
        f"context={json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}"
    )


def find_recent_parse_note_dedupe(context: dict) -> AssistJob | None:
    """
    BE-3 / D14: identical text_hash (+ line_id when present) within DEDUPE_SECONDS.
    Excludes FAILED so a failed attempt can be retried.
    """
    if not isinstance(context, dict):
        return None
    th = context.get("text_hash") or (
        _text_hash(context["text"]) if context.get("text") else None
    )
    if not th:
        return None
    since = timezone.now() - timedelta(seconds=DEDUPE_SECONDS)
    qs = (
        AssistJob.objects.filter(
            kind=AssistJob.Kind.PARSE_NOTE,
            created_at__gte=since,
        )
        .filter(context__text_hash=th)
        .exclude(status=AssistJob.Status.FAILED)
        .order_by("-id")
    )
    line_id = context.get("line_id")
    if line_id is not None and line_id != "":
        try:
            qs = qs.filter(context__line_id=int(line_id))
        except (TypeError, ValueError):
            pass
    return qs.first()


def enqueue_assist_job(kind: str, context: dict) -> AssistJob:
    """
    Create AssistJob and enqueue django-q2 SendMessage worker.

    parse_note: normalize context; text_hash dedupe returns existing non-failed
    job in-window (defense-in-depth for any client that still posts /jobs).
    D15: mode gates by section on context.
    """
    from django_q.tasks import async_task

    if kind not in {c.value for c in AssistJob.Kind}:
        raise AssistError(f"unsupported kind: {kind}", code="bad_kind")
    if not isinstance(context, dict):
        raise AssistError("context must be object", code="bad_context")

    if kind == AssistJob.Kind.PARSE_NOTE or kind == "parse_note":
        context = normalize_parse_note_context(context)

    # D15 mode gate
    section = None
    if isinstance(context, dict):
        section = context.get("section")
        if section is None and context.get("line_id") is not None:
            # section may have been enriched on parse_note context
            section = context.get("section")
    try:
        from planning.section_modes import SectionModeError, assert_job_allowed

        assert_job_allowed(kind=kind, section=section if section else None)
    except SectionModeError as exc:
        raise AssistError(str(exc), code=exc.code) from exc

    # menu_completeness / order_suggest: deterministic scaffold (no A2A)
    if kind in (AssistJob.Kind.MENU_COMPLETENESS, "menu_completeness"):
        from datetime import date as date_cls
        from planning.ordering_assist import ensure_menu_completeness_proposals

        sd_raw = (context or {}).get("service_date")
        sec = (context or {}).get("section")
        if not sec or not sd_raw:
            raise AssistError(
                "menu_completeness requires context.section and context.service_date",
                code="bad_context",
            )
        sd = sd_raw if hasattr(sd_raw, "isoformat") else date_cls.fromisoformat(str(sd_raw)[:10])
        ensure_menu_completeness_proposals(service_date=sd, section=str(sec))
        return AssistJob.objects.create(
            kind=kind, context=context, status=AssistJob.Status.SUCCEEDED
        )

    if kind in (AssistJob.Kind.ORDER_SUGGEST, "order_suggest"):
        from datetime import date as date_cls
        from planning.ordering_assist import ensure_order_suggest_from_board

        sd_raw = (context or {}).get("service_date")
        sec = (context or {}).get("section")
        if not sec or not sd_raw:
            raise AssistError(
                "order_suggest requires context.section and context.service_date",
                code="bad_context",
            )
        sd = sd_raw if hasattr(sd_raw, "isoformat") else date_cls.fromisoformat(str(sd_raw)[:10])
        ensure_order_suggest_from_board(service_date=sd, section=str(sec))
        return AssistJob.objects.create(
            kind=kind, context=context, status=AssistJob.Status.SUCCEEDED
        )

    # prep_plan: deterministic scaffold proposals (no A2A required for v1)
    if kind in (AssistJob.Kind.PREP_PLAN, "prep_plan"):
        from datetime import date as date_cls

        from planning.prep_plan import ensure_prep_plan_proposals

        sd_raw = (context or {}).get("service_date")
        sec = (context or {}).get("section")
        if not sec or not sd_raw:
            raise AssistError(
                "prep_plan requires context.section and context.service_date",
                code="bad_context",
            )
        try:
            if hasattr(sd_raw, "isoformat"):
                sd = sd_raw
            else:
                sd = date_cls.fromisoformat(str(sd_raw)[:10])
        except ValueError as exc:
            raise AssistError("bad service_date", code="bad_context") from exc
        ensure_prep_plan_proposals(service_date=sd, section=str(sec))
        job = AssistJob.objects.create(
            kind=kind,
            context=context,
            status=AssistJob.Status.SUCCEEDED,
        )
        return job

    if kind == AssistJob.Kind.PARSE_NOTE or kind == "parse_note":
        dup = find_recent_parse_note_dedupe(context)
        if dup is not None:
            logger.info(
                "parse_note enqueue dedupe hit job=%s hash=%s line_id=%s",
                dup.pk,
                context.get("text_hash"),
                context.get("line_id"),
            )
            return dup

    # qty_draft / morning_qty blocked already by mode gate for ordering/unset
    job = AssistJob.objects.create(
        kind=kind,
        context=context,
        status=AssistJob.Status.QUEUED,
    )
    try:
        qid = async_task("assist.a2a_client.run_assist_job", job.pk)
        job.q_task_id = str(qid or "")
        job.save(update_fields=["q_task_id", "updated_at"])
    except Exception as exc:  # noqa: BLE001
        # Note-save must not fail if queue is down — job stays queued for later
        logger.warning("enqueue async_task failed job=%s: %s", job.pk, exc)
        job.error = f"queue_enqueue_failed: {exc}"[:2000]
        job.save(update_fields=["error", "updated_at"])
    return job


def maybe_auto_enqueue_parse_note_for_line(
    line, *, text: str
) -> AssistJob | None:
    """
    After note-save: auto-enqueue parse_note when text long enough.
    Dedupe identical text per line (via enqueue_assist_job); rate-limit.
    Never raises to caller for queue issues. Returns job or None (skipped).
    """
    cleaned = (text or "").strip()
    if len(cleaned) < PARSE_NOTE_MIN_CHARS:
        return None

    line_id = getattr(line, "pk", None) or getattr(line, "id", None)
    if line_id is None:
        return None

    # Rate limit per line (dedupe is inside enqueue_assist_job)
    hour_ago = timezone.now() - timedelta(hours=1)
    n_hour = AssistJob.objects.filter(
        kind=AssistJob.Kind.PARSE_NOTE,
        created_at__gte=hour_ago,
        context__line_id=int(line_id),
    ).count()
    if n_hour >= RATE_PER_LINE_HOUR:
        logger.warning("parse_note rate limit line=%s n=%s", line_id, n_hour)
        return None

    ctx = {
        "text": cleaned,
        "line_id": int(line_id),
    }
    try:
        # Pre-check so auto path returns None on dedupe (enqueue still protects).
        norm = normalize_parse_note_context(ctx)
        if find_recent_parse_note_dedupe(norm) is not None:
            logger.info(
                "parse_note auto dedupe skip line=%s hash=%s",
                line_id,
                norm.get("text_hash"),
            )
            return None
        return enqueue_assist_job("parse_note", norm)
    except AssistError as exc:
        logger.warning("auto enqueue assist error: %s", exc)
        return None


def pending_proposals_for_line_ids(line_ids: list[int]) -> dict[int, dict]:
    """Map line_id → latest pending proposal summary (for board payload)."""
    if not line_ids:
        return {}
    qs = (
        AssistProposal.objects.filter(status=AssistProposal.Status.PENDING)
        .filter(kind=AssistJob.Kind.PARSE_NOTE)
        .order_by("-created_at", "-id")
    )
    out: dict[int, dict] = {}
    # Filter in Python for JSON line_id (portable)
    idset = {int(x) for x in line_ids}
    for p in qs[:500]:
        ctx = p.context if isinstance(p.context, dict) else {}
        lid = ctx.get("line_id")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        if lid_i is None or lid_i not in idset or lid_i in out:
            continue
        prop = p.proposal if isinstance(p.proposal, dict) else {}
        out[lid_i] = {
            "id": p.pk,
            "kind": p.kind,
            "status": p.status,
            "target": prop.get("target"),
            "target_confidence": prop.get("target_confidence"),
            "note": prop.get("note"),
            "house_made": prop.get("house_made"),
            "rationale": (p.rationale or prop.get("rationale") or "")[:300],
            "parse_error": (p.parse_error or "")[:300] or None,
            "accept_able": not bool(p.parse_error)
            and proposal_has_structure(prop)
            and not p.parse_error,
            "task_id": p.task_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
    return out


def proposal_out_dict(p: AssistProposal) -> dict:
    prop = p.proposal if isinstance(p.proposal, dict) else {}
    target = prop.get("target")
    if target is not None:
        target = str(target)
    conf = prop.get("target_confidence")
    if conf is not None:
        conf = str(conf)
    return {
        "id": p.pk,
        "kind": p.kind,
        "context": p.context if isinstance(p.context, dict) else {},
        "proposal": prop,
        # BE-4: top-level target fields (D14); FE no longer digs JSON heuristics
        "target": target,
        "target_confidence": conf,
        "rationale": p.rationale or "",
        "model": p.model or "",
        "status": p.status,
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
        "reject_reason": p.reject_reason or "",
        "task_id": p.task_id,
        "job_id": p.job_id,
        "parse_error": p.parse_error or "",
        "accept_able": (
            p.status == AssistProposal.Status.PENDING
            and not bool(p.parse_error)
            and proposal_has_structure(prop)
        ),
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


@transaction.atomic
def accept_assist_proposal(proposal_id: int) -> AssistProposal:
    """
    Accept proposal → domain writes for parse_note by declared target.
    Idempotent if already accepted. Rejects parse_error / no-structure rows.
    """
    proposal = AssistProposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.status == AssistProposal.Status.ACCEPTED:
        return proposal
    if proposal.status == AssistProposal.Status.REJECTED:
        raise AssistError("Cannot accept a rejected proposal", code="already_rejected")
    if proposal.parse_error:
        raise AssistError(
            "Cannot accept proposal with parse_error (inbox-only)",
            code="not_accept_able",
        )
    body = proposal.proposal if isinstance(proposal.proposal, dict) else {}
    if not proposal_has_structure(body):
        raise AssistError("Cannot accept empty/no-structure proposal", code="no_structure")

    if proposal.kind == AssistJob.Kind.PARSE_NOTE or proposal.kind == "parse_note":
        # Note tiers OR explicit v2 targets on parse_note body
        target = str(body.get("target") or "line").strip().lower()
        if target in {
            "planned_qty",
            "order_packs",
            "new_line",
            "component_fill",
        }:
            from assist.d15_targets import TargetApplyError, apply_d15_target

            try:
                apply_d15_target(proposal)
            except TargetApplyError as exc:
                raise AssistError(exc.message, code=exc.code) from exc
        elif target == "prep_step":
            _apply_prep_step(proposal)
        else:
            _apply_parse_note(proposal)
    elif proposal.kind == "prep_plan" or proposal.kind == AssistJob.Kind.PREP_PLAN:
        _apply_prep_step(proposal)
    elif proposal.kind in {
        "menu_completeness",
        "order_suggest",
        "qty_draft",
        "morning_qty",
        AssistJob.Kind.MENU_COMPLETENESS,
        AssistJob.Kind.ORDER_SUGGEST,
        AssistJob.Kind.QTY_DRAFT,
        AssistJob.Kind.MORNING_QTY,
    }:
        from assist.d15_targets import TargetApplyError, apply_d15_target

        try:
            apply_d15_target(proposal)
        except TargetApplyError as exc:
            raise AssistError(exc.message, code=exc.code) from exc
    else:
        # Fallback: body.target drives D15 handlers
        target = str(body.get("target") or "").strip().lower()
        if target in {
            "planned_qty",
            "order_packs",
            "new_line",
            "component_fill",
            "prep_step",
        }:
            if target == "prep_step":
                _apply_prep_step(proposal)
            else:
                from assist.d15_targets import TargetApplyError, apply_d15_target

                try:
                    apply_d15_target(proposal)
                except TargetApplyError as exc:
                    raise AssistError(exc.message, code=exc.code) from exc
        else:
            raise AssistError(
                f"no accept handler for kind={proposal.kind}",
                code="unknown_kind",
            )

    proposal.status = AssistProposal.Status.ACCEPTED
    proposal.decided_at = timezone.now()
    proposal.reject_reason = ""
    proposal.save(
        update_fields=["status", "decided_at", "reject_reason", "updated_at"]
    )
    return proposal


@transaction.atomic
def reject_assist_proposal(proposal_id: int, reason: str = "") -> AssistProposal:
    """
    Reject proposal. BE-1: empty/whitespace reason defaults to "other"
    so learning signal never stores blank reject_reason.
    """
    reason_s = (reason or "").strip() or "other"
    proposal = AssistProposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.status == AssistProposal.Status.ACCEPTED:
        raise AssistError("Cannot reject an accepted proposal", code="already_accepted")
    if proposal.status == AssistProposal.Status.REJECTED:
        if reason_s != proposal.reject_reason:
            proposal.reject_reason = reason_s[:2000]
            proposal.save(update_fields=["reject_reason", "updated_at"])
        return proposal
    proposal.status = AssistProposal.Status.REJECTED
    proposal.decided_at = timezone.now()
    proposal.reject_reason = reason_s[:2000]
    proposal.save(
        update_fields=["status", "decided_at", "reject_reason", "updated_at"]
    )
    return proposal


def _apply_prep_step(proposal: AssistProposal) -> None:
    """
    Accept a guided prep_step: validate working; stamp accepted_at on proposal body;
    optionally sync line planned_qty when line_id + qty present.
    Domain snapshot is the accepted AssistProposal row itself (board reads it).
    """
    from planning.prep_plan import validate_prep_step_body
    from planning.section_modes import PROMPT_VERSION, assert_target_allowed

    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    body = dict(proposal.proposal) if isinstance(proposal.proposal, dict) else {}
    section = ctx.get("section") or body.get("section")
    try:
        assert_target_allowed(target="prep_step", section=section)
    except Exception as exc:  # noqa: BLE001
        from planning.section_modes import SectionModeError

        if isinstance(exc, SectionModeError):
            raise AssistError(exc.message, code=exc.code) from exc
        raise
    err = validate_prep_step_body(body)
    if err:
        raise AssistError(err, code="not_accept_able")
    body["target"] = "prep_step"
    body["prompt_version"] = body.get("prompt_version") or PROMPT_VERSION
    body["accepted_at"] = timezone.now().isoformat()
    proposal.proposal = body
    if not proposal.model:
        proposal.model = proposal.model or "scaffold"

    line_id = body.get("line_id") or ctx.get("line_id")
    qty = body.get("qty")
    if line_id is not None and qty is not None:
        from planning.models import ProductionLine

        try:
            line = ProductionLine.objects.select_for_update().get(pk=int(line_id))
        except (ProductionLine.DoesNotExist, TypeError, ValueError):
            line = None
        if line is not None and line.mode != ProductionLine.Mode.CHECK:
            d = _to_decimal(qty)
            if d is not None:
                line.planned_qty = d
                line.save(update_fields=["planned_qty", "updated_at"])

    proposal.save(update_fields=["proposal", "model", "updated_at"])


def _apply_parse_note(proposal: AssistProposal) -> None:
    """
    Write ONLY to declared target:
      line → ProductionLine.notes (today)
      template → DishTemplate.notes (reappears daily; never house_made/components)
      item → Item notes / house_made / ItemComponent
    """
    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    body = normalize_proposal_targets(
        proposal.proposal if isinstance(proposal.proposal, dict) else {}
    )
    # persist normalized target back
    proposal.proposal = body

    target = str(body.get("target") or "line").strip().lower()
    note = body.get("note")
    note_s = _clip_note(note) if note is not None else None
    house_made = body.get("house_made")
    components = body.get("components") or []

    if target == "line":
        if ctx.get("line_id") is None:
            raise AssistError("line target requires context.line_id", code="line_required")
        from planning.models import ProductionLine

        try:
            line = ProductionLine.objects.select_for_update().get(pk=int(ctx["line_id"]))
        except (ProductionLine.DoesNotExist, TypeError, ValueError) as exc:
            raise AssistError(
                f"line_id {ctx.get('line_id')} not found",
                code="line_not_found",
            ) from exc
        if note_s is not None:
            line.notes = note_s
            line.save(update_fields=["notes", "updated_at"])
        return

    if target == "template":
        from planning.models import DishTemplate, ProductionLine

        tmpl = None
        tid = ctx.get("template_id")
        if tid is not None:
            try:
                tmpl = DishTemplate.objects.select_for_update().get(pk=int(tid))
            except (DishTemplate.DoesNotExist, TypeError, ValueError):
                tmpl = None
        if tmpl is None and ctx.get("line_id") is not None:
            try:
                line = ProductionLine.objects.select_related("template").get(
                    pk=int(ctx["line_id"])
                )
                if line.template_id:
                    tmpl = DishTemplate.objects.select_for_update().get(pk=line.template_id)
            except Exception:
                tmpl = None
        if tmpl is None:
            # name + section fallback
            name = ctx.get("line_name") or ctx.get("template_name")
            section = ctx.get("section")
            if name and section:
                tmpl = (
                    DishTemplate.objects.select_for_update()
                    .filter(section=section, name__iexact=str(name))
                    .first()
                )
        if tmpl is None:
            raise AssistError(
                "template target could not resolve DishTemplate",
                code="template_not_found",
            )
        if note_s is not None:
            tmpl.notes = note_s
            tmpl.save(update_fields=["notes"])
        # house_made/components ignored on template (normalize already coerces)
        return

    if target == "item":
        item = None
        item_id = ctx.get("item_id")
        item_name = _norm_name(str(ctx.get("item_name") or ""))
        if item_id is not None:
            try:
                item = Item.objects.select_for_update().get(pk=int(item_id))
            except (Item.DoesNotExist, TypeError, ValueError) as exc:
                raise AssistError(
                    f"item_id {item_id} not found",
                    code="item_not_found",
                ) from exc
        elif item_name:
            item = Item.objects.select_for_update().filter(name__iexact=item_name).first()
            if item is None:
                item = Item.objects.create(
                    name=item_name,
                    base_unit=Item.BaseUnit.EA,
                    active=True,
                    notes="",
                )
                item = Item.objects.select_for_update().get(pk=item.pk)
        else:
            # try line.item
            if ctx.get("line_id") is not None:
                from planning.models import ProductionLine

                try:
                    line = ProductionLine.objects.select_related("item").get(
                        pk=int(ctx["line_id"])
                    )
                    if line.item_id:
                        item = Item.objects.select_for_update().get(pk=line.item_id)
                except Exception:
                    item = None
        if item is None:
            raise AssistError(
                "item target requires resolvable item_id/name",
                code="item_required",
            )
        fields: list[str] = []
        if note_s is not None:
            item.notes = note_s
            fields.append("notes")
        if house_made is not None:
            item.house_made = bool(house_made)
            fields.append("house_made")
        if fields:
            item.save(update_fields=fields)
        if components and isinstance(components, list):
            _upsert_components(item, components)
        return

    raise AssistError(f"unknown target {target}", code="bad_target")


def _upsert_components(parent: Item, components: list) -> None:
    """Upsert ItemComponent rows; never delete SupplierItem; skip self-parent."""
    for i, raw in enumerate(components):
        if not isinstance(raw, dict):
            continue
        comp_item = None
        cid = raw.get("item_id")
        cname = _norm_name(str(raw.get("name") or ""))
        if cid is not None:
            try:
                comp_item = Item.objects.get(pk=int(cid))
            except (Item.DoesNotExist, TypeError, ValueError):
                comp_item = None
        if comp_item is None and cname:
            comp_item, _ = Item.objects.get_or_create(
                name=cname,
                defaults={
                    "base_unit": Item.BaseUnit.EA,
                    "active": True,
                    "notes": "",
                },
            )
        if comp_item is None:
            continue
        if comp_item.pk == parent.pk:
            continue
        qty = _to_decimal(raw.get("qty"))
        unit = str(raw.get("unit") or comp_item.base_unit or "").strip()[:16]
        notes = _clip_note(raw.get("notes"))
        sort_order = raw.get("sort_order")
        try:
            sort_i = int(sort_order) if sort_order is not None else i
        except (TypeError, ValueError):
            sort_i = i
        link, created = ItemComponent.objects.get_or_create(
            parent=parent,
            component=comp_item,
            defaults={
                "qty": qty,
                "unit": unit,
                "notes": notes,
                "sort_order": sort_i,
            },
        )
        if not created:
            upd: list[str] = []
            if qty is not None and link.qty != qty:
                link.qty = qty
                upd.append("qty")
            if unit and link.unit != unit:
                link.unit = unit
                upd.append("unit")
            if notes and notes not in (link.notes or ""):
                link.notes = notes
                upd.append("notes")
            if link.sort_order != sort_i:
                link.sort_order = sort_i
                upd.append("sort_order")
            if upd:
                link.save(update_fields=upd)


# ---------------------------------------------------------------------------
# B15 recipe explosion
# ---------------------------------------------------------------------------


def explode_item(
    item_id: int,
    *,
    qty: Decimal | float | int | str | None = 1,
    depth_cap: int = EXPLODE_DEPTH_CAP,
) -> list[dict[str, Any]]:
    try:
        root = Item.objects.get(pk=int(item_id))
    except (Item.DoesNotExist, TypeError, ValueError) as exc:
        raise AssistError(f"item {item_id} not found", code="item_not_found") from exc

    root_qty = _to_decimal(qty)
    if root_qty is None:
        root_qty = Decimal("1")

    edges: dict[int, list[tuple[int, Decimal | None, str, str]]] = {}
    for link in ItemComponent.objects.all().only(
        "parent_id", "component_id", "qty", "unit", "notes"
    ):
        edges.setdefault(link.parent_id, []).append(
            (link.component_id, link.qty, link.unit or "", link.notes or "")
        )

    items = {
        i.pk: i
        for i in Item.objects.filter(
            pk__in={root.pk}
            | {c for kids in edges.values() for c, *_ in kids}
            | set(edges.keys())
        )
    }
    items[root.pk] = root

    leaves: list[dict[str, Any]] = []

    def walk(cur_id: int, scale: Decimal, path: list[int], depth: int) -> None:
        if depth > depth_cap:
            raise RecipeDepthError(
                f"recipe depth exceeded {depth_cap} at item_id={cur_id} path={path}"
            )
        if cur_id in path:
            cycle = path + [cur_id]
            raise RecipeCycleError(
                f"recipe cycle detected: {'→'.join(str(x) for x in cycle)}"
            )
        kids = edges.get(cur_id) or []
        if not kids:
            it = items.get(cur_id)
            leaves.append(
                {
                    "item_id": cur_id,
                    "name": it.name if it else str(cur_id),
                    "qty": scale,
                    "unit": (it.base_unit if it else "") or "",
                    "depth": depth,
                    "path": list(path) + [cur_id],
                    "leaf": True,
                }
            )
            return
        new_path = path + [cur_id]
        for comp_id, link_qty, unit, notes in kids:
            factor = link_qty if link_qty is not None else Decimal("1")
            child_scale = scale * factor
            if edges.get(comp_id):
                walk(comp_id, child_scale, new_path, depth + 1)
            else:
                if depth + 1 > depth_cap:
                    raise RecipeDepthError(
                        f"recipe depth exceeded {depth_cap} at item_id={comp_id}"
                    )
                it = items.get(comp_id)
                leaves.append(
                    {
                        "item_id": comp_id,
                        "name": it.name if it else str(comp_id),
                        "qty": child_scale,
                        "unit": unit or (it.base_unit if it else "") or "",
                        "depth": depth + 1,
                        "path": new_path + [comp_id],
                        "leaf": True,
                        "parent_id": cur_id,
                        "notes": notes,
                    }
                )

    walk(root.pk, root_qty, [], 0)
    return leaves


def explode_item_as_dict(item_id: int, qty: Any = 1) -> dict[str, Any]:
    rows = explode_item(item_id, qty=qty)
    return {
        "item_id": int(item_id),
        "qty": float(_to_decimal(qty) or Decimal("1")),
        "components": [
            {
                **{k: v for k, v in r.items() if k != "qty"},
                "qty": float(r["qty"]) if isinstance(r["qty"], Decimal) else r["qty"],
            }
            for r in rows
        ],
    }
