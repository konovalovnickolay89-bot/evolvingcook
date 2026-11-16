"""
Thin LLM provider for catalogue ingest (decision D10: Mistral).

Multi-modal: text and/or one-or-more images (sheet photos, often rotated).
Swap provider/model = env change + this module. No vendor SDK.
LLM output is raw text/JSON only — never writes domain state.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Sequence

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Block live ingest when this env is unset.
API_KEY_ENV = "MISTRAL_API_KEY"
MODEL_ENV = "LLM_MODEL"
# Vision-capable default for sheet photo + text ingest.
# pixtral-large-latest retired on Mistral API (2026); Medium 3.5 is the replacement.
DEFAULT_MODEL = "mistral-medium-latest"
CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

# Companion answers are a phone screen (≤180 words) or one recipe card.
# The ingest default below is for dense MEP grids. Reserving it on a
# companion call is what makes prompt tokens + max_tokens exceed the model
# context — Mistral answers that with HTTP 400 before it generates anything.
COMPANION_MAX_TOKENS = 4096
INGEST_MAX_TOKENS = 32768

# Documented context windows, conservative where an alias has moved.
# https://docs.mistral.ai/resources/known-limitations (16 Nov 2026)
# mistral-large-latest is Mistral Large 4 (1M) since 2026-11-05.
# Large 4's completion ceiling is wire-enforced at 262144 (HTTP 400 / 3058
# above that). Unknown ids use the OpenAPI card default of 32768 so a stale
# alias cannot reserve more completion tokens than that window.
_CONTEXT_BY_MARKER = (
    ("mistral-large", 1_048_576),
    ("mistral-medium", 131_072),  # Medium 3.1 is 128k; 3.5 is 256k
    ("mistral-small", 131_072),
    ("pixtral", 131_072),
    ("codestral", 131_072),
    ("ministral", 131_072),
    ("magistral", 131_072),
    ("open-mistral", 32_768),
)
_UNKNOWN_CONTEXT = 32_768
_LARGE_COMPLETION_CEILING = 262_144
_DEFAULT_COMPLETION_CEILING = 32_768
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 1.5  # ChatCompletionRequest.temperature.maximum

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"(?i)authorization\s*[:=]\s*\S+")
_JSON_NOTE = "Respond with a JSON object."

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


class MistralHTTPError(RuntimeError):
    """Non-2xx from Mistral. ``provider_message`` is already redacted."""

    def __init__(self, status_code: int, provider_message: str):
        self.status_code = int(status_code)
        self.provider_message = provider_message
        super().__init__(f"Mistral HTTP {status_code}: {provider_message}")


def context_limit(model: str) -> int:
    name = (model or "").casefold()
    for marker, limit in _CONTEXT_BY_MARKER:
        if marker in name:
            return limit
    return _UNKNOWN_CONTEXT


def completion_ceiling(model: str) -> int:
    if "mistral-large" in (model or "").casefold():
        return _LARGE_COMPLETION_CEILING
    return _DEFAULT_COMPLETION_CEILING


def resolve_model(model: str | None) -> str:
    """Blank or illegal ids fall back to settings, then the ingest default."""
    candidate = (model or "").strip()
    if not candidate:
        candidate = (get_model() or "").strip()
    if not _MODEL_RE.match(candidate):
        return DEFAULT_MODEL
    return candidate


def clamp_temperature(value: Any) -> float:
    try:
        temp = float(value)
    except (TypeError, ValueError):
        return 0.0
    if temp != temp:  # NaN
        return 0.0
    return max(TEMPERATURE_MIN, min(TEMPERATURE_MAX, temp))


def _content_present(content: Any) -> bool:
    if content is None:
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return bool(content)
    return True


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                bits.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                bits.append(part)
        return "\n".join(bits)
    return ""


def estimate_tokens(messages: Sequence[dict[str, Any]]) -> int:
    """Rough budget: 4 characters per token, plus a fixed cost per image."""
    chars = 0
    for message in messages:
        chars += 8
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    chars += len(str(part.get("text") or ""))
                elif part.get("type") == "image_url":
                    chars += 6000
    return max(1, chars // 4)


def _strip_nul(text: str) -> str:
    return text.replace("\x00", "").strip()


def _coerce_content(content: Any, *, allow_parts: bool) -> str | list[dict[str, Any]] | None:
    """String, or a user multimodal list. Anything else becomes text or is dropped."""
    if content is None:
        return None
    if isinstance(content, str):
        text = _strip_nul(content)
        return text or None
    if isinstance(content, list):
        parts: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, str):
                text = _strip_nul(part)
                if text:
                    parts.append({"type": "text", "text": text})
                continue
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text = _strip_nul(str(part.get("text") or ""))
                if text:
                    parts.append({"type": "text", "text": text})
            elif allow_parts and part.get("type") == "image_url" and isinstance(
                part.get("image_url"), dict
            ):
                url = str(part["image_url"].get("url") or "").strip()
                if url:
                    parts.append({"type": "image_url", "image_url": {"url": url}})
        if not parts:
            return None
        if not allow_parts or (len(parts) == 1 and parts[0]["type"] == "text"):
            return _text_of(parts) or None
        return parts
    text = _strip_nul(str(content))
    return text or None


def _merge_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
    if isinstance(left, str) and isinstance(right, str):
        return f"{left}\n\n{right}"

    def parts(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        if isinstance(content, list):
            return [p for p in content if isinstance(p, dict)]
        return []

    merged = parts(left) + parts(right)
    if len(merged) == 1 and merged[0].get("type") == "text":
        return str(merged[0].get("text") or "")
    return merged


def normalize_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    """One system message first, then alternating user/assistant, ending on user.

    Drops empty content, merges consecutive same-role turns, and discards a
    trailing assistant turn. Mistral serving rejects a conversation that ends
    on an assistant message without prefix, and rejects empty assistant content.
    """
    system_bits: list[str] = []
    turns: list[dict[str, Any]] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            role = "user"
        content = _coerce_content(raw.get("content"), allow_parts=(role == "user"))
        if content is None:
            continue
        if role == "system":
            system_bits.append(content if isinstance(content, str) else _text_of(content))
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = _merge_content(turns[-1]["content"], content)
        else:
            turns.append({"role": role, "content": content})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    while turns and turns[-1]["role"] != "user":
        turns.pop()
    if not turns:
        raise ValueError("Mistral chat requires a user message")
    out: list[dict[str, Any]] = []
    system_text = "\n\n".join(bit for bit in system_bits if bit and bit.strip()).strip()
    if system_text:
        out.append({"role": "system", "content": system_text})
    out.extend(turns)
    return out


def _shrink_to_budget(messages: list[dict[str, Any]], budget_tokens: int) -> None:
    """Drop text from the front of the longest user turn until the estimate fits.

    The tail is the chef's question and the reply format, so it stays.
    """
    for _ in range(24):
        if estimate_tokens(messages) <= budget_tokens:
            return
        index = None
        longest = 0
        for i, message in enumerate(messages):
            if message.get("role") == "system":
                continue
            text = _text_of(message.get("content"))
            if len(text) > longest:
                longest = len(text)
                index = i
        if index is None or longest <= 400:
            return
        overflow = estimate_tokens(messages) - budget_tokens
        cut = max(1000, overflow * 4)
        content = messages[index]["content"]
        if isinstance(content, str):
            if len(content) <= cut + 200:
                messages[index]["content"] = content[-200:]
            else:
                messages[index]["content"] = "…\n" + content[-(len(content) - cut) :]
            continue
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = str(part.get("text") or "")
                    if len(text) > 400:
                        part["text"] = "…\n" + text[-max(200, len(text) - cut) :]
                        break
            else:
                return
            continue
        return


def _ensure_json_word(messages: list[dict[str, Any]]) -> None:
    blob = " ".join(_text_of(m.get("content")) for m in messages)
    if "json" in blob.casefold():
        return
    if messages and messages[0]["role"] == "system" and isinstance(messages[0]["content"], str):
        messages[0]["content"] = messages[0]["content"].rstrip() + "\n" + _JSON_NOTE
        return
    messages.insert(0, {"role": "system", "content": _JSON_NOTE})


def mistral_payload_issues(body: dict[str, Any]) -> list[str]:
    """Problems that make Mistral's chat endpoint return HTTP 400."""
    issues: list[str] = []
    model = body.get("model")
    if not isinstance(model, str) or not _MODEL_RE.match(model):
        issues.append("model")
        model_ok = False
    else:
        model_ok = True
    temp = body.get("temperature")
    if temp is not None:
        try:
            parsed = float(temp)
        except (TypeError, ValueError):
            issues.append("temperature")
        else:
            if parsed != parsed or parsed < TEMPERATURE_MIN or parsed > TEMPERATURE_MAX:
                issues.append("temperature")
    max_tokens = body.get("max_tokens")
    messages = body.get("messages")
    if max_tokens is not None and (
        isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1
    ):
        issues.append("max_tokens")
    elif model_ok and isinstance(max_tokens, int) and isinstance(messages, list):
        if max_tokens > completion_ceiling(model):
            issues.append("max_tokens_ceiling")
        prompt = estimate_tokens(messages)
        if prompt + max_tokens > context_limit(model):
            issues.append("context")
    if not isinstance(messages, list) or not messages:
        issues.append("messages")
        return issues
    roles: list[str] = []
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            issues.append(f"message_{i}")
            roles.append("")
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            issues.append(f"role_{i}")
        if content is None or content == "" or content == []:
            issues.append(f"empty_{i}")
        if role in {"system", "assistant"} and not isinstance(content, str):
            issues.append(f"content_type_{i}")
        if isinstance(content, str) and "\x00" in content:
            issues.append(f"nul_{i}")
        roles.append(role if isinstance(role, str) else "")
    if roles[0] not in {"system", "user"}:
        issues.append("start")
    system_at = [i for i, role in enumerate(roles) if role == "system"]
    if len(system_at) > 1 or (system_at and system_at[0] != 0):
        issues.append("system_once")
    conversation = [role for role in roles if role != "system"]
    if not conversation or conversation[-1] != "user":
        issues.append("last_user")
    if any(a == b for a, b in zip(conversation, conversation[1:])):
        issues.append("consecutive")
    response_format = body.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        blob = " ".join(
            _text_of(m.get("content")) for m in messages if isinstance(m, dict)
        )
        if "json" not in blob.casefold():
            issues.append("json_word")
    return issues


