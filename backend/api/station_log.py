"""Station log + storage areas under /api/v1/boards/..."""
from __future__ import annotations

from datetime import date
from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from api.auth import BearerAuth
from assist.providers import suggest_station_log
from planning.services import PlanningError
from planning.station_log import (
    create_log_line,
    list_log,
    list_storage_areas,
    patch_log_line,
    serialize_log_line,
)

router = Router(tags=["station-log"], auth=BearerAuth())


class ErrorOut(Schema):
    detail: str
    code: str


class LogLineIn(Schema):
    kind: str = "mep"
    text: str
    action: str = "none"
    qty: float | int | None = None
    unit: str = ""
    area_id: int | None = None
    item_id: int | None = None
    line_id: int | None = None
    use_by: date | None = None


class LogLinePatchIn(Schema):
    kind: str | None = None
    text: str | None = None
    action: str | None = None
    qty: float | int | None = None
    unit: str | None = None
    area_id: int | None = None
    item_id: int | None = None
    use_by: date | None = None
    status: str | None = None


def _http(exc: PlanningError) -> HttpError:
    status = 404 if exc.code.endswith("not_found") else 400
    if exc.code in {"day_closed", "day_not_found"}:
        status = 404 if "not_found" in exc.code else 409
    return HttpError(status, f"{exc.code}: {exc.message}")


@router.get("/storage-areas", response=list[dict[str, Any]])
def storage_areas(request: HttpRequest):
    return list_storage_areas()


@router.get("/days/{service_date}/sections/{section}/log")
def get_station_log(request: HttpRequest, service_date: date, section: str):
    try:
        return list_log(service_date, section)
    except PlanningError as exc:
        raise _http(exc) from exc


@router.post("/days/{service_date}/sections/{section}/log", response={200: dict, 400: ErrorOut, 404: ErrorOut})
def post_station_log(
    request: HttpRequest, service_date: date, section: str, body: LogLineIn
):
    try:
        row = create_log_line(
            service_date,
            section,
            kind=body.kind,
            text=body.text,
            action=body.action,
            qty=body.qty,
            unit=body.unit,
            area_id=body.area_id,
            item_id=body.item_id,
            line_id=body.line_id,
            use_by=body.use_by,
        )
    except PlanningError as exc:
        raise _http(exc) from exc
    return serialize_log_line(row)


@router.patch(
    "/days/{service_date}/sections/{section}/log/{line_id}",
    response={200: dict, 400: ErrorOut, 404: ErrorOut},
)
def patch_station_log(
    request: HttpRequest,
    service_date: date,
    section: str,
    line_id: int,
    body: LogLinePatchIn,
):
    fields = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
    try:
        row = patch_log_line(service_date, section, line_id, fields)
    except PlanningError as exc:
        raise _http(exc) from exc
    return serialize_log_line(row)


@router.post(
    "/days/{service_date}/sections/{section}/log/suggest",
    response={200: dict, 400: ErrorOut, 404: ErrorOut},
)
def post_station_log_suggest(
    request: HttpRequest, service_date: date, section: str
):
    try:
        return suggest_station_log(service_date, section)
    except PlanningError as exc:
        raise _http(exc) from exc
