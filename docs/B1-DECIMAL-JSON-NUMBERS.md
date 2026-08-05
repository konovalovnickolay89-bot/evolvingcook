# B1 fix — Decimal JSON numbers (contract 0.1.6)

## Done
- Added `api/types.py` → `DecimalQty` (Pydantic v2 PlainSerializer → JSON number; OpenAPI `type: number|null`)
- Board schemas use `DecimalQty` for `proposed_qty`, `planned_qty`, `actual_qty`, `par_level`, component `planned_qty`
- Regenerated `docs/openapi.json`
- Bumped `APP_VERSION` / `CONTRACT_VERSION` → **0.1.6**
- Unit restarted

## Contract change
endpoints unchanged; schema types for quantity fields: **string → number**

## Evidence (live board response body)
With temporary non-null decimals on one line, then cleared:
```json
"proposed_qty": 6,
"planned_qty": 6.5,
"actual_qty": null,
"par_level": 12
```
OpenAPI `ProductionLineOut`:
```json
"proposed_qty": {"type": ["number", "null"]}
```

## Gate status
green for B1