def redact_provider_text(text: str, api_key: str | None) -> str:
    cleaned = text or ""
    if api_key:
        cleaned = cleaned.replace(api_key, "[redacted]")
    cleaned = _BEARER_RE.sub("Bearer [redacted]", cleaned)
    cleaned = _AUTH_HEADER_RE.sub("authorization: [redacted]", cleaned)
    return cleaned[:1500]


def _provider_message(resp: httpx.Response, api_key: str | None) -> str:
    raw = resp.text or ""
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 — non-JSON error bodies are still logged
        data = None
    if isinstance(data, dict):
        message = data.get("message") or data.get("detail") or data.get("error") or raw
        if isinstance(message, dict):
            message = message.get("message") or str(message)
        bits = [str(message)]
        if data.get("type"):
            bits.append(f"type={data['type']}")
        if data.get("code") is not None:
            bits.append(f"code={data['code']}")
        if data.get("param"):
            bits.append(f"param={data['param']}")
        raw = " ".join(bits)
    if not raw.strip():
        raw = "(empty body)"
    return redact_provider_text(raw, api_key)


def _requested_max_tokens(explicit: int | None) -> int:
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            return COMPANION_MAX_TOKENS
    raw = os.environ.get("LLM_MAX_TOKENS") or str(INGEST_MAX_TOKENS)
    try:
        return int(raw)
    except ValueError:
        return INGEST_MAX_TOKENS


