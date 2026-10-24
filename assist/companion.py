"""
Kitchen companion — context-aware chat + standing manual daily brief (D16).

Chat rides the D10 Mistral gateway (catalog.llm_provider); no SDK, no new env.
The daily brief does not. It shows only tips the chef added (typed, voice, or
banto) and keeps unresolved ones until they are cleared or resolved. A
dashboard poll never calls the model to fill an empty brief.

Chat context is READ-ONLY: today's boards, station logs and pending proposals.
The companion chat returns advice text only — it never writes domain state.
"""
from __future__ import annotations

import ast
import json
import os
import re
import uuid
from datetime import date
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from assist.models import AssistProposal, CompanionBrief, CompanionProfile
from catalog import llm_provider
from planning.models import DishTemplate, ProductionLine, ServiceDay, StationLogLine

MAX_MESSAGES = 12
MAX_CONTENT_CHARS = 2000
MAX_LOG_LINES = 10
MAX_PROFILE_CHARS = 4000
MAX_MENU_DISHES = 150  # per section
MAX_MENU_COMPONENTS = 20  # per dish
MAX_MENU_NOTE_CHARS = 200
# Leading tag the menu seeds write on template notes: "NEW · Oct 26 menu · …"
_MENU_TAG = re.compile(r"^(NEW|CHANGED) · (?:[^·]*menu(?: · |$))?")

SYSTEM_PROMPT = (
    "You are the kitchen companion inside Evolving Cook, a phone app used by "
    "one commis chef running stations at a London hotel kitchen (six sections: "
    "skybar, breakfast buffet, à la carte, banquet buffet, banqueting, canteen). "
    "You receive a JSON snapshot of the working day: section boards with done / "
    "open / 86 counts, open station-log items, pending assist proposals, and "
    "the live menu (menu: section → category → 'Dish — notes | component; "
    "component', notes carry price and kcal; menu_changes names the dishes "
    "added (new) or reworked (changed) at the latest menu change, every other "
    "dish was already on; off_menu lists dishes that came off).\n"
    "Answer menu questions from that menu: it is current and beats anything "
    "said earlier in the conversation. Never invent dishes, prices or "
    "components; when a dish lists none, say so.\n"
    "Ground every answer in that snapshot when it is relevant. Speak chef-speak: "
    "short, concrete, mise-en-place-first (longest lead time first, cold chain "
    "respected, clock times only for day-of steps). Show arithmetic when you "
    "scale anything. The chef is a commis building toward senior: when a tip "
    "rests on a technique, add one short line of the why, so every answer "
    "teaches as well as tells. Flag food-safety risks plainly (HACCP: temps, "
    "use-by, allergens) but never invent house rules. You are advice only: you cannot "
    "change boards, orders or logs, so point at the action the chef should take "
    "in the app instead of claiming you did it. A house_profile field may "
    "carry the chef's standing rules and preferences: treat them as "
    "authoritative for this kitchen unless they conflict with food safety. "
    "Keep replies under 180 words unless asked for a full recipe or plan."
)

REPLY_FORMAT = (
    "Write the reply for a phone screen. It is ONE plain-text string, never "
    "an object or a list. Open with a one-line answer. Then short sections: "
    "a '**Heading**' line, then '- ' bullets; lead a bullet with a short "
    "label where it helps (Mise:, Lead:, Scale:, HACCP:, Why:). Blank line "
    "between sections. No tables, no code blocks, no JSON inside the reply."
)

# Retired for the daily brief. The brief is manual and must not be filled
# from the day snapshot, menu tags, invoices, or proposal queues. Do not
# call this from daily_brief, from refresh=true, or from a dashboard poll.
BRIEF_PROMPT = (
    "From the day snapshot, write 3 to 5 tips for this chef's shift today. "
    "Each tip is one practical, specific action or reminder grounded in the "
    "snapshot (menu dishes, 86'd dishes, open log items, pending proposals, "
    "day of week); "
    "if the snapshot is thin, give seasoned kitchen habits for that weekday "
    "instead. No fluff, no repetition of the obvious."
)

# One standing row holds manual tips. service_date here is not a service
# day — unresolved tips are shown on every date until resolved or deleted.
# Per-date rows with mode=manual still contribute (carry-over); rows without
# mode=manual are old model caches and are never returned or regenerated.
STANDING_BRIEF_DATE = date(1970, 1, 1)
MANUAL_MODE = "manual"
TIP_SOURCES = frozenset({"typed", "voice", "banto"})
MAX_TIP_TITLE = 200
MAX_TIP_BODY = 4000


