"""
Thin LLM provider for catalogue ingest (decision D10: Mistral).

Multi-modal: text and/or one-or-more images (sheet photos, often rotated).
Swap provider/model = env change + this module. No vendor SDK.
LLM output is raw text/JSON only — never writes domain state.
"""
from __future__ import annotations

import os
from typing import Any, Sequence

import httpx
from django.conf import settings

# Block live ingest when this env is unset.
API_KEY_ENV = "MISTRAL_API_KEY"
MODEL_ENV = "LLM_MODEL"
# Vision-capable default for sheet photo + text ingest.
# pixtral-large-latest retired on Mistral API (2026); Medium 3.5 is the replacement.
DEFAULT_MODEL = "mistral-medium-latest"
CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

# Models known/expected to accept image_url parts (substring match, casefold).
_VISION_MODEL_MARKERS = (
    "pixtral",
    "mistral-small",
    "mistral-medium",
    "mistral-large",
    "vision",
)


def api_key_present() -> bool:
    return bool(get_api_key())


def get_api_key() -> str | None:
    key = os.environ.get(API_KEY_ENV) or getattr(settings, API_KEY_ENV, None) or ""
    key = str(key).strip()
    return key or None


def get_model() -> str:
    return (
        os.environ.get(MODEL_ENV)
        or getattr(settings, MODEL_ENV, None)
        or DEFAULT_MODEL
    )


def model_supports_vision(model: str | None = None) -> bool:
    name = (model or get_model()).casefold()
    return any(m in name for m in _VISION_MODEL_MARKERS)


def _image_part(image_b64: str, image_media_type: str | None) -> dict[str, Any]:
    media = image_media_type or "image/jpeg"
    data_url = f"data:{media};base64,{image_b64}"
    # OpenAI-compatible nested shape (accepted by Mistral pixtral chat completions).
    return {
        "type": "image_url",
        "image_url": {"url": data_url},
    }


def build_user_content(
    user_text: str,
    *,
    image_b64: str | None = None,
    image_media_type: str | None = None,
    images: Sequence[tuple[str, str | None]] | None = None,
) -> str | list[dict[str, Any]]:
    """
    Build chat user content.
    - text only → plain string
    - any images → multimodal list: text block first, then image_url parts
    """
    parts: list[dict[str, Any]] = []
    text = (user_text or "").strip() or (
        "Extract catalogue lines from the attached kitchen sheet image(s). "
        "Photos may be rotated."
    )

    img_list: list[tuple[str, str | None]] = []
    if images:
        img_list.extend(list(images))
    if image_b64:
        img_list.append((image_b64, image_media_type))

    if not img_list:
        return text

    parts.append({"type": "text", "text": text})
    for b64, media in img_list:
        if not b64:
            continue
        parts.append(_image_part(b64, media))
    if len(parts) == 1:
        # only text made it through
        return text
    return parts


def chat_completion_json(
    *,
    system: str,
    user_text: str,
    image_b64: str | None = None,
    image_media_type: str | None = None,
    images: Sequence[tuple[str, str | None]] | None = None,
    model: str | None = None,
    timeout: float = 180.0,
) -> str:
    """
    OpenAI-compatible chat completions via Mistral httpx.
    Multi-modal when image_b64/images provided.
    Forces response_format json_object. Returns assistant text content.
    """
    key = get_api_key()
    if not key:
        raise RuntimeError(
            f"Live LLM call blocked: env {API_KEY_ENV} is not set."
        )

    model_name = model or get_model()
    user_content = build_user_content(
        user_text,
        image_b64=image_b64,
        image_media_type=image_media_type,
        images=images,
    )
    has_images = isinstance(user_content, list) and any(
        isinstance(p, dict) and p.get("type") == "image_url" for p in user_content
    )
    if has_images and not model_supports_vision(model_name):
        raise ValueError(
            f"Model {model_name!r} is not vision-capable; "
            f"set {MODEL_ENV}=mistral-medium-latest (or another vision-capable mistral*) "
            "for photo ingest."
        )

    # Dense MEP grids (100+ dish/component rows) truncate at 8k; default 32k.
    # Override with LLM_MAX_TOKENS if needed.
    try:
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS") or "32768")
    except ValueError:
        max_tokens = 32768
    max_tokens = max(1024, min(max_tokens, 131072))

    body: dict[str, Any] = {
        "model": model_name,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(CHAT_URL, headers=headers, json=body)
        if resp.status_code >= 400:
            # Surface API body for admin/debug without swallowing
            detail = resp.text[:800]
            raise httpx.HTTPStatusError(
                f"Mistral HTTP {resp.status_code}: {detail}",
                request=resp.request,
                response=resp,
            )
        data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("Mistral returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None or str(content).strip() == "":
        raise ValueError("Mistral returned empty content")
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text") or "")
            elif isinstance(part, str):
                texts.append(part)
        content = "\n".join(texts)
    return str(content).strip()
