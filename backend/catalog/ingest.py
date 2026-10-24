"""
ingest_catalog: raw upload stored as-is. Proposals only on an explicit ask.

Provider: Mistral (D10) via catalog.llm_provider — OpenAI-compatible httpx, no SDK.
Saving an upload does not call the model and does not create proposal rows.
``propose_from_upload`` is the deliberate path (companion API or admin action).
The worker refuses when ``propose_requested_at`` is empty, so a background
job cannot invent proposals from an upload that was only stored.

If MISTRAL_API_KEY is missing once propose was requested: job fails with the
env name — never fake catalogue. LLM writes proposal rows only; accept
handler writes Item+SupplierItem.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from catalog.llm_provider import (
    API_KEY_ENV,
    api_key_present,
    chat_completion_json,
    get_api_key,
    get_model,
)

logger = logging.getLogger(__name__)

# Back-compat aliases for scripts/admin that may import old names during transition.
mistral_key_present = api_key_present
get_mistral_key = get_api_key

_TEXT_KINDS = frozenset({"text", "csv"})


class IngestError(RuntimeError):
    def __init__(self, detail: str, code: str = "bad_request"):
        super().__init__(detail)
        self.code = code


def store_raw_upload(*, raw_text: str = "", source_kind: str = "text"):
    """Persist invoice or sheet text. Never calls the model or creates proposals."""
    from catalog.models import CatalogIngestUpload

    kind = (source_kind or "text").strip().lower()
    if kind not in _TEXT_KINDS:
        raise IngestError("Source kind must be text or csv.")
    text = (raw_text or "").strip()
    if not text:
        raise IngestError("Add the invoice text before saving.")
    return CatalogIngestUpload.objects.create(
        source_kind=kind,
        raw_text=text,
        status=CatalogIngestUpload.Status.PENDING,
        error="",
        q_task_id="",
        model_name="",
        propose_requested_at=None,
    )


def propose_from_upload(upload_id: int) -> str:
    """Explicit request to turn one stored upload into review proposals.

    This is the only path that may queue a model call for invoice content.
    Upload itself never reaches here.
    """
    from catalog.models import CatalogIngestUpload

    upload = CatalogIngestUpload.objects.get(pk=upload_id)
    has_text = bool((upload.raw_text or "").strip())
    has_image = bool(upload.image)
    if not has_text and not has_image:
        raise IngestError("This upload has no text or file to propose from.")
    if upload.propose_requested_at is None:
        upload.propose_requested_at = timezone.now()
        upload.save(update_fields=["propose_requested_at"])
    return queue_ingest_extraction(upload.pk)

EXTRACTION_SYSTEM = """You extract kitchen catalogue lines from chef sheets/photos.
Return JSON ONLY — no prose, no markdown fences.
Schema:
{
  "items": [
    {
      "dish": string|null,
      "name": string,
      "base_unit": "g"|"ml"|"ea",
      "supplier_name": string|null,
      "supplier_code": string|null,
      "pack_description": string|null,
      "pack_qty": number|null,
      "price": number|null,
      "confidence": number,
      "notes": string|null,
      "flag_ambiguous_unit": boolean
    }
  ]
}
Rules:
- base_unit must be g, ml, or ea only. Flag ambiguous units (flag_ambiguous_unit=true) rather than resolving.
- Never guess a supplier code — emit null + low confidence.
- Never drop an item for missing supplier data.
- Dual codes like "112724 / 591085" → keep as one string in supplier_code.
- Alternative suppliers ("BPM or Brakes") → put full text in supplier_name, lower confidence, note it.
- Spec-in-name ("Chicken fillet 140g-170g") stays in name; do not invent pack_qty from that.
- Convert kg→g and L→ml only when explicitly stated as pack size; pack_qty always in base units.
- confidence 0..1. Mark verify/uncertain source notes with confidence < 0.7.
- Photos may be rotated; read labels as written on the sheet.
- When an image is attached, OCR/read every visible line; do not ignore the photo in favour of empty text.
- Dense MEP grids (dish columns → component lists): one item per component line;
  dish = column/header title, name = component text, base_unit = "ea",
  supplier_name/supplier_code/pack_* /price = null, confidence high when legible.
  ED/highlighted dish marks → notes "ED" (or keep short). Skip decorative lines.
  Keep JSON compact — omit null fluff keys when possible; finish the full sheet.
