# Decision D15 — Section modes + proposal targets v2

| Field | Value |
|-------|--------|
| Decision | Chef chooses section mode once (counts vs ordering); guided prep for banquet*; proposal targets expand beyond note tiers |
| Phase | Cross-cut on boards + assist (contract **0.1.18**) |
| FE | Grok — Section Modes / Assist Inbox mocks; this doc is backend SoT |
| Supersedes | nothing (extends D11/D14) |

## 1. Section modes

Every `ServiceSectionCode` has one durable `SectionSetting` row:

| Field | Type | Notes |
|-------|------|--------|
| `section` | enum string, unique | six locked ids |
| `mode` | `counts` \| `ordering` \| **null** | null until chef chooses |
| `guided` | bool | default **true** for `banqueting` / `banquet_buffet`, else false |
| `decided_at` | datetime \| null | set when mode first chosen or changed |

**Never silently default `mode`.** Assist only recommends (surfaced as `mode_recommendation` on the board). FE shows the chef-speak prompt when `mode_prompt_needed` (mode is null).

### Recommendations (preselect only)

| section | recommend mode | guided default |
|---------|----------------|----------------|
| skybar | ordering | false |
| a_la_carte | ordering | false |
| canteen | counts | false |
| breakfast_buffet | counts | false |
| banqueting | counts | **true** |
| banquet_buffet | counts | **true** |

### API

| Method | Path | Body / notes |
|--------|------|----------------|
| GET | `/api/v1/sections/settings` | all six rows (+ recommendations) |
| PATCH | `/api/v1/sections/{section}/settings` | `{ "mode": "counts"\|"ordering", "guided"?: bool }` upsert |

### Board payload (one request)

On `BoardOut` / GET section board:

| Field | Type | Meaning |
|-------|------|---------|
| `section_mode` | string\|null | current mode |
| `mode_prompt_needed` | bool | `section_mode is null` |
| `guided` | bool | guided prep flag |
| `mode_recommendation` | string | Assist guess (`counts`\|`ordering`) |
| `prep_plan` | object\|null | guided only — see §3 |

## 2. Mode gates (jobs + proposals)

| Mode | Allowed assist work |
|------|---------------------|
| **ordering** | Menu-completeness (`component_fill` / incomplete recipes); order proposals (`order_packs` shortfall). **No** qty/par/morning planned_qty drafts. |
| **counts** | Full pipeline: qty proposals (`planned_qty`), walk→order, note parse, day-open drafts. |
| **counts + guided** | Day-open / on-demand **prep plan** (`prep_step` proposals), MEP-ordered. |
| **mode null** | No automated qty or prep drafts until chef chooses. Note parse still allowed (reversible). |

Enqueue paths must call `assert_job_allowed_for_section(kind, section)` (or equivalent). Clients posting disallowed jobs get **400** `mode_gate`.

## 3. Guided prep plan

When `guided` and `mode=counts`, Assist (or deterministic scaffold) emits ordered steps:

```json
{
  "target": "prep_step",
  "title": "string",
  "phase": "mep" | "day_of",
  "order_index": 0,
  "clock_time": "HH:MM" | null,
  "qty": number | null,
  "unit": "g|ml|ea|…" | null,
  "working": "arithmetic / why as text — REQUIRED",
  "watch_out": "string" | null,
  "service_date": "YYYY-MM-DD",
  "section": "banqueting"
}
```

Rules:

- **MEP** steps: `order_index` set, **`clock_time` null** (longest lead first).
- **day_of** steps: `clock_time` backwards-planned from service; still carry `order_index` for stable sort.
- Every step **must** include non-empty `working` — reject/regenerate otherwise (B3).
- Plan lands as **pending** `AssistProposal` rows (`kind=prep_plan`); accept per step (dashed → solid on FE).
- Accepted steps accumulate on the board under `prep_plan.steps` (pending + accepted).

Mise-en-place first is the teaching principle (commis → senior): order is the lesson.

## 4. Proposal targets v2

In addition to D14 note tiers (`line` | `template` | `item`), proposals may declare:

| target | Meaning | Accept writes |
|--------|---------|----------------|
| `planned_qty` | set/adjust line planned quantity | `ProductionLine.planned_qty` (+ event) |
| `order_packs` | add packs to today's order / PO draft | purchasing path (existing order proposal hooks) |
| `new_line` | add a board line | `ProductionLine` create |
| `component_fill` | fix dish→ingredient list | `LineComponent` / template components |
| `prep_step` | one guided plan step | accept into section prep plan snapshot |

Note-tier targets remain for `parse_note`. Mixed bodies are invalid — one primary `target` per proposal.

`proposal.audit` (D14 BE-2) still holds pipeline coercion notes. Do not stuff audit into `rationale`.

## 5. LLM / prompt (B3)

- Context packs include **candidate catalogue items** (id + name + unit) for the section — **never invent names**.
- Stamp on every proposal: `model`, `prompt_version` (string, e.g. `section-modes-v1`).
- Prep steps without `working` → not accept-able (`parse_error` or gate on accept).

## 6. Non-negotiables carried forward

- Covers never required outside banquet* scaling paths.
- Par ≠ f(covers).
- Skip ≠ 0.
- LLM → AssistProposal only until accept.
- 401 never drops client data.

## 7. Contract

Bump **APP_VERSION / CONTRACT_VERSION → 0.1.18**, regenerate `docs/openapi.json`.


## 8. Depth increment (0.1.18)

- Accept handlers for `planned_qty`, `component_fill`, `order_packs`, `new_line`
- Accept may send `{ "proposal": {…} }` overlay (FE Adjust / fill components)
- Ordering board: component `stock_status` dots + line `to_order_count` + `order_assist` card
- Deterministic `menu_completeness` + `order_suggest` scaffolds on ordering board fetch
- `build_prep_plan_llm_prompt` ready for A2A rewrite (scaffold still default)


## 9. Depth 0.1.18

- **prep_plan A2A**: scaffold first; if A2A configured, queue LLM rewrite → replaces pending steps (`steps[]` with required `working`)
- **qty_draft / morning_qty**: MEP-ordered planned_qty proposals on counts boards; optional `use_llm`
- **Covers change**: pending prep steps re-scaffolded with new working maths (accepted kept)
- **Stock dots**: par-aware (`par_qty` on components) when ParLevel exists
- **Walk shortfall**: submit + `/order-proposal` also create/merge `order_suggest` AssistProposal (`assist_proposal_id`)


## 10. Optional FE polish 0.1.18

- Area-scoped stock: `stock_by_area[]`, `stock_primary_qty`, `primary_area_*` on components
- Board `qty_draft` strip separate from `prep_plan` (morning_qty clocks when counts && !guided)
- FE handoff: `docs/FE-SECTION-MODES.md` + `docs/FE-OPENAPI-SLICE.json`
