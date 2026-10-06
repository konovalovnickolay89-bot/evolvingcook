"""
Kitchen companion — context-aware chat + cached daily brief (D16).

Rides the D10 Mistral gateway (catalog.llm_provider); no SDK, no new env.
Context is READ-ONLY: today's boards, station logs and pending proposals.
The companion returns advice text only — it never writes domain state.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from django.utils import timezone

from assist.models import AssistProposal, CompanionBrief
from catalog import llm_provider
from planning.models import ProductionLine, ServiceDay, StationLogLine

MAX_MESSAGES = 12
MAX_CONTENT_CHARS = 2000
MAX_LOG_LINES = 10

SYSTEM_PROMPT = (
    "You are the kitchen companion inside Evolving Cook, a phone app used by "
    "one commis chef running stations at a London hotel kitchen (six sections: "
    "skybar, breakfast buffet, à la carte, banquet buffet, banqueting, canteen). "
    "You receive a JSON snapshot of the working day: section boards with done / "
    "open / 86 counts, open station-log items, and pending assist proposals.\n"
    "Ground every answer in that snapshot when it is relevant. Speak chef-speak: "
    "short, concrete, mise-en-place-first (longest lead time first, cold chain "
    "respected, clock times only for day-of steps). Show arithmetic when you "
    "scale anything. Flag food-safety risks plainly (HACCP: temps, use-by, "
    "allergens) but never invent house rules. You are advice only: you cannot "
    "change boards, orders or logs, so point at the action the chef should take "
    "in the app instead of claiming you did it. Keep replies under 180 words "
    "unless asked for a full recipe or plan."
)

BRIEF_PROMPT = (
    "From the day snapshot, write 3 to 5 tips for this chef's shift today. "
    "Each tip is one practical, specific action or reminder grounded in the "
    "snapshot (86'd dishes, open log items, pending proposals, day of week); "
    "if the snapshot is thin, give seasoned kitchen habits for that weekday "
    "instead. No fluff, no repetition of the obvious."
)


class CompanionError(RuntimeError):
    def __init__(self, detail: str, code: str = "llm_error"):
        super().__init__(detail)
        self.code = code


def llm_ready() -> bool:
    return llm_provider.api_key_present()


def build_day_context(service_date: date) -> dict[str, Any]:
    """Compact read-only snapshot of the day for prompt grounding."""
    ctx: dict[str, Any] = {
        "service_date": service_date.isoformat(),
        "weekday": service_date.strftime("%A"),
        "day_status": "not_open",
        "sections": [],
        "pending_proposals": AssistProposal.objects.filter(
            status=AssistProposal.Status.PENDING
        ).count(),
    }
    day = (
        ServiceDay.objects.filter(service_date=service_date)
        .prefetch_related("sections")
        .first()
    )
    if day is None:
        return ctx
    ctx["day_status"] = day.status

    for sec in day.sections.all():
        lines = list(
            ProductionLine.objects.filter(service_section=sec).only(
                "name", "status", "mode"
            )
        )
        eighty_six = [
            l.name for l in lines if l.status == ProductionLine.Status.EIGHTY_SIX
        ]
        done = sum(1 for l in lines if l.status == ProductionLine.Status.READY)
        open_log = [
            {"kind": row.kind, "text": row.text, "action": row.action}
            for row in StationLogLine.objects.filter(
                service_section=sec, status=StationLogLine.Status.OPEN
            ).order_by("kind", "id")[:MAX_LOG_LINES]
        ]
        ctx["sections"].append(
            {
                "section": sec.section,
                "active": sec.active,
                "covers": sec.covers,
                "lines_total": len(lines),
                "done": done,
                "open": max(0, len(lines) - done - len(eighty_six)),
                "eighty_six": eighty_six,
                "open_log": open_log,
            }
        )
    return ctx


def _require_key() -> None:
    if not llm_ready():
        raise CompanionError(
            f"Companion offline: env {llm_provider.API_KEY_ENV} is not set.",
            code="llm_unconfigured",
        )


def _call(system: str, user_text: str) -> tuple[dict[str, Any], str]:
    """One JSON-mode gateway call → (parsed object, model name)."""
    _require_key()
    model = llm_provider.get_model()
    try:
        raw = llm_provider.chat_completion_json(
            system=system, user_text=user_text, model=model, timeout=90.0
        )
    except Exception as exc:  # httpx/network/provider errors → one clear code
        raise CompanionError(f"Companion call failed: {exc}") from exc
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except ValueError as exc:
        raise CompanionError(f"Companion returned invalid JSON: {exc}") from exc
    return data, model


def companion_chat(
    messages: list[dict[str, str]], service_date: date
) -> dict[str, str]:
    """Context-grounded chat turn. Returns {"reply", "model"}."""
    _require_key()
    trimmed = [
        {
            "role": "assistant" if m.get("role") == "assistant" else "user",
            "content": str(m.get("content", ""))[:MAX_CONTENT_CHARS],
        }
        for m in messages[-MAX_MESSAGES:]
        if str(m.get("content", "")).strip()
    ]
    if not trimmed or trimmed[-1]["role"] != "user":
        raise CompanionError("Last message must be from the chef.", code="bad_request")

    user_text = json.dumps(
        {
            "day_snapshot": build_day_context(service_date),
            "conversation": trimmed,
            "respond_with": {"reply": "string — your answer to the last message"},
        },
        ensure_ascii=False,
    )
    data, model = _call(SYSTEM_PROMPT, user_text)
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise CompanionError("Companion returned an empty reply.")
    return {"reply": reply, "model": model}


def daily_brief(service_date: date, refresh: bool = False) -> dict[str, Any]:
    """Cached per-date tips. Regenerates only on refresh=true."""
    cached = CompanionBrief.objects.filter(service_date=service_date).first()
    if cached and not refresh:
        return _brief_out(cached)

    user_text = json.dumps(
        {
            "day_snapshot": build_day_context(service_date),
            "task": BRIEF_PROMPT,
            "respond_with": {"tips": [{"title": "string", "body": "string"}]},
        },
        ensure_ascii=False,
    )
    try:
        data, model = _call(SYSTEM_PROMPT, user_text)
    except CompanionError:
        if cached:  # stale beats silent when the provider hiccups on refresh
            return _brief_out(cached)
        raise
    tips = [
        {"title": str(t.get("title", "")).strip(), "body": str(t.get("body", "")).strip()}
        for t in (data.get("tips") or [])
        if isinstance(t, dict) and str(t.get("body", "")).strip()
    ][:5]
    if not tips:
        raise CompanionError("Companion returned no tips.")
    brief, _ = CompanionBrief.objects.update_or_create(
        service_date=service_date,
        defaults={"payload": {"tips": tips}, "model": model},
    )
    return _brief_out(brief)


def _brief_out(brief: CompanionBrief) -> dict[str, Any]:
    return {
        "service_date": brief.service_date.isoformat(),
        "generated_at": timezone.localtime(brief.updated_at).isoformat(),
        "model": brief.model,
        "tips": list((brief.payload or {}).get("tips", [])),
    }
