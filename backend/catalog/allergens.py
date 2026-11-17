"""
UK Food Standards Agency 14 allergens — the only recognised names.

Stored and returned in this order. Legacy spellings (the old chip set
"gluten" / "nuts", plus common kitchen aliases) map onto the canonical
name. Anything else is not an allergen name: writers that opt into
strict mode reject it, and other writers drop it.
"""
from __future__ import annotations

import re

UK14_ALLERGENS: tuple[str, ...] = (
    "celery",
    "cereals containing gluten",
    "crustaceans",
    "eggs",
    "fish",
    "lupin",
    "milk",
    "molluscs",
    "mustard",
    "tree nuts",
    "peanuts",
    "sesame",
    "soya",
    "sulphites",
)

# Folded alias → one or more canonical names. Canonical names are added
# in _aliases() so this table is only the legacy / kitchen spellings.
# "shellfish" covers both crustaceans and molluscs; recording both is the
# cautious reading when the source did not say which.
RAW_ALIASES: dict[str, tuple[str, ...]] = {
    "gluten": ("cereals containing gluten",),
    "cereals": ("cereals containing gluten",),
    "wheat": ("cereals containing gluten",),
    "barley": ("cereals containing gluten",),
    "rye": ("cereals containing gluten",),
    "oats": ("cereals containing gluten",),
    "crustacean": ("crustaceans",),
    "shellfish": ("crustaceans", "molluscs"),
    "egg": ("eggs",),
    "dairy": ("milk",),
    "lactose": ("milk",),
    "mollusc": ("molluscs",),
    "mollusk": ("molluscs",),
    "mollusks": ("molluscs",),
    "nuts": ("tree nuts",),
    "tree nut": ("tree nuts",),
    "peanut": ("peanuts",),
    "groundnut": ("peanuts",),
    "groundnuts": ("peanuts",),
    "sesame seed": ("sesame",),
    "sesame seeds": ("sesame",),
    "soy": ("soya",),
    "soybean": ("soya",),
    "soybeans": ("soya",),
    "soya bean": ("soya",),
    "soya beans": ("soya",),
    "soy bean": ("soya",),
    "soy beans": ("soya",),
    "sulphite": ("sulphites",),
    "sulfite": ("sulphites",),
    "sulfites": ("sulphites",),
    "sulphur dioxide": ("sulphites",),
    "sulfur dioxide": ("sulphites",),
    "e220": ("sulphites",),
    "lupine": ("lupin",),
    "lupins": ("lupin",),
}

_FOLD_RE = re.compile(r"\s+")


class UnknownAllergen(ValueError):
    def __init__(self, unknown: list[str]):
        self.unknown = list(unknown)
        super().__init__(", ".join(self.unknown))


def fold_allergen(value: str) -> str:
    text = value.strip().lower().replace("-", " ").replace("_", " ")
    text = text.replace(".", "")
    return _FOLD_RE.sub(" ", text).strip()


def _alias_table() -> dict[str, tuple[str, ...]]:
    table = {fold_allergen(key): names for key, names in RAW_ALIASES.items()}
    for name in UK14_ALLERGENS:
        table.setdefault(fold_allergen(name), (name,))
    return table


_ALIASES = _alias_table()
_ORDER = {name: index for index, name in enumerate(UK14_ALLERGENS)}


def normalize_allergens(values, *, strict: bool = False) -> list[str]:
    """Map to the UK 14, in canonical order, with duplicates removed.

    strict=True raises UnknownAllergen for any token that is not a
    recognised name or alias. strict=False drops those tokens.
    """
    if values is None:
        values = []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        if strict:
            raise UnknownAllergen(["invalid"])
        return []

    found: set[str] = set()
    unknown: list[str] = []
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        mapped = _ALIASES.get(fold_allergen(text))
        if not mapped:
            unknown.append(text)
            continue
        found.update(mapped)
    if strict and unknown:
        raise UnknownAllergen(unknown)
    return sorted(found, key=lambda name: _ORDER[name])