_UNWRAP_KEYS = {"reply", "answer", "text", "message", "content"}


def _label(key: Any) -> str:
    s = str(key).replace("_", " ").strip()
    return s[:1].upper() + s[1:]  # not .capitalize(): keep "HACCP"


def _as_text(value: Any, depth: int = 0) -> str:
    """Model output → readable chat text, whatever shape JSON mode returned.

    Strings pass through; lists become '- ' bullets; objects become
    '**Heading**' sections (container values) or '**Key:** value' lines.
    Never str() a container — that leaks Python reprs into the chat.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, (list, dict)):
        return str(value)
    if depth > 4:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict) and not any(
                isinstance(v, (list, dict)) for v in item.values()
            ):
                flat = " · ".join(
                    f"{_label(k)}: {_as_text(v)}"
                    for k, v in item.items()
                    if _as_text(v)
                )
                if flat:
                    lines.append(f"- {flat}")
                continue
            text = _as_text(item, depth + 1)
            if text:  # indent wrapped lines so they stay inside the bullet
                lines.append(
                    text
                    if isinstance(item, (list, dict))
                    else "- " + text.replace("\n", "\n  ")
                )
        return "\n".join(lines)
    if len(value) == 1:
        ((k, v),) = value.items()
        if str(k).lower() in _UNWRAP_KEYS:
            return _as_text(v, depth + 1)
    blocks = []
    for k, v in value.items():
        text = _as_text(v, depth + 1)
        if not text:
            continue
        if isinstance(v, (list, dict)):
            blocks.append(f"**{_label(k)}**\n{text}")
        else:
            blocks.append(f"**{_label(k)}:** {text}")
    return "\n\n".join(blocks)


def _repair_reply(content: str) -> str:
    """Replies stored before the _as_text fix can be Python reprs
    ("{'actions': [...]}"). Turn them back into text so the model stops
    copying that shape from the conversation."""
    s = (content or "").strip()
    if not s or s[0] not in "{[":
        return content
    for parse in (json.loads, ast.literal_eval):
        try:
            value = parse(s)
        except Exception:  # noqa: BLE001 — any parse failure keeps the original
            continue
        if isinstance(value, (list, dict)):
            return _as_text(value) or content
    return content


class CompanionError(RuntimeError):
    def __init__(self, detail: str, code: str = "llm_error"):
        super().__init__(detail)
        self.code = code


def llm_ready() -> bool:
    return llm_provider.api_key_present()


def get_profile() -> dict[str, Any]:
    row = CompanionProfile.objects.first()
    return {
        "text": row.text if row else "",
        "updated_at": (
            timezone.localtime(row.updated_at).isoformat() if row else None
        ),
    }


def set_profile(text: str) -> dict[str, Any]:
    """Save the house profile.

    The daily brief is a standing manual list. Saving the profile must not
    delete it: a missing brief used to be filled by the model on the next
    dashboard poll, and that path is closed.
    """
    clean = (text or "").strip()[:MAX_PROFILE_CHARS]
    row, created = CompanionProfile.objects.get_or_create(
        singleton=True, defaults={"text": clean}
    )
    if not created and row.text != clean:
        row.text = clean
        row.save(update_fields=["text", "updated_at"])
    return get_profile()


def get_companion_model() -> str:
    """COMPANION_MODEL env/setting, falling back to the D10 ingest model."""
    return (
        os.environ.get("COMPANION_MODEL")
        or getattr(settings, "COMPANION_MODEL", None)
        or llm_provider.get_model()
    )


def _menu_dish(t: DishTemplate) -> tuple[str, str]:
    """('Name — notes | component; component', "new" | "changed" | "")."""
    text = t.name
    note = " ".join(t.notes.split())
    change = ""
    tag = _MENU_TAG.match(note)
    if tag:  # → menu_changes; inline, the model read "Oct 26 menu" as 26 Oct
        change, note = tag.group(1).lower(), note[tag.end() :]
    if note:
        if len(note) > MAX_MENU_NOTE_CHARS:
            note = note[: MAX_MENU_NOTE_CHARS - 1].rstrip() + "…"
        text += f" — {note}"
    names = [
        (c.item.name if c.item_id else c.name).strip() for c in t.components.all()
    ]
    comps = list(dict.fromkeys(n for n in names if n))  # dedupe, keep order
    if comps:
        more = len(comps) - MAX_MENU_COMPONENTS
        text += " | " + "; ".join(comps[:MAX_MENU_COMPONENTS])
        if more > 0:
            text += f" (+{more} more)"
    return text, change


def build_menu_context() -> dict[str, Any]:
    """Live menu from dish templates → menu / menu_changes / off_menu.

    All keyed by section. Templates are the standing menu, so the companion
    knows a menu change even on a board opened before it. Categories that
    just repeat the section name read as "other".
    """
    menu: dict[str, Any] = {}
    changes: dict[str, dict[str, list[str]]] = {}
    shown: dict[str, int] = {}
    hidden: dict[str, int] = {}
    for t in DishTemplate.objects.filter(active=True).prefetch_related(
        "components__item"
    ):
        if shown.get(t.section, 0) >= MAX_MENU_DISHES:
            hidden[t.section] = hidden.get(t.section, 0) + 1
            continue
        shown[t.section] = shown.get(t.section, 0) + 1
        cat = t.category if t.category and t.category != t.section else "other"
        line, change = _menu_dish(t)
        menu.setdefault(t.section, {}).setdefault(cat, []).append(line)
        if change:
            changes.setdefault(t.section, {}).setdefault(change, []).append(t.name)
    for section, n in hidden.items():
        menu[section]["not_shown"] = [f"+{n} more dishes"]

    off_menu: dict[str, list[str]] = {}
    for section, name in DishTemplate.objects.filter(active=False).values_list(
        "section", "name"
    ):
        off_menu.setdefault(section, []).append(name)
    return {"menu": menu, "menu_changes": changes, "off_menu": off_menu}


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
        **build_menu_context(),
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
    """One JSON-mode gateway call → (parsed object, model name).

    JSON mode now and then leaves a quote unescaped in a long reply (seen
    live on a menu list); the same call made again is well-formed, so one
    retry beats a "companion offline" screen.
    """
    _require_key()
    model = get_companion_model()
    for attempt in (1, 2):
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
            return data, model
        except ValueError as exc:
            if attempt == 2:
                raise CompanionError(
                    f"Companion returned invalid JSON: {exc}"
                ) from exc
    raise AssertionError("unreachable")


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
    for m in trimmed:
        if m["role"] == "assistant":
            m["content"] = _repair_reply(m["content"])
    if not trimmed or trimmed[-1]["role"] != "user":
        raise CompanionError("Last message must be from the chef.", code="bad_request")

    user_text = json.dumps(
        {
            "day_snapshot": build_day_context(service_date),
            "house_profile": get_profile()["text"] or None,
            "conversation": trimmed,
            "format": REPLY_FORMAT,
            "respond_with": {
                "reply": "one plain-text string — your answer to the last message"
            },
        },
        ensure_ascii=False,
    )
    data, model = _call(SYSTEM_PROMPT, user_text)
    # JSON mode sometimes nests the answer ({"reply": {"actions": [...]}})
    # or drops the wrapper; either way render it as text, never a repr.
    reply = _repair_reply(_as_text(data["reply"] if "reply" in data else data))
    if not reply:
        raise CompanionError("Companion returned an empty reply.")
    return {"reply": reply, "model": model}


def _now_iso() -> str:
    return timezone.localtime(timezone.now()).isoformat()


def _payload_tips(brief: CompanionBrief) -> tuple[dict[str, Any], list]:
    payload = brief.payload if isinstance(brief.payload, dict) else {}
    tips = payload.get("tips")
    if not isinstance(tips, list):
        tips = []
    return payload, tips


def _tip_out(tip: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(tip.get("id") or ""),
        "title": str(tip.get("title") or ""),
        "body": str(tip.get("body") or ""),
        "source": str(tip.get("source") or "typed"),
        "created_at": tip.get("created_at"),
        "resolved_at": tip.get("resolved_at"),
    }


def _open_manual_tips() -> list[dict[str, Any]]:
    """Unresolved manual tips from every brief row, oldest first.

    A tip with resolved_at set is hidden. Rows that are not mode=manual
    (old model caches) are ignored — they are not regenerated.
    """
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for brief in CompanionBrief.objects.all().only("payload"):
        payload, tips = _payload_tips(brief)
        if payload.get("mode") != MANUAL_MODE:
            continue
        for tip in tips:
            if not isinstance(tip, dict) or tip.get("resolved_at"):
                continue
            out = _tip_out(tip)
            if out["id"] and out["id"] in seen:
                continue
            if out["id"]:
                seen.add(out["id"])
            if not out["title"] and not out["body"]:
                continue
            found.append(out)
    found.sort(key=lambda t: (str(t.get("created_at") or ""), t.get("id") or ""))
    return found


def _save_manual_tips(
    brief: CompanionBrief, payload: dict[str, Any], tips: list
) -> None:
    stored = dict(payload)
    stored["mode"] = MANUAL_MODE
    stored["tips"] = tips
    brief.payload = stored
    brief.model = ""
    brief.save(update_fields=["payload", "model", "updated_at"])


def _standing_brief_locked() -> CompanionBrief:
    brief, _created = CompanionBrief.objects.select_for_update().get_or_create(
        service_date=STANDING_BRIEF_DATE,
        defaults={"payload": {"mode": MANUAL_MODE, "tips": []}, "model": ""},
    )
    return brief


def _locked_manual_hit(
    tip_id: str,
) -> tuple[CompanionBrief, dict[str, Any], list, int] | None:
    for brief in CompanionBrief.objects.select_for_update().order_by("id"):
        payload, tips = _payload_tips(brief)
        if payload.get("mode") != MANUAL_MODE:
            continue
        for index, tip in enumerate(tips):
            if isinstance(tip, dict) and str(tip.get("id") or "") == tip_id:
                return brief, payload, tips, index
    return None


def _check_source(source: str) -> str:
    clean = (source or "typed").strip().lower()
    if clean not in TIP_SOURCES:
        raise CompanionError(
            "Source must be typed, voice, or banto.",
            code="bad_request",
        )
    return clean


def _check_tip_text(title: str, body: str) -> tuple[str, str]:
    title = (title or "").strip()[:MAX_TIP_TITLE]
    body = (body or "").strip()[:MAX_TIP_BODY]
    if not title and not body:
        raise CompanionError(
            "A tip needs a title or some text.",
            code="bad_request",
        )
    return title, body


def daily_brief(service_date: date, refresh: bool = False) -> dict[str, Any]:
    """Standing manual tips for any service date.

    ``refresh`` is accepted so the existing dashboard poll keeps working.
    It does not call the model and does not overwrite stored tips.
    An empty list is a valid brief. This function does not write.
    """
    del refresh  # explicit no-op — never a regenerate
    standing = CompanionBrief.objects.filter(service_date=STANDING_BRIEF_DATE).first()
    latest = standing or CompanionBrief.objects.order_by("-updated_at").first()
    when = latest.updated_at if latest is not None else timezone.now()
    return {
        "service_date": service_date.isoformat(),
        "generated_at": timezone.localtime(when).isoformat(),
        "model": "",
        "mode": MANUAL_MODE,
        "tips": _open_manual_tips(),
    }


def add_manual_tip(*, title: str = "", body: str = "", source: str = "typed") -> dict[str, Any]:
    """Append one standing tip. Shown every day until resolved or deleted."""
    source = _check_source(source)
    title, body = _check_tip_text(title, body)
    tip = {
        "id": uuid.uuid4().hex,
        "title": title,
        "body": body,
        "source": source,
        "created_at": _now_iso(),
        "resolved_at": None,
    }
    with transaction.atomic():
        brief = _standing_brief_locked()
        payload, tips = _payload_tips(brief)
        tips.append(tip)
        _save_manual_tips(brief, payload, tips)
    return _tip_out(tip)


def edit_manual_tip(
    tip_id: str, *, title: str | None = None, body: str | None = None
) -> dict[str, Any]:
    if title is None and body is None:
        raise CompanionError("Nothing to change on this tip.", code="bad_request")
    with transaction.atomic():
        hit = _locked_manual_hit(tip_id)
        if hit is None:
            raise CompanionError("Tip not found.", code="not_found")
        brief, payload, tips, index = hit
        current = dict(tips[index])
        new_title = current.get("title") if title is None else title
        new_body = current.get("body") if body is None else body
        new_title, new_body = _check_tip_text(str(new_title or ""), str(new_body or ""))
        current["title"] = new_title
        current["body"] = new_body
        tips[index] = current
        _save_manual_tips(brief, payload, tips)
    return _tip_out(current)


def delete_manual_tip(tip_id: str) -> dict[str, Any]:
    with transaction.atomic():
        hit = _locked_manual_hit(tip_id)
        if hit is None:
            raise CompanionError("Tip not found.", code="not_found")
        brief, payload, tips, index = hit
        removed = _tip_out(tips.pop(index))
        _save_manual_tips(brief, payload, tips)
    return removed


def resolve_manual_tip(tip_id: str) -> dict[str, Any]:
    """Hide a tip on every day. The row stays, with resolved_at set."""
    with transaction.atomic():
        hit = _locked_manual_hit(tip_id)
        if hit is None:
            raise CompanionError("Tip not found.", code="not_found")
        brief, payload, tips, index = hit
        current = dict(tips[index])
        if not current.get("resolved_at"):
            current["resolved_at"] = _now_iso()
            tips[index] = current
            _save_manual_tips(brief, payload, tips)
    return _tip_out(current)


def clear_manual_tips() -> dict[str, Any]:
    """Resolve every open manual tip. Does not call the model."""
    now = _now_iso()
    with transaction.atomic():
        for brief in CompanionBrief.objects.select_for_update().order_by("id"):
            payload, tips = _payload_tips(brief)
            if payload.get("mode") != MANUAL_MODE:
                continue
            changed = False
            updated: list = []
            for tip in tips:
                if isinstance(tip, dict) and not tip.get("resolved_at"):
                    tip = dict(tip)
                    tip["resolved_at"] = now
                    changed = True
                updated.append(tip)
            if changed:
                _save_manual_tips(brief, payload, updated)
    return daily_brief(timezone.localdate())


RECIPE_TASK = (
    "Draft a production recipe card for this kitchen from the chef's request. "
    "Quantities sized for base_covers when given (else pick a sensible batch "
    "and say so in notes). Ingredients with qty+unit a commis can weigh out. "
    "Method MEP-first: longest lead first, clock references only where they "
    "matter, show arithmetic in the step where you scale or ratio anything. "
    "allergens: names from the UK 14 list actually present in the recipe. "
    "Plain chef-speak throughout; no invented house rules."
)


def draft_recipe(prompt: str, covers: int | None = None) -> dict[str, Any]:
    """Companion-drafted recipe card — returned for the chef to edit, not saved."""
    text = (prompt or "").strip()[:MAX_CONTENT_CHARS]
    if not text:
        raise CompanionError("Say what to draft.", code="bad_request")
    user_text = json.dumps(
        {
            "task": RECIPE_TASK,
            "request": text,
            "base_covers": covers,
            "house_profile": get_profile()["text"] or None,
            "respond_with": {
                "name": "string",
                "base_covers": "integer or null",
                "yield_qty": "number or null",
                "yield_unit": "string",
                "ingredients": [
                    {"name": "string", "qty": "number or null", "unit": "string", "note": "string"}
                ],
                "method": ["step strings in order"],
                "allergens": ["UK-14 allergen names present"],
                "notes": "string",
            },
        },
        ensure_ascii=False,
    )
    data, model = _call(SYSTEM_PROMPT, user_text)

    def _num(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f == f else None  # NaN guard

    ingredients = [
        {
            "name": str(i.get("name", "")).strip(),
            "qty": _num(i.get("qty")),
            "unit": str(i.get("unit", "")).strip(),
            "note": str(i.get("note", "")).strip(),
        }
        for i in (data.get("ingredients") or [])
        if isinstance(i, dict) and str(i.get("name", "")).strip()
    ]
    method = [_as_text(s) for s in (data.get("method") or []) if _as_text(s)]
    if not ingredients or not method:
        raise CompanionError("Companion returned an incomplete recipe.")
    bc = data.get("base_covers")
    return {
        "name": str(data.get("name", "")).strip() or text[:80],
        "base_covers": int(bc) if isinstance(bc, (int, float)) and bc and bc > 0 else covers,
        "yield_qty": _num(data.get("yield_qty")),
        "yield_unit": str(data.get("yield_unit", "")).strip(),
        "ingredients": ingredients,
        "method": method,
        "allergens": [
            str(a).strip() for a in (data.get("allergens") or []) if str(a).strip()
        ],
        "notes": _as_text(data.get("notes")),
        "source": "companion",
        "model": model,
    }
