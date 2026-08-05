# Decision D12 — Notes + house-made (recipe-lite)

| Field | Value |
|-------|--------|
| Decision | ProductionLine + Item **notes** in board payload; **house_made** items with **ItemComponent** recipe-lite |
| Phase | Cross-cut after Phase 2; B15 explosion lands in Phase 5. Does **not** replace Phase 3 ledger |
| Ordering | **P5 amendment (2026-08-04):** house_made **parents skipped** in PO shortfall (you make them; don't buy the parent). Escape: untick `house_made` in admin any week you would rather buy. Components still order when on walks with pars. |
| Assist | A2A task type **`parse_note`** → `AssistProposal` only (D11 accept flow) |

---

## 1. Notes

| Target | Behaviour |
|--------|-----------|
| `ProductionLine` | set/clear short free-text note |
| `Item` | set/clear short free-text note |

- Endpoints: set + clear (or PATCH with null = clear) under `/api/v1/`.
- **Board payload includes notes** — no extra round-trip for FE.
- Keep notes short (reasonable `max_length`, e.g. 500); not a journal.

## 2. House-made + components

| Model | Fields |
|-------|--------|
| `Item.house_made` | `BooleanField` default `False` |
| `ItemComponent` | `parent` → Item (FK), `component` → Item (FK), `qty` (nullable Decimal, rough), `unit` (nullable Char; prefer base unit of component when set), `sort_order`, optional `notes` |

Rules:

- Recipe-lite only — **not** full B15 explosion yet (depth, cycles, CTEs = Phase 5).
- **Admin:** TabularInline components on Item change page.
- House-made is a **flag**, not a replacement for bought supply: keep existing `SupplierItem` rows.
- Self-reference / cycles: reject obvious parent==component; deep cycle detection deferred to Phase 5.
- Quantities may be **unverified** — seed/examples flagged as such (notes or `verified=False` if you add a field; otherwise `Item.notes` / component notes say `unverified`).

## 3. Seed (two real examples)

Both with **unverified** quantities:

1. **Asian slaw** (`house_made=True`) components: red cabbage, white cabbage, carrot, savoy cabbage, onion  
2. **Aioli** (`house_made=True`, house-prepared)

- Create/link component `Item` rows if missing (active, base_unit sensible).
- **Do not** remove or replace their bought `SupplierItem` links if any exist.
- Prefer management command or data migration under `catalog/` so re-run is safe (idempotent on codes/names).

## 4. A2A task type `parse_note`

Add to contract file (create if missing):

`docs/contracts/a2a-tasks.md` (or `docs/a2a-tasks.md` — one path; prefer `docs/contracts/a2a-tasks.md`)

| | |
|--|--|
| `kind` | `parse_note` |
| Input | free text + line and/or item context (ids + names) |
| Output | proposal JSON: `note` text, optional `components[]`, optional `house_made` |
| Landing | `AssistProposal` row only; standard accept handlers apply domain writes |
| Transport | D11 (Hermes A2A + signed push) when Phase 5 assist ships; **document schema now** even if runtime path is stub/admin-only |

Do **not** auto-apply parse_note output to Item/ProductionLine without accept.

## 5. Ordering

- Phase 2 (original): order proposal did not special-case `house_made`.
- **Phase 5 amendment (locked 2026-08-04, Mykola):** skip **house_made parent** items in PO shortfall generation — kitchen makes the parent; do not propose buying it. Components remain orderable when they appear on walks with pars.
- Escape hatch: admin untick `Item.house_made` any week you would rather buy the finished item (Brakes fallback etc.).
- B15 `explode_item` is separate (`POST /api/v1/assist/explode`); demand→PO explosion of components is optional follow-on, not required for this lock.

## 6. Contract / openapi

- Bump `APP_VERSION` / `CONTRACT_VERSION` (from current **0.1.7**).
- Regenerate `docs/openapi.json`.
- Report contract delta in gate/report.

## 7. Non-goals

- Stock ledger (Phase 3)
- Full recipe explosion B15
- D11 Hermes enable / live A2A round-trip (schema only unless already trivial)
- (superseded) Changing PO math for house-made — now allowed as P5 amendment §5
- FE

## 8. Gate evidence

- migrate + unit healthy; version bump visible
- set/clear note on ProductionLine + Item; board GET shows note inline
- Item admin shows component inline; two seeds present with house_made + components, unverified qty noted
- openapi lists new endpoints; Decimal still JSON numbers where applicable
- order-proposal smoke: house_made **parents** omitted from shortfall (P5 amendment §5); components still appear when walked
