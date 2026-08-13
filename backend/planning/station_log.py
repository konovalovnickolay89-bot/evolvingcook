"""Station running-chef log: CRUD, carry, draft apply. No catalogue writes."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

from catalog.models import Item, StorageArea
from planning.models import ProductionLine, ServiceDay, ServiceSection, StationLogLine
from planning.services import PlanningError, _dec_json, _section_for_day, get_day
from walks.models import Walk, WalkLine

AREA_REQUIRED_KINDS = frozenset(
    {
        StationLogLine.Kind.HOLDING,
        StationLogLine.Kind.LEFTOVER,
        StationLogLine.Kind.EXPIRE_SOON,
    }
)

KIND_ORDER = [c.value for c in StationLogLine.Kind]


def _qty_json(v: Decimal | None):
    return _dec_json(v)


def last_walk_count(item_id: int | None, area_id: int | None) -> dict | None:
    if not item_id:
        return None
    qs = WalkLine.objects.filter(item_id=item_id).select_related("walk", "area")
    if area_id:
        qs = qs.filter(area_id=area_id)
    row = qs.order_by("-walk__started_at", "-id").first()
    if row is None:
        return None
    return {
        "walk_id": row.walk_id,
        "counted_qty": _qty_json(row.counted_qty),
        "skipped": bool(row.skipped),
        "area_id": row.area_id,
        "area_name": row.area.name if row.area_id else "",
    }


def serialize_log_line(row: StationLogLine) -> dict[str, Any]:
    item = row.item
    area = row.area
    default_area = None
    if item is not None and item.default_area_id:
        da = item.default_area
        default_area = {"id": da.pk, "name": da.name, "kind": da.kind}
    walk = last_walk_count(row.item_id, row.area_id)
    return {
        "id": row.pk,
        "kind": row.kind,
        "text": row.text,
        "action": row.action,
        "qty": _qty_json(row.qty),
        "unit": row.unit or "",
        "area_id": row.area_id,
        "area_name": area.name if area is not None else "",
        "item_id": row.item_id,
        "item_name": item.name if item is not None else "",
        "default_area": default_area,
        "line_id": row.line_id,
        "use_by": str(row.use_by) if row.use_by else None,
        "status": row.status,
        "source": row.source,
        "carried_from_id": row.carried_from_id,
        "from_yesterday": bool(row.carried_from_id),
        "walk_count": walk,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "done_at": row.done_at.isoformat() if row.done_at else None,
    }


def carry_open_from_yesterday(sec: ServiceSection) -> int:
    """Idempotent: copy yesterday's still-open lines onto today."""
    yday = sec.service_day.service_date - timedelta(days=1)
    try:
        prev_day = ServiceDay.objects.get(service_date=yday)
        prev = ServiceSection.objects.get(service_day=prev_day, section=sec.section)
    except (ServiceDay.DoesNotExist, ServiceSection.DoesNotExist):
        return 0
    existing = set(
        StationLogLine.objects.filter(
            service_section=sec,
            carried_from_id__isnull=False,
        ).values_list("carried_from_id", flat=True)
    )
    created = 0
    for src in StationLogLine.objects.filter(
        service_section=prev, status=StationLogLine.Status.OPEN
    ):
        if src.pk in existing:
            continue
        StationLogLine.objects.create(
            service_section=sec,
            kind=src.kind,
            text=src.text,
            action=src.action,
            qty=src.qty,
            unit=src.unit,
            area_id=src.area_id,
            item_id=src.item_id,
            line_id=None,
            use_by=src.use_by,
            status=StationLogLine.Status.OPEN,
            source=StationLogLine.Source.CARRIED,
            carried_from=src,
        )
        created += 1
    return created


def list_log(service_date: date, section: str) -> dict[str, Any]:
    day = get_day(service_date)
    sec = _section_for_day(day, section)
    carry_open_from_yesterday(sec)
    rows = list(
        StationLogLine.objects.filter(service_section=sec)
        .select_related("area", "item", "item__default_area", "line")
        .order_by("status", "kind", "id")
    )
    open_n = sum(1 for r in rows if r.status == StationLogLine.Status.OPEN)
    grouped: dict[str, list] = {k: [] for k in KIND_ORDER}
    for r in rows:
        grouped.setdefault(r.kind, []).append(serialize_log_line(r))
    return {
        "service_date": str(service_date),
        "section": section,
        "open_count": open_n,
        "lines": [serialize_log_line(r) for r in rows],
        "by_kind": grouped,
    }


