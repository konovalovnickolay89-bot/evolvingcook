"""
Modular station-log intelligence.

Providers: rules | hermes | grok
Assigned via env, IntelligenceAssignment row, or PUT /api/internal/intelligence/assign.
Chef never picks a bot. Bots may only insert open StationLogLine drafts.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings

from assist.models import IntelligenceAssignment
from catalog.models import Item, StorageArea
from planning.models import ProductionLine, StationLogLine
from planning.services import PlanningError, _section_for_day, get_day
from planning.station_log import apply_drafts, serialize_log_line
from walks.models import WalkLine

logger = logging.getLogger(__name__)

PROVIDERS = ("rules", "hermes", "grok")
TASK_STATION_LOG = IntelligenceAssignment.Task.STATION_LOG

AREA_ALIASES = (
    ("walk-in fridge", "walk in fridge", "walkin fridge", "fridge"),
    ("walk-in freezer", "walk in freezer", "freezer"),
    ("dry store", "dry stores", "dry"),
    ("pastry",),
    ("butcher",),
    ("veg prep", "veg"),
    ("skybar cellar", "cellar"),
    ("banquet hold",),
)


def resolve_provider(section: str | None = None) -> str:
    sec = (section or "").strip()
    if sec:
        row = (
            IntelligenceAssignment.objects.filter(
                task=TASK_STATION_LOG, section=sec
            )
            .order_by("-id")
            .first()
        )
        if row and row.provider in PROVIDERS:
            return row.provider
    row = (
        IntelligenceAssignment.objects.filter(task=TASK_STATION_LOG, section="")
        .order_by("-id")
        .first()
    )
    if row and row.provider in PROVIDERS:
        return row.provider
    env_p = (getattr(settings, "STATION_LOG_PROVIDER", None) or "rules").strip().lower()
    if env_p in PROVIDERS:
        return env_p
    return "rules"


def assign_provider(
    *,
    task: str = TASK_STATION_LOG,
    provider: str,
    section: str | None = None,
) -> IntelligenceAssignment:
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise PlanningError(f"unknown provider: {provider}", code="bad_provider")
    if task != TASK_STATION_LOG:
        raise PlanningError(f"unknown task: {task}", code="bad_task")
    sec = (section or "").strip()
    obj, _created = IntelligenceAssignment.objects.update_or_create(
        task=task,
        section=sec,
        defaults={"provider": provider},
    )
    return obj


def classify_text(text: str, *, kind_hint: str | None = None) -> dict[str, Any]:
    """Deterministic parse of chef wording. Never invents catalogue names."""
    raw = (text or "").strip()
    low = raw.lower()
    out: dict[str, Any] = {"kind_confidence": "low"}
    if not raw:
        return out

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z%]{0,8})\b", raw)
    if m:
        try:
            out["qty"] = Decimal(m.group(1))
        except Exception:
            pass
        unit = (m.group(2) or "").strip()
        if unit:
            out["unit"] = unit[:16]

    kind = None
    action = None
    if re.search(r"\b86\b|eighty[\s-]?six", low):
        kind, action = StationLogLine.Kind.SERVICE, StationLogLine.Action.NONE
    elif "leftover" in low or "left over" in low:
        kind, action = StationLogLine.Kind.LEFTOVER, StationLogLine.Action.HOLD
    elif "expire" in low or "day-dot" in low or "daydot" in low or "use by" in low:
        kind, action = StationLogLine.Kind.EXPIRE_SOON, StationLogLine.Action.CHECK
    elif "priority" in low or "fire first" in low:
        kind, action = StationLogLine.Kind.COOK_PRIORITY, StationLogLine.Action.PREP
    elif re.search(r"\bhold(ing)?\b|\bstorage\b", low):
        kind, action = StationLogLine.Kind.HOLDING, StationLogLine.Action.HOLD
    elif "house prep" in low or "house-made" in low or "housemade" in low:
        kind, action = StationLogLine.Kind.HOUSE_PREP, StationLogLine.Action.PREP
    elif re.search(r"\bmep\b|mise", low):
        kind, action = StationLogLine.Kind.MEP, StationLogLine.Action.CHECK
    if kind:
        out["kind"] = kind
        out["kind_confidence"] = "high"
    elif kind_hint:
        out["kind"] = kind_hint

    if re.search(r"\border\b", low):
        action = StationLogLine.Action.ORDER
    elif re.search(r"\bcheck\b", low):
        action = StationLogLine.Action.CHECK
    elif re.search(r"\bprep\b", low) and action is None:
        action = StationLogLine.Action.PREP
    if action:
        out["action"] = action

    areas = list(StorageArea.objects.filter(active=True))
    best_area = None
    best_len = 0
    for area in areas:
        name = area.name.lower()
        if name and name in low and len(name) > best_len:
            best_area, best_len = area, len(name)
    if best_area is None:
        for area in areas:
            n = area.name.lower()
            for aliases in AREA_ALIASES:
                if any(a in n for a in aliases) and any(a in low for a in aliases):
                    if len(n) > best_len:
                        best_area, best_len = area, len(n)
    if best_area is not None:
        out["area_id"] = best_area.pk

    tokens = [t for t in re.split(r"[^a-z0-9]+", low) if len(t) >= 4]
    item_hit = None
    if tokens:
        qs = Item.objects.filter(active=True)
        for tok in sorted(tokens, key=len, reverse=True)[:8]:
            hit = qs.filter(name__icontains=tok).order_by("name").first()
            if hit is not None:
                item_hit = hit
                break
    if item_hit is not None:
        out["item_id"] = item_hit.pk
        if "area_id" not in out and item_hit.default_area_id:
            out["area_id"] = item_hit.default_area_id
    return out


def rules_suggest(service_date: date, section: str) -> list[dict[str, Any]]:
    """Fill from kitchen — board, par/stock, last walk. No invented names."""
    from planning.ordering_assist import ingredient_status_for_item

    sec = _section_for_day(get_day(service_date), section)
    drafts: list[dict[str, Any]] = []
    lines = list(
        ProductionLine.objects.filter(service_section=sec)
        .select_related("item", "item__default_area")
        .prefetch_related(
            "components", "components__item", "components__item__default_area"
        )
        .order_by("sort_order", "id")
    )
    banquet = section in {"banqueting", "banquet_buffet"}

    for ln in lines:
        if ln.status == ProductionLine.Status.EIGHTY_SIX:
            drafts.append(
                {
                    "kind": StationLogLine.Kind.SERVICE,
                    "text": f"86 {ln.name}",
                    "action": StationLogLine.Action.NONE,
                    "line_id": ln.pk,
                    "item_id": ln.item_id,
                }
            )
        house = bool(ln.item_id and ln.item and ln.item.house_made)
        if ln.status != ProductionLine.Status.EIGHTY_SIX and (
            ln.mode == ProductionLine.Mode.PRODUCE or house
        ):
            if ln.status != ProductionLine.Status.READY:
                drafts.append(
                    {
                        "kind": StationLogLine.Kind.HOUSE_PREP
                        if house
                        else StationLogLine.Kind.MEP,
                        "text": f"Prep {ln.name}",
                        "action": StationLogLine.Action.PREP,
                        "line_id": ln.pk,
                        "item_id": ln.item_id,
                    }
                )
        if (
            banquet
            and ln.mode == ProductionLine.Mode.PRODUCE
            and ln.planned_qty is None
            and sec.covers is not None
        ):
            drafts.append(
                {
                    "kind": StationLogLine.Kind.COOK_PRIORITY,
                    "text": f"Scale not done — {ln.name}",
                    "action": StationLogLine.Action.PREP,
                    "line_id": ln.pk,
                    "item_id": ln.item_id,
                }
            )

        for comp in ln.components.all():
            item = comp.item
            if item is None:
                continue
            st = ingredient_status_for_item(item.pk, section=section)
            status = st.get("status") or st.get("stock_status") or ""
            area_id = item.default_area_id
            if status in ("running_low", "on_order"):
                drafts.append(
                    {
                        "kind": StationLogLine.Kind.MEP,
                        "text": f"Order {item.name}",
                        "action": StationLogLine.Action.ORDER,
                        "item_id": item.pk,
                        "area_id": area_id,
                        "qty": st.get("shortfall") or st.get("on_order_qty"),
                        "unit": item.base_unit,
                    }
                )
            elif status in ("unknown", "", None) and area_id:
                drafts.append(
                    {
                        "kind": StationLogLine.Kind.MEP,
                        "text": f"Check {item.name}",
                        "action": StationLogLine.Action.CHECK,
                        "item_id": item.pk,
                        "area_id": area_id,
                        "unit": item.base_unit,
                    }
                )

    seen_empty: set[tuple] = set()
    for wl in (
        WalkLine.objects.filter(skipped=False, counted_qty=0, item_id__isnull=False)
        .select_related("item", "area")
        .order_by("-walk__started_at")[:80]
    ):
        key = (wl.item_id, wl.area_id)
        if key in seen_empty:
            continue
        seen_empty.add(key)
        drafts.append(
            {
                "kind": StationLogLine.Kind.MEP,
                "text": f"Empty shelf — {wl.item.name}",
                "action": StationLogLine.Action.CHECK,
                "item_id": wl.item_id,
                "area_id": wl.area_id,
                "qty": 0,
                "unit": wl.counted_unit or (wl.item.base_unit if wl.item else ""),
            }
        )

    return drafts


def build_station_log_prompt(ctx: dict) -> str:
    """Compact JSON-only task for Hermes / Grok. IDs only — no bulk dump."""
    return (
        "You are a station running-chef assistant for Hilton London Wembley.\n"
        "Return ONLY a JSON array of station log drafts. No markdown.\n"
        "Each object: kind, text, action, qty, unit, area_id, item_id, line_id, use_by.\n"
        "kind one of: mep, house_prep, service, holding, leftover, cook_priority, expire_soon.\n"
        "action one of: check, order, prep, hold, none.\n"
        "Use only area_id / item_id / line_id from the context. Never invent SKUs.\n"
        f"context: {json.dumps(ctx, default=str)[:1800]}"
    )


def _compact_context(service_date: date, section: str) -> dict[str, Any]:
    sec = _section_for_day(get_day(service_date), section)
    lines = []
    for ln in ProductionLine.objects.filter(service_section=sec).order_by(
        "sort_order", "id"
    )[:40]:
        lines.append(
            {
                "line_id": ln.pk,
                "name": ln.name,
                "mode": ln.mode,
                "status": ln.status,
                "item_id": ln.item_id,
            }
        )
    areas = [
        {"id": a.pk, "name": a.name}
        for a in StorageArea.objects.filter(active=True).order_by("name")[:20]
    ]
    return {
        "service_date": str(service_date),
        "section": section,
        "covers": sec.covers,
        "lines": lines,
        "areas": areas,
    }


def _enqueue_hermes(service_date: date, section: str) -> dict[str, Any]:
    from assist.services import enqueue_assist_job

    ctx = _compact_context(service_date, section)
    job = enqueue_assist_job("station_log", ctx)
    return {"queued": True, "provider": "hermes", "job_id": job.pk}


def parse_log_drafts_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("lines", "drafts", "items"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
        if data.get("kind") and data.get("text"):
            return [data]
    if isinstance(data, str):
        try:
            return parse_log_drafts_payload(json.loads(data))
        except json.JSONDecodeError:
            return []
    return []


def _call_grok(service_date: date, section: str) -> list[dict[str, Any]]:
    base = (getattr(settings, "GROK_ASSIST_BASE_URL", None) or "").rstrip("/")
    token = getattr(settings, "GROK_ASSIST_TOKEN", None) or ""
    if not base:
        raise PlanningError("GROK_ASSIST_BASE_URL unset", code="grok_unconfigured")
    ctx = _compact_context(service_date, section)
    body = json.dumps(
        {"text": build_station_log_prompt(ctx), "context": ctx}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base, data=body, headers=headers, method="POST")
    timeout = int(getattr(settings, "GROK_ASSIST_TIMEOUT", 30) or 30)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode() or "{}"
            data = json.loads(raw)
    except urllib.error.URLError as exc:
        raise PlanningError(f"Grok unreachable: {exc}", code="grok_unreachable") from exc
    except json.JSONDecodeError as exc:
        raise PlanningError("Grok returned non-JSON", code="grok_bad_json") from exc
    return parse_log_drafts_payload(data)


def suggest_station_log(service_date: date, section: str) -> dict[str, Any]:
    """
    Fill from kitchen. Always runs rules immediately.
    If a bot is assigned, enqueue/call it; on failure kitchen still has rules drafts.
    """
    rules_drafts = rules_suggest(service_date, section)
    created = apply_drafts(service_date, section, rules_drafts)
    provider = resolve_provider(section)
    extra: dict[str, Any] = {"provider": provider}
    if provider == "hermes":
        try:
            extra.update(_enqueue_hermes(service_date, section))
        except Exception as exc:  # noqa: BLE001
            logger.warning("hermes station_log failed, rules already applied: %s", exc)
            extra["error"] = str(exc)[:500]
            extra["fell_back"] = True
    elif provider == "grok":
        try:
            grok_drafts = _call_grok(service_date, section)
            extra_rows = apply_drafts(service_date, section, grok_drafts)
            extra["queued"] = False
            extra["grok_created"] = len(extra_rows)
            created.extend(extra_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("grok station_log failed, rules already applied: %s", exc)
            extra["error"] = str(exc)[:500]
            extra["fell_back"] = True
    else:
        extra["queued"] = False
    return {
        "provider": provider,
        "created_count": len(created),
        "created": [serialize_log_line(r) for r in created],
        **extra,
    }


def apply_agent_station_log_text(
    *,
    service_date: date,
    section: str,
    agent_text: str,
) -> list:
    drafts = parse_log_drafts_payload(agent_text)
    if not drafts:
        try:
            drafts = parse_log_drafts_payload(json.loads(agent_text))
        except (json.JSONDecodeError, TypeError):
            drafts = []
    return apply_drafts(service_date, section, drafts)