def build_chat_body(
    *,
    system: str,
    user_content: str | list[dict[str, Any]],
    model: str | None,
    messages: Sequence[Any] | None = None,
    max_tokens: int | None = None,
    temperature: Any = 0,
) -> dict[str, Any]:
    """Payload that satisfies Mistral chat-completions validation."""
    model_name = resolve_model(model)
    raw_messages: list[Any] = [{"role": "system", "content": system}]
    if messages is not None:
        raw_messages.extend(messages)
    # History and the new turn both stay. An empty user_content is only the
    # placeholder the caller uses when the turn is already in ``messages``.
    if messages is None or _content_present(user_content):
        raw_messages.append({"role": "user", "content": user_content})
    normalised = normalize_messages(raw_messages)
    requested = _requested_max_tokens(max_tokens)
    requested = max(1, min(requested, completion_ceiling(model_name)))
    context = context_limit(model_name)
    reserve = min(requested, max(256, context // 8))
    budget = max(256, context - reserve - 256)
    _shrink_to_budget(normalised, budget)
    _ensure_json_word(normalised)
    prompt = estimate_tokens(normalised)
    # Leave headroom. Mistral 400s when prompt tokens + max_tokens exceed context.
    room = context - prompt - 256
    if room < 1:
        _shrink_to_budget(normalised, max(1, context - 512))
        prompt = estimate_tokens(normalised)
        room = max(1, context - prompt - 32)
    capped = max(1, min(requested, room))
    body = {
        "model": model_name,
        "temperature": clamp_temperature(temperature),
        "max_tokens": capped,
        "response_format": {"type": "json_object"},
        "messages": normalised,
    }
    issues = mistral_payload_issues(body)
    if issues:
        raise ValueError(
            "Refusing to send an invalid Mistral payload: " + ", ".join(issues)
        )
    return body


def chat_completion_json(
    *,
    system: str,
    user_text: str,
    image_b64: str | None = None,
    image_media_type: str | None = None,
    images: Sequence[tuple[str, str | None]] | None = None,
    model: str | None = None,
    timeout: float = 180.0,
    messages: Sequence[Any] | None = None,
    max_tokens: int | None = None,
    temperature: Any = 0,
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

    model_name = resolve_model(model)
    # build_user_content turns a blank string into an ingest instruction.
    # A caller that already passed history must not get that sentence appended.
    if (
        messages is not None
        and not (user_text or "").strip()
        and not image_b64
        and not images
    ):
        user_content: str | list[dict[str, Any]] = ""
    else:
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

    body = build_chat_body(
        system=system,
        user_content=user_content,
        model=model_name,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(CHAT_URL, headers=headers, json=body)
        if resp.status_code >= 400:
            detail = _provider_message(resp, key)
            # Status and Mistral's message only. Never the key or this header.
            logger.warning(
                "Mistral chat completions failed: HTTP %s model=%s %s",
                resp.status_code,
                body.get("model"),
                detail,
            )
            raise MistralHTTPError(resp.status_code, detail)
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
