"""
Public Assist API — Bearer /api/v1/assist/*

List/get proposals, accept/reject, enqueue jobs, recipe explode.
Internal agent-events is NOT here.

NOTE→ASSIST v2: parse_note context is typed; notes alias of text;
empty text → 400; accept_able flag on proposals.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

from api.auth import BearerAuth
from api.types import DecimalQty
from assist import companion, kitchen
from assist.models import AssistJob, AssistProposal
from catalog.ingest import IngestError, propose_from_upload, store_raw_upload
from catalog.models import CatalogIngestUpload
from assist.services import (
    AssistError,
    accept_assist_proposal,
    enqueue_assist_job,
    expire_stale_proposals,
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
    expire_stale_proposals()  # lazy hygiene: stale "today only" rows → expired
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


# ── D16 — kitchen companion (chat + daily brief) ──────────────────


class ChatMessageIn(Schema):
    role: str  # "user" | "assistant"
    content: str


class ChatIn(Schema):
    messages: list[ChatMessageIn]
    service_date: date | None = None


class ChatOut(Schema):
    reply: str
    model: str


class BriefTipOut(Schema):
    id: str = ""
    title: str = ""
    body: str = ""
    source: str = ""
    created_at: str | None = None
    resolved_at: str | None = None


class BriefOut(Schema):
    service_date: str
    generated_at: str
    model: str
    mode: str = "manual"
    tips: list[BriefTipOut]


@router.post(
    "/chat",
    response={200: ChatOut, 400: ErrorOut, 503: ErrorOut},
)
def companion_chat(request: HttpRequest, body: ChatIn):
    sd = body.service_date or timezone.localdate()
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        return 200, companion.companion_chat(msgs, sd)
    except companion.CompanionError as exc:
        status = 400 if exc.code == "bad_request" else 503
        return status, {"detail": str(exc), "code": exc.code}


@router.get(
    "/daily-brief",
    response={200: BriefOut, 503: ErrorOut},
)
def companion_daily_brief(
    request: HttpRequest,
    service_date: date | None = None,
    refresh: bool = False,
):
    sd = service_date or timezone.localdate()
    try:
        return 200, companion.daily_brief(sd, refresh=refresh)
    except companion.CompanionError as exc:
        return 503, {"detail": str(exc), "code": exc.code}


class ProfileOut(Schema):
    text: str
    updated_at: str | None = None


class ProfileIn(Schema):
    text: str


@router.get("/companion-profile", response=ProfileOut)
def get_companion_profile(request: HttpRequest):
    return 200, companion.get_profile()


@router.put("/companion-profile", response=ProfileOut)
def put_companion_profile(request: HttpRequest, body: ProfileIn):
    return 200, companion.set_profile(body.text)


def _companion_http(exc: companion.CompanionError) -> int:
    if exc.code == "not_found":
        return 404
    if exc.code == "bad_request":
        return 400
    return 503


class TipIn(Schema):
    title: str = ""
    body: str = ""
    source: str = "typed"


class TipEditIn(Schema):
    title: str | None = None
    body: str | None = None


class OkOut(Schema):
    ok: bool = True
    id: str = ""


@router.post(
    "/daily-brief/tips",
    response={201: BriefTipOut, 400: ErrorOut},
)
def add_brief_tip(request: HttpRequest, body: TipIn):
    try:
        return 201, companion.add_manual_tip(
            title=body.title, body=body.body, source=body.source
        )
    except companion.CompanionError as exc:
        return _companion_http(exc), {"detail": str(exc), "code": exc.code}


@router.patch(
    "/daily-brief/tips/{tip_id}",
    response={200: BriefTipOut, 400: ErrorOut, 404: ErrorOut},
)
def edit_brief_tip(request: HttpRequest, tip_id: str, body: TipEditIn):
    try:
        return 200, companion.edit_manual_tip(
            tip_id, title=body.title, body=body.body
        )
    except companion.CompanionError as exc:
        return _companion_http(exc), {"detail": str(exc), "code": exc.code}


@router.delete(
    "/daily-brief/tips/{tip_id}",
    response={200: OkOut, 404: ErrorOut},
)
def delete_brief_tip(request: HttpRequest, tip_id: str):
    try:
        removed = companion.delete_manual_tip(tip_id)
    except companion.CompanionError as exc:
        return _companion_http(exc), {"detail": str(exc), "code": exc.code}
    return 200, {"ok": True, "id": removed["id"]}


@router.post(
    "/daily-brief/tips/{tip_id}/resolve",
    response={200: BriefTipOut, 404: ErrorOut},
)
def resolve_brief_tip(request: HttpRequest, tip_id: str):
    try:
        return 200, companion.resolve_manual_tip(tip_id)
    except companion.CompanionError as exc:
        return _companion_http(exc), {"detail": str(exc), "code": exc.code}


@router.post("/daily-brief/clear", response={200: BriefOut})
def clear_brief_tips(request: HttpRequest):
    return 200, companion.clear_manual_tips()


class KitchenNoteIn(Schema):
    title: str = ""
    body: str = ""
    source: str = "typed"


class KitchenNoteOut(Schema):
    id: int
    title: str = ""
    body: str
    source: str
    created_at: str | None = None
    resolved_at: str | None = None


class KitchenInboxOut(Schema):
    id: int
    kind: str
    summary: str = ""
    assist_proposal_id: int | None = None
    catalog_proposal_id: int | None = None
    created_at: str | None = None
    resolved_at: str | None = None


def _kitchen_http(exc: kitchen.KitchenError) -> int:
    if exc.code == "not_found":
        return 404
    return 400


@router.get("/kitchen-notes", response=list[KitchenNoteOut])
def get_kitchen_notes(request: HttpRequest, include_resolved: bool = False):
    return 200, kitchen.list_kitchen_notes(include_resolved=include_resolved)


@router.post(
    "/kitchen-notes",
    response={201: KitchenNoteOut, 400: ErrorOut},
)
def post_kitchen_note(request: HttpRequest, body: KitchenNoteIn):
    try:
        return 201, kitchen.add_kitchen_note(
            title=body.title, body=body.body, source=body.source
        )
    except kitchen.KitchenError as exc:
        return _kitchen_http(exc), {"detail": str(exc), "code": exc.code}


@router.post(
    "/kitchen-notes/{note_id}/resolve",
    response={200: KitchenNoteOut, 404: ErrorOut},
)
def post_resolve_kitchen_note(request: HttpRequest, note_id: int):
    try:
        return 200, kitchen.resolve_kitchen_note(note_id)
    except kitchen.KitchenError as exc:
        return _kitchen_http(exc), {"detail": str(exc), "code": exc.code}


@router.get("/kitchen-inbox", response=list[KitchenInboxOut])
def get_kitchen_inbox(request: HttpRequest, include_resolved: bool = False):
    return 200, kitchen.list_kitchen_inbox(include_resolved=include_resolved)


@router.post(
    "/kitchen-inbox/{item_id}/resolve",
    response={200: KitchenInboxOut, 404: ErrorOut},
)
def post_resolve_kitchen_inbox(request: HttpRequest, item_id: int):
    try:
        return 200, kitchen.resolve_kitchen_inbox_item(item_id)
    except kitchen.KitchenError as exc:
        return _kitchen_http(exc), {"detail": str(exc), "code": exc.code}


class InvoiceUploadIn(Schema):
    raw_text: str
    source_kind: str = "text"


class InvoiceUploadOut(Schema):
    id: int
    status: str
    source_kind: str
    created_at: str
    proposal_count: int
    propose_requested: bool


class ProposeOut(Schema):
    id: int
    status: str
    queued: bool
    task_id: str = ""


def _upload_out(upload: CatalogIngestUpload) -> dict:
    return {
        "id": upload.pk,
        "status": upload.status,
        "source_kind": upload.source_kind,
        "created_at": timezone.localtime(upload.created_at).isoformat(),
        "proposal_count": upload.proposals.count(),
        "propose_requested": upload.propose_requested_at is not None,
    }


@router.post(
    "/invoice-uploads",
    response={201: InvoiceUploadOut, 400: ErrorOut},
    summary="Store invoice or sheet text as raw data. Does not call a model.",
)
def create_invoice_upload(request: HttpRequest, body: InvoiceUploadIn):
    try:
        upload = store_raw_upload(raw_text=body.raw_text, source_kind=body.source_kind)
    except IngestError as exc:
        return 400, {"detail": str(exc), "code": exc.code}
    return 201, _upload_out(upload)


@router.post(
    "/invoice-uploads/{upload_id}/propose",
    response={202: ProposeOut, 400: ErrorOut, 404: ErrorOut},
    summary="Explicit propose from one stored upload. Not run on upload.",
)
def propose_invoice_upload(request: HttpRequest, upload_id: int):
    try:
        task_id = propose_from_upload(upload_id)
    except CatalogIngestUpload.DoesNotExist:
        return 404, {"detail": "Upload not found.", "code": "not_found"}
    except IngestError as exc:
        return 400, {"detail": str(exc), "code": exc.code}
    upload = CatalogIngestUpload.objects.get(pk=upload_id)
    return 202, {
        "id": upload.pk,
        "status": upload.status,
        "queued": True,
        "task_id": task_id,
    }
