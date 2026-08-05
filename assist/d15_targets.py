"""
D15 proposal target accept handlers (v2 targets beyond note tiers).

Targets: planned_qty | order_packs | new_line | component_fill
(prep_step lives in _apply_prep_step; note tiers in _apply_parse_note)
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from assist.models import AssistProposal
from catalog.models import Item, SupplierItem
from planning.models import LineComponent, ProductionLine, ServiceDay, ServiceSection
from planning.section_modes import PROMPT_VERSION, SectionModeError, assert_target_allowed

logger = logging.getLogger(__name__)


class TargetApplyError(Exception):
    def __init__(self, message: str, code: str = "target_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _to_dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def _section_from(proposal: AssistProposal, body: dict) -> str | None:
    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    return ctx.get("section") or body.get("section")


def _gate(target: str, section: str | None) -> None:
    try:
        assert_target_allowed(target=target, section=section)
    except SectionModeError as exc:
        raise TargetApplyError(exc.message, code=exc.code) from exc


def apply_d15_target(proposal: AssistProposal) -> None:
    """Dispatch body.target for non-note kinds / explicit v2 targets."""
    body = proposal.proposal if isinstance(proposal.proposal, dict) else {}
    target = str(body.get("target") or "").strip().lower()
    section = _section_from(proposal, body)

    if target == "planned_qty":
        _gate(target, section)
        _apply_planned_qty(proposal, body)
    elif target == "component_fill":
        _gate(target, section)
        _apply_component_fill(proposal, body)
    elif target == "order_packs":
        _gate(target, section)
        _apply_order_packs(proposal, body)
    elif target == "new_line":
        _gate(target, section)
        _apply_new_line(proposal, body)
    else:
        raise TargetApplyError(
            f"no D15 handler for target={target or '(empty)'}",
            code="unknown_target",
        )

    # stamp
    body = dict(proposal.proposal) if isinstance(proposal.proposal, dict) else {}
    body.setdefault("prompt_version", PROMPT_VERSION)
    body["accepted_at"] = timezone.now().isoformat()
    proposal.proposal = body
    if not proposal.model:
        proposal.model = "d15-accept"
    proposal.save(update_fields=["proposal", "model", "updated_at"])


def _apply_planned_qty(proposal: AssistProposal, body: dict) -> None:
    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    line_id = body.get("line_id") or ctx.get("line_id")
    if line_id is None:
        raise TargetApplyError("planned_qty requires line_id", code="line_required")
    qty = _to_dec(body.get("planned_qty") if "planned_qty" in body else body.get("qty"))
    if qty is None and body.get("planned_qty") is not None:
        raise TargetApplyError("planned_qty must be a number or null", code="bad_qty")
    try:
        line = ProductionLine.objects.select_for_update().get(pk=int(line_id))
    except (ProductionLine.DoesNotExist, TypeError, ValueError) as exc:
        raise TargetApplyError(f"line_id {line_id} not found", code="line_not_found") from exc

    if line.mode == ProductionLine.Mode.CHECK:
        raise TargetApplyError(
            "check-mode lines never take planned_qty", code="check_no_qty"
        )

    from planning.services import _event  # local event helper

    old = line.planned_qty
    line.planned_qty = qty
    line.save(update_fields=["planned_qty", "updated_at"])
    try:
        _event(
            line,
            "assist_planned_qty",
            from_qty=str(old) if old is not None else None,
            to_qty=str(qty) if qty is not None else None,
            proposal_id=proposal.pk,
        )
    except Exception:  # noqa: BLE001
        pass
    body["line_id"] = line.pk
    body["planned_qty"] = float(qty) if qty is not None else None
    proposal.proposal = body


def _apply_component_fill(proposal: AssistProposal, body: dict) -> None:
    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    line_id = body.get("line_id") or ctx.get("line_id")
    if line_id is None:
        raise TargetApplyError("component_fill requires line_id", code="line_required")
    comps = body.get("components")
    if not isinstance(comps, list) or not comps:
        raise TargetApplyError(
            "component_fill requires non-empty components[]", code="bad_components"
        )
    try:
        line = ProductionLine.objects.select_for_update().get(pk=int(line_id))
    except (ProductionLine.DoesNotExist, TypeError, ValueError) as exc:
        raise TargetApplyError(f"line_id {line_id} not found", code="line_not_found") from exc

    replace = bool(body.get("replace", True))
    if replace:
        LineComponent.objects.filter(line=line).delete()

    created = 0
    for i, c in enumerate(comps):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        item_id = c.get("item_id")
        item = None
        if item_id is not None:
            try:
                item = Item.objects.get(pk=int(item_id))
                if not name:
                    name = item.name
            except (Item.DoesNotExist, TypeError, ValueError):
                item = None
        if not name:
            continue
        LineComponent.objects.create(
            line=line,
            item=item,
            name=name[:255],
            planned_qty=_to_dec(c.get("qty") if c.get("qty") is not None else c.get("planned_qty")),
            unit=str(c.get("unit") or (item.base_unit if item else "ea"))[:16],
            sort_order=int(c.get("sort_order") if c.get("sort_order") is not None else i),
            done=False,
        )
        created += 1
    if created == 0:
        raise TargetApplyError("no valid components written", code="bad_components")
    body["line_id"] = line.pk
    body["components_written"] = created
    proposal.proposal = body


def _apply_order_packs(proposal: AssistProposal, body: dict) -> None:
    """
    Add packs to draft replenishment POs.
    body.lines: [{item_id|supplier_item_id, packs, why?}]
    """
    from purchasing.models import PurchaseOrder, PurchaseOrderLine
    from purchasing.services import preferred_supplier_item

    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    lines_in = body.get("lines") or body.get("order_lines") or []
    if not isinstance(lines_in, list) or not lines_in:
        # single-line shorthand
        if body.get("item_id") or body.get("supplier_item_id"):
            lines_in = [body]
        else:
            raise TargetApplyError(
                "order_packs requires lines[] or item_id", code="bad_order_lines"
            )

    order_date = ctx.get("service_date") or body.get("service_date") or timezone.localdate()
    if isinstance(order_date, str):
        order_date = date.fromisoformat(order_date[:10])

    written: list[dict] = []
    for row in lines_in:
        if not isinstance(row, dict):
            continue
        packs = _to_dec(row.get("packs") if row.get("packs") is not None else row.get("qty"))
        if packs is None or packs <= 0:
            continue
        si = None
        sid = row.get("supplier_item_id")
        if sid is not None:
            try:
                si = SupplierItem.objects.select_related("supplier", "item").get(
                    pk=int(sid), active=True
                )
            except (SupplierItem.DoesNotExist, TypeError, ValueError):
                si = None
        if si is None and row.get("item_id") is not None:
            si = preferred_supplier_item(int(row["item_id"]))
        if si is None:
            continue

        po, _ = PurchaseOrder.objects.get_or_create(
            supplier_id=si.supplier_id,
            order_date=order_date,
            status=PurchaseOrder.Status.DRAFT,
            scope=PurchaseOrder.Scope.REPLENISHMENT,
            defaults={"notes": f"assist order_packs proposal#{proposal.pk}"},
        )
        pack_qty = si.pack_qty or Decimal("1")
        qty_base = packs * pack_qty
        pol, created = PurchaseOrderLine.objects.get_or_create(
            purchase_order=po,
            supplier_item=si,
            defaults={
                "proposed_packs": packs,
                "packs": packs,
                "qty_base": qty_base,
                "note": str(row.get("why") or row.get("rationale") or "")[:500],
            },
        )
        if not created:
            pol.packs = (pol.packs or Decimal("0")) + packs
            pol.proposed_packs = (pol.proposed_packs or Decimal("0")) + packs
            pol.qty_base = (pol.packs or Decimal("0")) * pack_qty
            extra = str(row.get("why") or "").strip()
            if extra:
                pol.note = ((pol.note or "") + f" | {extra}").strip(" |")[:500]
            pol.save()
        written.append(
            {
                "po_id": po.pk,
                "po_line_id": pol.pk,
                "supplier_item_id": si.pk,
                "item_id": si.item_id,
                "packs": float(packs),
            }
        )

    if not written:
        raise TargetApplyError(
            "order_packs wrote nothing — need active SupplierItem + packs>0",
            code="order_empty",
        )
    body["written"] = written
    proposal.proposal = body


def _apply_new_line(proposal: AssistProposal, body: dict) -> None:
    ctx = proposal.context if isinstance(proposal.context, dict) else {}
    section = ctx.get("section") or body.get("section")
    sd_raw = ctx.get("service_date") or body.get("service_date")
    name = str(body.get("name") or body.get("line_name") or "").strip()
    if not name:
        raise TargetApplyError("new_line requires name", code="name_required")
    if not section or not sd_raw:
        raise TargetApplyError(
            "new_line requires section + service_date", code="bad_context"
        )
    if isinstance(sd_raw, str):
        sd = date.fromisoformat(sd_raw[:10])
    else:
        sd = sd_raw
    try:
        day = ServiceDay.objects.get(service_date=sd)
        sec = ServiceSection.objects.get(service_day=day, section=section)
    except (ServiceDay.DoesNotExist, ServiceSection.DoesNotExist) as exc:
        raise TargetApplyError(
            "service day/section not open", code="section_not_found"
        ) from exc

    mode = str(body.get("mode") or ProductionLine.Mode.CHECK).strip().lower()
    if mode not in {c.value for c in ProductionLine.Mode}:
        mode = ProductionLine.Mode.CHECK
    kind = str(body.get("kind") or ProductionLine.Kind.DISH).strip().lower()
    if kind not in {c.value for c in ProductionLine.Kind}:
        kind = ProductionLine.Kind.DISH

    item = None
    if body.get("item_id") is not None:
        try:
            item = Item.objects.get(pk=int(body["item_id"]))
        except (Item.DoesNotExist, TypeError, ValueError):
            item = None

    max_sort = (
        ProductionLine.objects.filter(service_section=sec)
        .order_by("-sort_order")
        .values_list("sort_order", flat=True)
        .first()
    )
    sort_order = (max_sort or 0) + 10

    line = ProductionLine.objects.create(
        service_section=sec,
        name=name[:255],
        mode=mode,
        kind=kind,
        unit=str(body.get("unit") or (item.base_unit if item else "ea"))[:16],
        item=item,
        source="assist",
        notes=str(body.get("notes") or "")[:500],
        sort_order=sort_order,
        planned_qty=_to_dec(body.get("planned_qty")),
        proposed_qty=_to_dec(body.get("proposed_qty")),
    )
    body["line_id"] = line.pk
    proposal.proposal = body
