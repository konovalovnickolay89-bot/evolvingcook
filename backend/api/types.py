"""
Shared Pydantic/ninja field types.

B1: Decimal must serialise as JSON **number**, not string.
Pydantic v2 defaults Decimal → string in JSON Schema; we force number + float emit
while keeping Decimal in Python (no float arithmetic in domain code).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer, WithJsonSchema


def _to_decimal(v):
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not a quantity")
    if isinstance(v, (int, float, str)):
        return Decimal(str(v))
    raise TypeError(f"cannot coerce {type(v)!r} to Decimal")


def _dec_to_json(v: Decimal | None):
    """Emit JSON number (int when integral, else float). None stays null."""
    if v is None:
        return None
    if v == v.to_integral_value():
        return int(v)
    return float(v)


# Optional quantity/par fields on API responses and bodies.
DecimalQty = Annotated[
    Decimal | None,
    BeforeValidator(_to_decimal),
    PlainSerializer(_dec_to_json, return_type=int | float | None),
    WithJsonSchema({"type": ["number", "null"]}, mode="serialization"),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "number"},
                {"type": "string", "pattern": r"^-?\d+(\.\d+)?$"},
                {"type": "null"},
            ]
        },
        mode="validation",
    ),
    Field(default=None),
]

# Required quantity (no default) for waste / adjustment / transfer bodies.
DecimalQtyRequired = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(_dec_to_json, return_type=int | float),
    WithJsonSchema({"type": "number"}, mode="serialization"),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "number"},
                {"type": "string", "pattern": r"^-?\d+(\.\d+)?$"},
            ]
        },
        mode="validation",
    ),
]
