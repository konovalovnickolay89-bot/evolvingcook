"""
Public Assist API — Bearer /api/v1/assist/*

List/get proposals, accept/reject, enqueue jobs, recipe explode.
Internal agent-events is NOT here.

NOTE→ASSIST v2: parse_note context is typed; notes alias of text;
empty text → 400; accept_able flag on proposals.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema

from api.auth import BearerAuth
from api.types import DecimalQty
from assist.models import AssistJob, AssistProposal
from assist.services import (
    AssistError,
    accept_assist_proposal,
    enqueue_assist_job,
    explode_item_as_dict,
    proposal_out_dict,
    reject_assist_proposal,
)

router = Router(tags=["assist"], auth=BearerAuth())


class ErrorOut(Schema):
    detail: str
    code: str


class ParseNoteContextIn(Schema):
    """Typed parse_note context. `notes` accepted as alias of `text` at service layer."""

    text: str | None = None
    notes: str | None = None  # alias of text
    line_id: int | None = None
    item_id: int | None = None
    section: str | None = None
    service_date: str | None = None
    line_name: str | None = None
    item_name: str | None = None


class ProposalOut(Schema):
    id: int
    kind: str
    context: dict
    proposal: dict
    # BE-4 / D14 — top-level so FE need not scrape proposal JSON
    target: str | None = None
    target_confidence: str | None = None
    rationale: str
    model: str
    status: str
    decided_at: str | None = None
    reject_reason: str = ""
    task_id: str | None = None
    job_id: int | None = None
    parse_error: str = ""
    accept_able: bool = False
    created_at: str
    updated_at: str


class JobOut(Schema):
    id: int
    kind: str
    context: dict
    status: str
    task_id: str | None = None
    error: str = ""
    created_at: str
    updated_at: str


class JobCreateIn(Schema):
    kind: str = "parse_note"
    # Free dict still accepted for forward-compat; service normalizes parse_note
    context: dict


class RejectIn(Schema):
    """Empty/omitted reason → service stores \"other\" (BE-1)."""

    reason: str = ""


class AcceptIn(Schema):
    """Optional proposal overlay before accept (FE Adjust / fill components)."""

    proposal: dict | None = None


class ExplodeIn(Schema):
    item_id: int
    qty: DecimalQty = None


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _proposal_out(p: AssistProposal) -> dict:
    return proposal_out_dict(p)


def _job_out(j: AssistJob) -> dict:
    return {
        "id": j.pk,
        "kind": j.kind,
        "context": j.context if isinstance(j.context, dict) else {},
        "status": j.status,
        "task_id": j.task_id,
        "error": j.error or "",
        "created_at": _iso(j.created_at) or "",
        "updated_at": _iso(j.updated_at) or "",
    }


@router.get("/proposals", response=list[ProposalOut])
def list_proposals(
    request: HttpRequest,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
):
    qs = AssistProposal.objects.all().order_by("-created_at", "-id")
    if status:
        qs = qs.filter(status=status)
    if kind:
        qs = qs.filter(kind=kind)
    limit = max(1, min(int(limit or 50), 200))
    return [_proposal_out(p) for p in qs[:limit]]


@router.get("/proposals/{proposal_id}", response={200: ProposalOut, 404: ErrorOut})
def get_proposal(request: HttpRequest, proposal_id: int):
    try:
        p = AssistProposal.objects.get(pk=proposal_id)
    except AssistProposal.DoesNotExist:
        return 404, {"detail": "not found", "code": "not_found"}
    return 200, _proposal_out(p)


@router.post(
    "/proposals/{proposal_id}/accept",
    response={200: ProposalOut, 400: ErrorOut, 404: ErrorOut},
)
def accept_proposal(request: HttpRequest, proposal_id: int, body: AcceptIn = None):
    try:
        # Optional FE overlay (adjust qty / fill components) before domain write
        if body and isinstance(body.proposal, dict) and body.proposal:
            from assist.models import AssistProposal as AP

            try:
                p0 = AP.objects.get(pk=proposal_id)
            except AP.DoesNotExist:
                return 404, {"detail": "not found", "code": "not_found"}
            if p0.status == AP.Status.PENDING:
                merged = dict(p0.proposal) if isinstance(p0.proposal, dict) else {}
                merged.update(body.proposal)
                p0.proposal = merged
                # Clear inbox-only flag when FE supplied real structure
                if p0.parse_error and proposal_has_structure_safe(merged):
                    p0.parse_error = ""
                p0.save(update_fields=["proposal", "parse_error", "updated_at"])
        p = accept_assist_proposal(proposal_id)
    except AssistProposal.DoesNotExist:
        return 404, {"detail": "not found", "code": "not_found"}
    except AssistError as exc:
        return 400, {"detail": str(exc), "code": exc.code}
    return 200, _proposal_out(p)


def proposal_has_structure_safe(body: dict) -> bool:
    try:
        from assist.services import proposal_has_structure

        return proposal_has_structure(body)
    except Exception:
        return False


@router.post(
    "/proposals/{proposal_id}/reject",
    response={200: ProposalOut, 400: ErrorOut, 404: ErrorOut},
)
def reject_proposal(request: HttpRequest, proposal_id: int, body: RejectIn = None):
    # BE-1: blank → "other" (also enforced in reject_assist_proposal)
    reason = ((body.reason if body else "") or "").strip() or "other"
    try:
        p = reject_assist_proposal(proposal_id, reason=reason)
    except AssistProposal.DoesNotExist:
        return 404, {"detail": "not found", "code": "not_found"}
    except AssistError as exc:
        return 400, {"detail": str(exc), "code": exc.code}
    return 200, _proposal_out(p)


@router.post(
    "/jobs",
    response={201: JobOut, 400: ErrorOut},
    summary="Enqueue assist job. parse_note: context.text required (notes alias OK).",
)
def create_job(request: HttpRequest, body: JobCreateIn):
    try:
        job = enqueue_assist_job(body.kind, body.context or {})
    except AssistError as exc:
        return 400, {"detail": str(exc), "code": exc.code}
    return 201, _job_out(job)


@router.get("/jobs/{job_id}", response={200: JobOut, 404: ErrorOut})
def get_job(request: HttpRequest, job_id: int):
    try:
        j = AssistJob.objects.get(pk=job_id)
    except AssistJob.DoesNotExist:
        return 404, {"detail": "not found", "code": "not_found"}
    return 200, _job_out(j)


@router.post("/explode", response={200: dict, 400: ErrorOut, 404: ErrorOut})
def explode(request: HttpRequest, body: ExplodeIn):
    qty = body.qty if body.qty is not None else Decimal("1")
    try:
        return 200, explode_item_as_dict(body.item_id, qty=qty)
    except AssistError as exc:
        code = 404 if exc.code == "item_not_found" else 400
        return code, {"detail": str(exc), "code": exc.code}
