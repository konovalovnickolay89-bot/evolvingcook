# Decision D14 — NOTE→ASSIST v2 (three note tiers + auto parse)

| Field | Value |
|-------|--------|
| Decision | Note-save auto-enqueues `parse_note`; three storage tiers; board carries `template_notes` + `pending_proposal` |
| Phase | Cross-cut on Phase 5 assist (contract **0.1.13**) |
| FE | Grok — separate card (chips, inline cards); this doc is backend SoT |

## Tiers

| target | Storage | Lifetime |
|--------|---------|----------|
| `line` | `ProductionLine.notes` | Dies with the service day |
| `template` | `DishTemplate.notes` | Reappears as `template_notes` on every future board line for that dish |
| `item` | `Item.notes` / `house_made` / `ItemComponent` | Permanent catalogue |

`house_made` and `components` are **item-tier only**. Accept coerces template+those facts → item with low confidence rationale.

## Intake

- `notes` alias of `text`; empty → 400 `empty_text` on `/assist/jobs`
- Note-save `PATCH /boards/lines/{id}/notes` always succeeds; auto-enqueues when len≥`ASSIST_NOTE_MIN_CHARS` (default 15)
- FE must **not** file note-parse jobs for ordinary note UX
- Dedupe identical text per line (`ASSIST_NOTE_DEDUPE_SECONDS`); rate limit per line/hour

## Outcomes

| Result | Behaviour |
|--------|-----------|
| Structure found | `AssistProposal` pending; `target` + `target_confidence` required |
| Nothing structured | Job succeeded; **no** proposal row |
| Parse failure | Proposal with `parse_error`; inbox-only; **not** accept-able |

GetTask recovery runs when push body fails JSON parse.

## Confidence

When unsure, model sets `target_confidence: "low"` + one-line `rationale`. Prefer **line** over **item** when unsure (reversible).

## Board payload

Per line:

- `notes` — day tier
- `template_notes` — from `DishTemplate.notes`
- `pending_proposal` — latest pending parse_note for that `line_id` or null