"""


def queue_ingest_extraction(upload_id: int) -> str:
    """Enqueue django-q2 job. Returns task id. Does not call the LLM inline.

    Refuses unless ``propose_from_upload`` has set ``propose_requested_at``.
    A bare upload must not land on the worker.
    """
    from django_q.tasks import async_task

    from catalog.models import CatalogIngestUpload

    upload = CatalogIngestUpload.objects.get(pk=upload_id)
    if upload.propose_requested_at is None:
        raise IngestError(
            "Propose was not requested for this upload. It stays stored as raw data.",
            code="propose_not_requested",
        )
    task_id = async_task(
        "catalog.ingest.run_ingest_extraction",
        upload_id,
        task_name=f"ingest_catalog_{upload_id}",
    )
    upload.status = CatalogIngestUpload.Status.QUEUED
    upload.q_task_id = str(task_id)
    upload.error = ""
    upload.save(update_fields=["status", "q_task_id", "error"])
    return str(task_id)


def run_ingest_extraction(upload_id: int) -> dict[str, Any]:
    """
    django-q2 worker entrypoint.
    Does nothing to the model unless propose was requested explicitly.
    Blocks live extraction when MISTRAL_API_KEY missing — never fakes rows.
    """
    from catalog.models import CatalogIngestProposal, CatalogIngestUpload

    upload = CatalogIngestUpload.objects.get(pk=upload_id)
    if upload.propose_requested_at is None:
        if upload.status in {
            CatalogIngestUpload.Status.QUEUED,
            CatalogIngestUpload.Status.RUNNING,
        }:
            upload.status = CatalogIngestUpload.Status.PENDING
            upload.q_task_id = ""
            upload.error = ""
            upload.save(update_fields=["status", "q_task_id", "error"])
        logger.info(
            "ingest left raw upload_id=%s (propose not requested)", upload_id
        )
        return {
            "ok": False,
            "skipped": "propose_not_requested",
            "error": (
                "Upload kept as raw data. Proposals are created only when you ask."
            ),
        }

    upload.status = CatalogIngestUpload.Status.RUNNING
    upload.error = ""
    upload.save(update_fields=["status", "error"])

    key = get_api_key()
    if not key:
        msg = (
            f"Live catalogue extraction blocked: env {API_KEY_ENV} is not set. "
            "Models/admin/job skeleton only — refusing to invent catalogue rows."
        )
        upload.status = CatalogIngestUpload.Status.FAILED
        upload.error = msg
        upload.save(update_fields=["status", "error"])
        logger.error(msg)
        return {"ok": False, "error": msg, "blocked_env": API_KEY_ENV}

    try:
        payload = _build_user_payload(upload)
        model_name = get_model()
        raw_json = _call_llm_strict_json(payload, model=model_name)
        items = _parse_items(raw_json)
        with transaction.atomic():
            CatalogIngestProposal.objects.filter(upload=upload).delete()
            for row in items:
                CatalogIngestProposal.objects.create(
                    upload=upload,
                    dish=row.get("dish") or "",
                    name=row["name"],
                    base_unit=row.get("base_unit") or "ea",
                    supplier_name=row.get("supplier_name") or "",
                    supplier_code=row.get("supplier_code") or "",
                    pack_description=row.get("pack_description") or "",
                    pack_qty=row.get("pack_qty"),
                    price=row.get("price"),
                    confidence=row.get("confidence"),
                    flagged_low_confidence=bool(row.get("flagged_low_confidence")),
                    notes=row.get("notes") or "",
                    raw=row.get("raw") or {},
                )
            upload.status = CatalogIngestUpload.Status.REVIEW
            upload.model_name = model_name
            upload.error = ""
            upload.save(update_fields=["status", "model_name", "error"])
        return {"ok": True, "count": len(items)}
    except Exception as exc:  # noqa: BLE001 — surface to upload.error
        logger.exception("ingest extraction failed upload_id=%s", upload_id)
        upload.status = CatalogIngestUpload.Status.FAILED
        upload.error = f"{type(exc).__name__}: {exc}"
        upload.save(update_fields=["status", "error"])
        return {"ok": False, "error": upload.error}


def _build_user_payload(upload) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_kind": upload.source_kind,
        "text": upload.raw_text or "",
        "image_base64": None,
        "image_media_type": None,
        "images": [],  # list[(b64, media_type)] — multi-modal
    }
    if upload.image:
        path = Path(upload.image.path)
        if path.is_file():
            data = path.read_bytes()
            # Phone sheet photos; ~8MB raw cap
            if len(data) > 8_000_000:
                raise ValueError("Image exceeds 8MB limit for extraction")
            suffix = path.suffix.lower()
            media = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".heic": "image/heic",
                ".heif": "image/heif",
            }.get(suffix)
            if media is None:
                # sniff
                if data[:3] == b"\xff\xd8\xff":
                    media = "image/jpeg"
                elif data[:8] == b"\x89PNG\r\n\x1a\n":
                    media = "image/png"
                elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                    media = "image/webp"
                else:
                    media = "image/jpeg"
            if media in {"image/heic", "image/heif"}:
                raise ValueError(
                    "HEIC/HEIF not supported for Mistral data-URL ingest — "
                    "re-export as JPEG/PNG from the phone."
                )
            b64 = base64.standard_b64encode(data).decode("ascii")
            payload["image_base64"] = b64
            payload["image_media_type"] = media
            payload["images"] = [(b64, media)]
            if upload.source_kind != upload.SourceKind.PHOTO:
                # Keep DB as-is if already set; callers may still pass TEXT+image.
                pass
    if not payload["text"] and not payload["images"]:
        raise ValueError("Upload has neither text nor image content")
    return payload


def _call_llm_strict_json(payload: dict[str, Any], *, model: str) -> str:
    text_part = payload.get("text") or ""
    dense_hint = (
        " If this is a multi-column MEP grid, emit one JSON item per component "
        "under its dish header; keep fields short (dish, name, base_unit=ea, "
        "notes only when ED/handwritten); cover every column including bottom rows."
    )
    if payload.get("images") and not text_part:
        user_text = (
            "Extract catalogue lines from the attached kitchen sheet photo(s). "
            "Photos may be rotated. Return JSON only per system schema."
            + dense_hint
        )
    else:
        user_text = (
            "Extract catalogue lines from this kitchen sheet content "
            "(text and/or attached image)."
            + dense_hint
            + "\n\n"
            f"{text_part or '(see image)'}"
        )
    joined = chat_completion_json(
        system=EXTRACTION_SYSTEM,
        user_text=user_text,
        images=payload.get("images") or None,
        image_b64=None if payload.get("images") else payload.get("image_base64"),
        image_media_type=None
        if payload.get("images")
        else payload.get("image_media_type"),
        model=model,
        timeout=300.0,
    )
    return _strip_fences(joined)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_items(raw_json: str) -> list[dict[str, Any]]:
    data = json.loads(raw_json)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("items") or data.get("rows") or []
    else:
        raise ValueError("Extraction JSON root must be object or array")

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        unit = (row.get("base_unit") or "ea").strip().lower()
        if unit not in {"g", "ml", "ea"}:
            unit = "ea"
            row["flag_ambiguous_unit"] = True
        conf = _dec(row.get("confidence"))
        flagged = bool(row.get("flag_ambiguous_unit")) or bool(
            row.get("flagged_low_confidence")
        )
        if conf is not None and conf < Decimal("0.7"):
            flagged = True
        # Never invent codes: empty string if null
        code = row.get("supplier_code")
        if code is not None:
            code = str(code).strip()
        else:
            code = ""
            flagged = True
        out.append(
            {
                "dish": (row.get("dish") or "") or "",
                "name": name,
                "base_unit": unit,
                "supplier_name": (row.get("supplier_name") or "") or "",
                "supplier_code": code,
                "pack_description": (row.get("pack_description") or "") or "",
                "pack_qty": _dec(row.get("pack_qty")),
                "price": _dec(row.get("price")),
                "confidence": conf,
                "flagged_low_confidence": flagged,
                "notes": (row.get("notes") or "") or "",
                "raw": row,
            }
        )
    return out


def mark_upload_done_if_settled(upload_id: int) -> None:
    from catalog.models import CatalogIngestProposal, CatalogIngestUpload

    upload = CatalogIngestUpload.objects.get(pk=upload_id)
    pending = upload.proposals.filter(
        status=CatalogIngestProposal.Status.PENDING
    ).exists()
    if not pending and upload.status == CatalogIngestUpload.Status.REVIEW:
        upload.status = CatalogIngestUpload.Status.DONE
        upload.save(update_fields=["status"])
