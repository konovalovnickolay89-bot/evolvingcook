# Decision D17 — Recipe cards

| Field | Value |
|-------|--------|
| What | Chef-owned recipe cards: production spec + method in one. Companion drafts; the chef edits, saves, scales |
| Model | `catalog.Recipe` (migration 0003): name, section, base_covers, yield, `ingredients` `[{name, qty, unit, note}]`, `method` `[step]`, `allergens` (UK-14 names), notes, source chef/companion |
| Scaling | Client-side display only: factor = covers / base_covers. Stored quantities never change |
| Draft | `POST /recipes/draft {prompt, covers}` → companion (D16 gateway, JSON mode) returns a card for editing — **never saves**. MEP-first method, arithmetic shown, UK-14 allergens |
| CRUD | Bearer `/api/v1/recipes`: GET list (`?q=` name search) · POST · GET/PATCH/DELETE `/{id}`. `/draft` registered before `/{recipe_id}` (ninja shadowing rule) |
| Contract | **0.1.20** |

Also in 0.1.20: pending assist proposals auto-expire on list — `line`-target
("today only") after 3 days, anything after 30 — to `rejected` /
`reject_reason "expired"` so the Done tab keeps the audit trail.
