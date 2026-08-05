# Decision D13 — Purchasing scope + variance language

| Field | Value |
|-------|--------|
| Decision | POs are **scoped**: `replenishment` (default) vs `event`. Only replenishment counts as `on_order` for shortfall. Variance is **unexplained** gap, never auto-corrects |
| Touches | Phase 2 order proposal math; Phase 3 variance wording/behaviour |
| Ambition | **No global inventory** — walks, pars, proposals scoped to Mykola’s operation only |

---

## 1. PurchaseOrder.scope

| Value | Meaning |
|-------|---------|
| `replenishment` | **Default.** Standing stock top-up for the operation. |
| `event` | Banquet / BEO / one-off event buy. **Must not** reduce shortfall for replenishment proposals. |

- Field: `CharField` with choices; default `replenishment`.
- Admin + API create/read expose scope.
- Existing rows migrate to `replenishment`.

## 2. Order proposal — `on_order`

When computing:

```text
shortfall = max(0, par − counted − on_order)
```

**`on_order`** = sum of open replenishment PO quantities for that (item, supplier) [and area rules as today], statuses that mean “still coming” (e.g. draft/sent/confirmed — match current Phase 2 open-set; document the set).

**Exclude** all POs with `scope=event` from `on_order`, regardless of status.

Event POs remain first-class for send/receive/admin; they simply never suppress replenishment shortfall.

## 3. Phase 3 variance (when ledger ships / if already partial)

| Rule | |
|------|--|
| Label | Counted vs theoretical gap = **`unexplained`** — **never** “error” |
| Why | Shared areas: other sections’ event deliveries and consumption the app does not fully see |
| Noise floor | Per-item (config or field); below floor → treat as zero unexplained / do not flag |
| Auto-correct | **Never** auto-adjust pars or balances from variance |
| Corrections | Compensating stock movements only (append-only ledger), human-driven |

If Phase 3 is not built yet: lock the language and field names in this doc + any stub fields; implement math with Phase 3 card. **Still ship §1–2 now** if Phase 2 path exists.

## 4. No global-inventory ambitions

- Walks, pars, proposals, balances: **this operation only** (Mykola / Hilton kitchen ops as modelled).
- Do not design multi-outlet enterprise inventory, hotel-wide SoT, or “true” theoretical that assumes full visibility of every movement.
- Event scope exists precisely because the app will not see everything in shared fridges.

## 5. Contract

- If schemas change (PO scope on API): bump `CONTRACT_VERSION` / `APP_VERSION`, regenerate `docs/openapi.json`, report delta.
- Order-proposal response should remain honest: breakdown may show `on_order` that excludes event (document in OpenAPI description).

## 6. Non-goals

- FE
- Changing house_made / D12
- Auto-accept of anything
- Inventing event↔BEO linkage beyond optional notes/FK later

## 7. Gate evidence

1. Migration: existing POs → `replenishment`; new PO can be `event`
2. Two open POs same item (one replenishment, one event): order proposal `on_order` reflects **replenishment only**; shortfall not reduced by event qty
3. openapi shows `scope` if exposed
4. Report notes variance language lock for Phase 3 (and implements if Phase 3 already present)
