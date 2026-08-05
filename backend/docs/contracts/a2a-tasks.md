# A2A task types — Evolving Cook assist contract

Schema-only document for Hermes A2A task kinds that land as `AssistProposal`
rows. **Runtime webhook / Hermes enable is out of scope for D12** — this file
defines the contract so Phase 5 can implement without inventing shapes.

Authority: `docs/D11-HERMES-A2A-ASSIST.md`, `docs/D12-NOTES-HOUSE-MADE.md`.

Non-negotiables:

- Webhook / agent completion **never** writes domain state directly.
- Output always lands as **AssistProposal** (`kind`, `context`, `proposal`, …).
- Domain writes happen only via **accept** handlers after human review.
- UI / kitchen ops must work if assist is down.

---

## `parse_note`

| Field | Value |
|-------|--------|
| `kind` | `parse_note` |
| Purpose | Turn free-text kitchen note into a structured proposal (note text, optional recipe-lite components, optional house_made flag) |
| Transport | D11 Hermes A2A + signed push (when Phase 5 ships); document-only until then |
| Landing | `AssistProposal` row only — standard accept handlers apply domain writes |
| Auto-apply | **Never** without accept |

### Input (`context` JSON)

IDs + display names only — no bulk catalogue dump.

```json
{
  "text": "string — free text from chef / board note",
  "line_id": "int | null — ProductionLine id when note is line-scoped",
  "line_name": "string | null",
  "item_id": "int | null — Item id when note is item-scoped",
  "item_name": "string | null",
  "service_date": "YYYY-MM-DD | null",
  "section": "string | null — ServiceSectionCode value"
}
```

Rules:

- At least one of `text` non-empty, or structured ids, should be present.
- Prefer ids over names when both are known.
- Do not require covers / waves / stock balances.

### Output (`proposal` JSON)

Agent text body = **strict JSON only** (no markdown fences).

```json
{
  "note": "string | null — cleaned short note (max 500) to apply on accept",
  "target": "line | item | both — where accept should write the note",
  "house_made": "bool | null — set Item.house_made on accept when target includes item",
  "components": [
    {
      "name": "string — constituent item name (resolve/create on accept)",
      "item_id": "int | null — preferred if known",
      "qty": "number | null — rough; B1 JSON number, not string",
      "unit": "string | null — prefer component base unit",
      "notes": "string | null — e.g. unverified",
      "sort_order": "int | null"
    }
  ],
  "rationale": "string | null — short why (also may live on AssistProposal.rationale)",
  "confidence": "number | null — 0..1 optional"
}
```

Rules:

- `components` may be `[]` or omitted when the note is text-only.
- `qty` uses JSON **numbers** (B1), never quoted decimals.
- Self-parent components (`parent == component`) must not be proposed; deep cycles deferred to Phase 5.
- House-made is a **flag**, not a replacement for bought `SupplierItem` rows.
- Accept handlers (Phase 5) own resolution of names → Item FKs and write
  `ProductionLine.notes` / `Item.notes` / `Item.house_made` / `ItemComponent`.

### Accept behaviour (document; not implemented on D12)

On `AssistProposal` accept for `kind=parse_note`:

1. If `target` includes `line` and `context.line_id`: set/clear line notes from `proposal.note`.
2. If `target` includes `item` and `context.item_id` (or resolved name): set/clear item notes; apply `house_made` when non-null.
3. Upsert `ItemComponent` rows for `components[]` when house-made / recipe-lite is intended; never delete existing `SupplierItem`.
4. Reject path: no domain writes; store `reject_reason`.

### Size / degradation

- Keep proposal JSON small (fit push budget ~2k when possible).
- If Hermes down / timeout / bad JSON → job failed or proposal with parse error; **boards and ordering keep working**.

### Out of scope here

- Live A2A round-trip
- Stock ledger, banquet covers, full B15 explosion
- Order-proposal special-casing of `house_made` (Phase 5 consumes components)
