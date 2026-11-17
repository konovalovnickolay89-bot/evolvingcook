"""
Companion allergen refusal.

The model must not tell the chef a dish is free of an allergen or suitable
for an allergy. Absence is the kitchen allergen matrix on the recipe card,
or "allergens not recorded" when that card has no names.

The blocks marked phrase-lint:allow-refusal are the refusal definition and
the claim matcher. The phrase lint skips those blocks and only those blocks.
"""
from __future__ import annotations

import re

# phrase-lint:allow-refusal
BANNED_ALLERGEN_CLAIMS = (
    "allergen-free",
    "no allergens",
    "free from",
    "safe for",
)

ALLERGEN_SAFETY_REFUSAL = (
    "Allergen rule: never state that a dish is allergen-free, has no allergens, "
    "is free from an allergen, is free of an allergen, or is safe for any allergy "
    "or diet. You do not know that. Defer to the kitchen's allergen matrix on the "
    "recipe card. If the card lists no allergen names, say 'allergens not recorded' "
    "and stop. Do not guess absence from an ingredients list or from memory."
)

_CLAIM_RE = re.compile(
    r"allergen[\s-]*free|no\s+listed\s+allergens|no\s+allergens|"
    r"free\s+from|free\s+of|safe\s+for",
    re.IGNORECASE,
)
# phrase-lint:allow-refusal-end

ALLERGEN_DEFERENCE = (
    "I can't confirm an allergen is absent. "
    "Check the kitchen allergen matrix on the recipe card. "
    "Where that card lists nothing, allergens not recorded."
)

_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def guard_allergen_claims(text: str) -> str:
    """Drop sentences that claim an allergen is absent, then defer.

    Text with no such claim is returned unchanged. A reply that is only
    a claim becomes the deference line.
    """
    if not text or not _CLAIM_RE.search(text):
        return text
    parts = _SPLIT_RE.split(text.strip())
    kept = [part.strip() for part in parts if part.strip() and not _CLAIM_RE.search(part)]
    body = "\n".join(kept).strip()
    if body == ALLERGEN_DEFERENCE or ALLERGEN_DEFERENCE in body:
        return body
    if body:
        return f"{body}\n\n{ALLERGEN_DEFERENCE}"
    return ALLERGEN_DEFERENCE
