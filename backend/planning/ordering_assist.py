"""
Ordering-mode board enrichment + deterministic menu/order assist proposals (D15 depth).
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from assist.models import AssistJob, AssistProposal
from inventory.models import StockBalance
from planning.models import LineComponent, ProductionLine, ServiceSection
from planning.section_modes import PROMPT_VERSION, get_setting
from purchasing.models import PurchaseOrder, PurchaseOrderLine

logger = logging.getLogger(__name__)


def total_stock_qty(item_id: int | None) -> Decimal:
    if not item_id:
        return Decimal("0")
    agg = (
        StockBalance.objects.filter(item_id=item_id)
        .aggregate(t=Sum("qty"))
        .get("t")
    )
    return agg if agg is not None else Decimal("0")


def on_order_qty(item_id: int | None) -> Decimal:
    """Open replenishment PO base qty for item (draft/sent/confirmed)."""
    if not item_id:
        return Decimal("0")
    open_status = [
        PurchaseOrder.Status.DRAFT,
        PurchaseOrder.Status.SENT,
        PurchaseOrder.Status.CONFIRMED,
    ]
    agg = (
        PurchaseOrderLine.objects.filter(
            supplier_item__item_id=item_id,
            purchase_order__status__in=open_status,
            purchase_order__scope=PurchaseOrder.Scope.REPLENISHMENT,
        )
        .aggregate(t=Sum("qty_base"))
        .get("t")
    )
    return agg if agg is not None else Decimal("0")


def ingredient_status_for_item(item_id: int | None) -> dict[str, Any]:
    """
    FE stock dots: green in_stock | yellow running_low | orange on_order | grey unknown.
    Heuristic: qty<=0 and on_order>0 → on_order; qty<=0 → running_low; else in_stock.
    """
    if not item_id:
        return {
            "status": "unknown",
            "status_text": "no catalogue link",
            "stock_qty": None,
            "on_order_qty": None,
        }
    stock = total_stock_qty(item_id)
    oo = on_order_qty(item_id)
    if stock <= 0 and oo > 0:
        st, text = "on_order", "on today's order"
    elif stock <= 0:
        st, text = "running_low", "running low / none counted"
    elif stock < Decimal("1") and oo == 0:
        st, text = "running_low", "running low"
    else:
        st, text = "in_stock", "in stock"
    return {
        "status": st,
        "status_text": text,
        "stock_qty": float(stock),
        "on_order_qty": float(oo),
    }


def enrich_component_dict(comp: dict, *, ordering_mode: bool) -> dict:
    if not ordering_mode:
        return comp
    item_id = comp.get("item_id")
    st = ingredient_status_for_item(item_id)
    out = dict(comp)
    out["stock_status"] = st["status"]
    out["stock_status_text"] = st["status_text"]
    out["stock_qty"] = st["stock_qty"]
    out["on_order_qty"] = st["on_order_qty"]
    # supplier code when linked
    if item_id and not out.get("supplier_code"):
        from catalog.models import SupplierItem

        si = (
            SupplierItem.objects.filter(item_id=item_id, active=True)
            .order_by("-preferred", "id")
            .first()
        )
        if si is not None:
            out["supplier_code"] = si.supplier_code or ""
            out["supplier_item_id"] = si.pk
    return out


def dish_order_summary(components: list[dict]) -> dict[str, Any]:
    """Orange pill counts for ordering-mode dish rows."""
    n = len(components)
    low = sum(
        1
        for c in components
        if c.get("stock_status") in ("running_low", "on_order")
    )
    to_order = sum(1 for c in components if c.get("stock_status") == "running_low")
    return {
        "ingredient_count": n,
        "low_count": low,
        "to_order_count": to_order,
        "label": f"{n} items" + (f" · {to_order} to order" if to_order else ""),
    }


def ensure_menu_completeness_proposals(
    *, service_date: date, section: str
) -> list[AssistProposal]:
    """
    Lines with zero components → pending component_fill proposals (ordering + counts).
    """
    st = get_setting(section)
    if st.mode not in ("ordering", "counts"):
        return []

    from planning.models import ServiceDay

    try:
        day = ServiceDay.objects.get(service_date=service_date)
        sec = ServiceSection.objects.get(service_day=day, section=section)
    except Exception:
        return []

    lines = (
        ProductionLine.objects.filter(service_section=sec)
        .prefetch_related("components")
        .order_by("sort_order", "id")
    )
    created: list[AssistProposal] = []
    for ln in lines:
        if ln.components.exists():
            continue
        # skip if pending already
        exists = AssistProposal.objects.filter(
            kind="menu_completeness",
            status=AssistProposal.Status.PENDING,
            context__line_id=ln.pk,
        ).exists()
        if exists:
            continue
        body = {
            "target": "component_fill",
            "line_id": ln.pk,
            "line_name": ln.name,
            "components": [],
            "rationale": "dish has no ingredient list yet — complete the recipe card",
            "prompt_version": PROMPT_VERSION,
            "needs_input": True,
        }
        p = AssistProposal.objects.create(
            kind="menu_completeness",
            context={
                "section": section,
                "service_date": str(service_date),
                "line_id": ln.pk,
            },
            proposal=body,
            rationale=body["rationale"],
            model="scaffold",
            status=AssistProposal.Status.PENDING,
            parse_error="components empty — chef/LLM must fill before accept",
        )
        created.append(p)
    return created


def ensure_order_suggest_from_board(
    *, service_date: date, section: str
) -> AssistProposal | None:
    """
    One pending order_packs proposal listing running_low ingredients on the board.
    """
    st = get_setting(section)
    if st.mode not in ("ordering", "counts"):
        return None

    from planning.models import ServiceDay

    try:
        day = ServiceDay.objects.get(service_date=service_date)
        sec = ServiceSection.objects.get(service_day=day, section=section)
    except Exception:
        return None

    # dedupe open suggest
    existing = (
        AssistProposal.objects.filter(
            kind="order_suggest",
            status=AssistProposal.Status.PENDING,
            context__section=section,
            context__service_date=str(service_date),
        )
        .order_by("-id")
        .first()
    )
    if existing:
        return existing

    lines = (
        ProductionLine.objects.filter(service_section=sec)
        .prefetch_related("components", "components__item")
        .order_by("sort_order", "id")
    )
    order_lines: list[dict] = []
    seen_items: set[int] = set()
    for ln in lines:
        for c in ln.components.all():
            if not c.item_id or c.item_id in seen_items:
                continue
            st_i = ingredient_status_for_item(c.item_id)
            if st_i["status"] != "running_low":
                continue
            seen_items.add(c.item_id)
            packs = Decimal("1")
            order_lines.append(
                {
                    "item_id": c.item_id,
                    "name": c.item.name if c.item_id else c.name,
                    "packs": float(packs),
                    "why": f"{ln.name}: {st_i['status_text']}",
                }
            )

    if not order_lines:
        return None

    body = {
        "target": "order_packs",
        "lines": order_lines,
        "service_date": str(service_date),
        "section": section,
        "rationale": f"{len(order_lines)} ingredients look short on this board",
        "prompt_version": PROMPT_VERSION,
    }
    return AssistProposal.objects.create(
        kind="order_suggest",
        context={
            "section": section,
            "service_date": str(service_date),
        },
        proposal=body,
        rationale=body["rationale"],
        model="scaffold",
        status=AssistProposal.Status.PENDING,
    )


def board_order_assist_payload(
    *, section: str, service_date: date
) -> dict[str, Any] | None:
    """Top-of-board order card for ordering mode."""
    try:
        st = get_setting(section)
    except Exception:
        return None
    if st.mode != "ordering":
        return None
    p = (
        AssistProposal.objects.filter(
            kind="order_suggest",
            status=AssistProposal.Status.PENDING,
            context__section=section,
            context__service_date=str(service_date),
        )
        .order_by("-id")
        .first()
    )
    if p is None:
        return None
    prop = p.proposal if isinstance(p.proposal, dict) else {}
    return {
        "proposal_id": p.pk,
        "kind": p.kind,
        "status": p.status,
        "target": prop.get("target") or "order_packs",
        "rationale": p.rationale or prop.get("rationale") or "",
        "lines": prop.get("lines") or [],
        "accept_able": p.status == AssistProposal.Status.PENDING
        and not p.parse_error
        and bool(prop.get("lines")),
    }


def build_prep_plan_llm_prompt(
    *, section: str, service_date: date, covers: int | None, lines: list[dict]
) -> str:
    """Prompt for A2A prep_plan rewrite — working required on every step."""
    from planning.prep_plan import catalogue_candidates_for_section

    candidates = catalogue_candidates_for_section(section, limit=50)
    return (
        "TASK kind=prep_plan\n"
        f"prompt_version={PROMPT_VERSION}\n"
        "Return STRICT JSON only: {\"steps\":[...]} No markdown. No TTS.\n"
        "Each step: {"
        '"target":"prep_step","title":string,"phase":"mep"|"day_of",'
        '"order_index":int,"clock_time":"HH:MM"|null,"qty":number|null,'
        '"unit":string|null,"working":string,"watch_out":string|null,'
        '"line_id":int|null}\n'
        "MEP first by lead time (overnight/long reductions top). "
        "MEP steps: clock_time MUST be null. "
        "day_of: clock_time backwards from service. "
        "working REQUIRED on every step — show arithmetic. "
        "Prefer line names/ids from board_lines. Never invent catalogue items.\n"
        f"section={section} service_date={service_date} covers={covers}\n"
        f"board_lines={lines}\n"
        f"candidates={candidates}\n"
    )