def _parse_qty(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise PlanningError("qty must be a number", code="bad_qty") from exc


def _parse_use_by(raw) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise PlanningError("use_by must be YYYY-MM-DD", code="bad_use_by") from exc


def create_log_line(
    service_date: date,
    section: str,
    *,
    kind: str,
    text: str,
    action: str = StationLogLine.Action.NONE,
    qty=None,
    unit: str = "",
    area_id: int | None = None,
    item_id: int | None = None,
    line_id: int | None = None,
    use_by=None,
    source: str = StationLogLine.Source.CHEF,
    classify: bool = True,
) -> StationLogLine:
    day = get_day(service_date)
    sec = _section_for_day(day, section)
    kind_s = (kind or "").strip()
    if kind_s not in {c.value for c in StationLogLine.Kind}:
        raise PlanningError(f"unknown kind: {kind_s}", code="bad_kind")
    action_s = (action or StationLogLine.Action.NONE).strip()
    if action_s not in {c.value for c in StationLogLine.Action}:
        raise PlanningError(f"unknown action: {action_s}", code="bad_action")
    text_s = (text or "").strip()
    if not text_s:
        raise PlanningError("text required", code="bad_text")
    if len(text_s) > 500:
        text_s = text_s[:500]

    if classify and source == StationLogLine.Source.CHEF:
        from assist.providers import classify_text

        hint = classify_text(text_s, kind_hint=kind_s)
        if not area_id and hint.get("area_id"):
            area_id = hint["area_id"]
        if not item_id and hint.get("item_id"):
            item_id = hint["item_id"]
        if qty is None and hint.get("qty") is not None:
            qty = hint["qty"]
        if hint.get("kind") and kind_s == StationLogLine.Kind.MEP:
            # only auto-upgrade kind from default mep when keywords are strong
            if hint.get("kind_confidence") == "high":
                kind_s = hint["kind"]
        if hint.get("action") and action_s == StationLogLine.Action.NONE:
            action_s = hint["action"]
        if not unit and hint.get("unit"):
            unit = hint["unit"]

    if area_id is not None and not StorageArea.objects.filter(pk=area_id).exists():
        raise PlanningError("unknown area", code="area_not_found")
    if item_id is not None and not Item.objects.filter(pk=item_id).exists():
        raise PlanningError("unknown item", code="item_not_found")
    if line_id is not None:
        if not ProductionLine.objects.filter(
            pk=line_id, service_section=sec
        ).exists():
            raise PlanningError("line not on this station", code="line_not_found")

    row = StationLogLine.objects.create(
        service_section=sec,
        kind=kind_s,
        text=text_s,
        action=action_s,
        qty=_parse_qty(qty),
        unit=(unit or "")[:16],
        area_id=area_id,
        item_id=item_id,
        line_id=line_id,
        use_by=_parse_use_by(use_by),
        status=StationLogLine.Status.OPEN,
        source=source,
    )
    return row


def patch_log_line(
    service_date: date,
    section: str,
    line_pk: int,
    fields: dict[str, Any],
) -> StationLogLine:
    day = get_day(service_date)
    sec = _section_for_day(day, section)
    try:
        row = StationLogLine.objects.select_related("area", "item").get(
            pk=line_pk, service_section=sec
        )
    except StationLogLine.DoesNotExist as exc:
        raise PlanningError("log line not found", code="log_not_found") from exc

    upd = []
    if "text" in fields and fields["text"] is not None:
        t = str(fields["text"]).strip()[:500]
        if not t:
            raise PlanningError("text required", code="bad_text")
        row.text = t
        upd.append("text")
    if "kind" in fields and fields["kind"]:
        k = str(fields["kind"]).strip()
        if k not in {c.value for c in StationLogLine.Kind}:
            raise PlanningError(f"unknown kind: {k}", code="bad_kind")
        row.kind = k
        upd.append("kind")
    if "action" in fields and fields["action"] is not None:
        a = str(fields["action"]).strip()
        if a not in {c.value for c in StationLogLine.Action}:
            raise PlanningError(f"unknown action: {a}", code="bad_action")
        row.action = a
        upd.append("action")
    if "qty" in fields:
        row.qty = _parse_qty(fields["qty"])
        upd.append("qty")
    if "unit" in fields and fields["unit"] is not None:
        row.unit = str(fields["unit"])[:16]
        upd.append("unit")
    if "area_id" in fields:
        aid = fields["area_id"]
        if aid in ("", None):
            row.area_id = None
        else:
            if not StorageArea.objects.filter(pk=int(aid)).exists():
                raise PlanningError("unknown area", code="area_not_found")
            row.area_id = int(aid)
        upd.append("area")
    if "item_id" in fields:
        iid = fields["item_id"]
        if iid in ("", None):
            row.item_id = None
        else:
            if not Item.objects.filter(pk=int(iid)).exists():
                raise PlanningError("unknown item", code="item_not_found")
            row.item_id = int(iid)
        upd.append("item")
    if "use_by" in fields:
        row.use_by = _parse_use_by(fields["use_by"])
        upd.append("use_by")
    if "status" in fields and fields["status"]:
        st = str(fields["status"]).strip()
        if st not in {c.value for c in StationLogLine.Status}:
            raise PlanningError("status must be open or done", code="bad_status")
        if st == StationLogLine.Status.DONE and row.kind in AREA_REQUIRED_KINDS:
            area_id = row.area_id
            if "area_id" in fields:
                aid = fields["area_id"]
                area_id = None if aid in ("", None) else int(aid)
            if not area_id:
                raise PlanningError(
                    "holding, leftovers, and expire-soon need a store or fridge",
                    code="area_required",
                )
        row.status = st
        if st == StationLogLine.Status.DONE:
            row.done_at = timezone.now()
            upd.append("done_at")
        else:
            row.done_at = None
            upd.append("done_at")
        upd.append("status")
    if not upd:
        return row
    row.save(update_fields=[*upd, "updated_at"])
    return row


def _dupe_exists(sec: ServiceSection, draft: dict) -> bool:
    qs = StationLogLine.objects.filter(
        service_section=sec,
        kind=draft["kind"],
        status=StationLogLine.Status.OPEN,
    )
    if draft.get("line_id"):
        return qs.filter(line_id=draft["line_id"]).exists()
    if draft.get("item_id") and draft.get("area_id"):
        return qs.filter(item_id=draft["item_id"], area_id=draft["area_id"]).exists()
    if draft.get("item_id"):
        return qs.filter(item_id=draft["item_id"], area_id__isnull=True).exists()
    text = (draft.get("text") or "").strip().lower()
    if text:
        return qs.filter(text__iexact=text).exists()
    return False


def apply_drafts(service_date: date, section: str, drafts: list[dict]) -> list[StationLogLine]:
    """Insert open suggest lines. Never invent items/areas. Skip dupes."""
    day = get_day(service_date)
    sec = _section_for_day(day, section)
    created: list[StationLogLine] = []
    valid_kinds = {c.value for c in StationLogLine.Kind}
    valid_actions = {c.value for c in StationLogLine.Action}
    for raw in drafts:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip()
        if kind not in valid_kinds:
            continue
        text = str(raw.get("text") or "").strip()[:500]
        if not text:
            continue
        action = str(raw.get("action") or StationLogLine.Action.NONE).strip()
        if action not in valid_actions:
            action = StationLogLine.Action.NONE
        area_id = raw.get("area_id")
        item_id = raw.get("item_id")
        line_id = raw.get("line_id")
        try:
            area_id = int(area_id) if area_id not in (None, "") else None
        except (TypeError, ValueError):
            area_id = None
        try:
            item_id = int(item_id) if item_id not in (None, "") else None
        except (TypeError, ValueError):
            item_id = None
        try:
            line_id = int(line_id) if line_id not in (None, "") else None
        except (TypeError, ValueError):
            line_id = None
        if area_id and not StorageArea.objects.filter(pk=area_id).exists():
            area_id = None
        if item_id and not Item.objects.filter(pk=item_id).exists():
            item_id = None
        if line_id and not ProductionLine.objects.filter(
            pk=line_id, service_section=sec
        ).exists():
            line_id = None
        draft = {
            "kind": kind,
            "text": text,
            "item_id": item_id,
            "area_id": area_id,
            "line_id": line_id,
        }
        if _dupe_exists(sec, draft):
            continue
        qty = None
        if raw.get("qty") not in (None, ""):
            try:
                qty = Decimal(str(raw["qty"]))
            except (InvalidOperation, ValueError):
                qty = None
        use_by = None
        if raw.get("use_by"):
            try:
                use_by = _parse_use_by(raw.get("use_by"))
            except PlanningError:
                use_by = None
        created.append(
            StationLogLine.objects.create(
                service_section=sec,
                kind=kind,
                text=text,
                action=action,
                qty=qty,
                unit=str(raw.get("unit") or "")[:16],
                area_id=area_id,
                item_id=item_id,
                line_id=line_id,
                use_by=use_by,
                status=StationLogLine.Status.OPEN,
                source=StationLogLine.Source.SUGGEST,
            )
        )
    return created


def list_storage_areas() -> list[dict[str, Any]]:
    return [
        {"id": a.pk, "name": a.name, "kind": a.kind}
        for a in StorageArea.objects.filter(active=True).order_by(
            "walk_order", "name"
        )
    ]
