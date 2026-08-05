# Evolving Cook FE contract — Section Modes + Assist (0.1.18)

**Paste this whole file to Grok FE.** Backend SoT: live `https://api.apidiscoverysolution.uk` · monorepo `backend/` on GitHub `konovalovnickolay89-bot/evolvingcook`.

| | |
|--|--|
| Contract | **0.1.18** (`GET /api/v1/version`) |
| Auth | Bearer from `POST /api/v1/auth/login` — **401 → re-auth + retry, never drop local state** |
| CORS | `https://evolvingcook.grok.me` (+ grok-sandbox regex) |
| Style | tokens.css only, no Tailwind; touch ≥44px; text ≥12px; **dashed = pending proposal, solid = decided** |

OpenAPI slice: `docs/FE-OPENAPI-SLICE.json` (regenerated with deploy).

---

## 1. Section mode (F1) — do first

### Endpoints

```
GET  /api/v1/sections/settings
PATCH /api/v1/sections/{section}/settings
Body: { "mode": "counts" | "ordering", "guided"?: boolean }
```

### On every board GET (one request — no extra hop)

```jsonc
{
  "section_mode": null,              // "counts" | "ordering" | null
  "mode_prompt_needed": true,      // true until chef chooses
  "guided": false,                   // banqueting* default true
  "mode_recommendation": "ordering", // Assist guess only — never auto-apply
  "prep_plan": null,
  "qty_draft": null,
  "order_assist": null,
  "lines": [ /* ... */ ]
}
```

### Chef copy (exact)

> **On this board, do the numbers matter — or is it really about what to order?**
>
> - **Counts matter** → quantities tracked, three-number rows, Assist drafts prep/order maths  
> - **Just ordering** → clean menu reference (dish → ingredients), Assist only flags what to order  

Assist hint (dashed):  
`Assist's guess for {section}: {mode_recommendation} — your call.`

On pick → `PATCH` → receipt row + mode pill (Ordering = cyan, Counts = yellow).  
Line: *Change any time in section settings.*

**Never silently default mode.** Until chosen, show prompt; note-parse still OK.

| section | recommend |
|---------|-----------|
| skybar, a_la_carte | ordering |
| canteen, breakfast_buffet | counts |
| banqueting, banquet_buffet | counts + guided |

---

## 2. Ordering mode board (F2)

When `section_mode === "ordering"`:

- **Do not render** three-number qty / bars / count chips (even if API still sends qty fields).
- Row = dish: `name` + `order_summary_label` (e.g. `6 items · 2 to order`).
- Expand → `components[]`:

```ts
type Comp = {
  id: number
  name: string
  item_id?: number
  supplier_code?: string
  stock_status: "in_stock" | "running_low" | "on_order" | "unknown"
  stock_status_text: string
  stock_qty?: number          // house total
  stock_primary_qty?: number  // default_area qty (par compare)
  primary_area_name?: string
  par_qty?: number
  stock_by_area?: { area_id: number; area_name: string; qty: number }[]
  on_order_qty?: number
}
```

Dots: green / yellow / orange / grey from `stock_status`.  
Expand areas via `stock_by_area` if chef wants where stock sits.

### Top card — `order_assist`

```jsonc
{
  "proposal_id": 12,
  "kind": "order_suggest",
  "target": "order_packs",
  "rationale": "…",
  "lines": [{ "item_id", "name", "packs", "why" }],
  "accept_able": true
}
```

Buttons: **Add to order** →  
`POST /api/v1/assist/proposals/{id}/accept`  
**Pass** →  
`POST /api/v1/assist/proposals/{id}/reject` `{ "reason": "" }` → stores `"other"`.

Walk path also feeds this card; `/walks/{id}/order-proposal` returns `assist_proposal_id`.

---

## 3. Counts mode (F3 + qty strip)

### Always (`section_mode === "counts"`)

Keep three-number rows (`proposed_qty` / `planned_qty` / `actual_qty`). Check lines: no qty UI.

### `qty_draft` — separate strip (not prep_plan)

```jsonc
"qty_draft": {
  "section": "canteen",
  "service_date": "2026-08-05",
  "items": [{
    "proposal_id": 1,
    "kind": "qty_draft" | "morning_qty",
    "status": "pending" | "accepted",
    "accept_able": true,
    "line_id": 9,
    "line_name": "Staff stew",
    "planned_qty": 25,
    "unit": "ea",
    "working": "board proposed/planned = 25",
    "phase": "mep" | "day_of",
    "order_index": 0,
    "clock_time": "11:30" | null,   // morning_qty day_of only
    "target": "planned_qty"
  }]
}
```

- **guided counts** (banquet*): kind `qty_draft` (no clocks required).  
- **non-guided counts**: kind `morning_qty` — day_of items get **clock_time** backwards from service.  
- MEP first in list (`phase`).  
- Accept: `POST …/accept` or overlay adjust:

```http
POST /api/v1/assist/proposals/{id}/accept
{ "proposal": { "planned_qty": 30, "working": "chef adjusted" } }
```

### `prep_plan` — guided only (`guided && counts`)

```jsonc
"prep_plan": {
  "steps": [{
    "proposal_id": 3,
    "status": "pending" | "accepted",
    "accept_able": true,
    "title": "Reduce jus",
    "phase": "mep" | "day_of",
    "order_index": 0,
    "clock_time": null,           // null for MEP
    "qty": 4,
    "unit": "L",
    "working": "REQUIRED teaching line",
    "watch_out": "…" | null,
    "target": "prep_step"
  }]
}
```

Groups:

1. **Mise en place — day before** — *No clock here — work the order. Longest lead first.*  
2. **Day of — finish & hold (service HH:MM)** — *Clock matters — times backwards-planned from service.*

Buttons per pending step: **Looks right** (accept) / **Adjust** (overlay then accept).  
Covers change → pending steps re-scaffold (accepted stay solid).

---

## 4. Proposal targets & accept/reject

| target | Accept writes |
|--------|----------------|
| `line` / `template` / `item` | notes / house_made / components (D14) |
| `planned_qty` | line planned qty |
| `component_fill` | dish ingredient list |
| `order_packs` | draft PO packs |
| `new_line` | add board line |
| `prep_step` | guided step accept |

```http
POST /api/v1/assist/proposals/{id}/accept
Body optional: { "proposal": { …partial overlay… } }

POST /api/v1/assist/proposals/{id}/reject
{ "reason": "wrong tier" }   // empty → "other"
```

Response `ProposalOut` top-level: `target`, `target_confidence`, `accept_able`, `parse_error`, `rationale`.  
Pipeline notes live in `proposal.audit[]` — **do not string-split rationale**.

Only accept when `accept_able === true`.

---

## 5. Mode gates (FE should not offer)

| Mode | Jobs allowed |
|------|----------------|
| unset | parse_note only |
| ordering | parse_note, menu_completeness, order_suggest |
| counts | + qty_draft, morning_qty, prep_plan (if guided) |

Disallowed enqueue → `400` `mode_gate`.

Note-save auto-enqueues parse_note when text long enough; FE should **not** double-file for ordinary notes.

---

## 6. Screen map → API

| Screen | Gate | Primary fields |
|--------|------|----------------|
| Mode prompt | `mode_prompt_needed` | PATCH settings |
| Skybar / ALC ordering | `section_mode==ordering` | lines + components stock + order_assist |
| Canteen counts | counts, !guided | three-number + qty_draft (morning clocks) |
| Banqueting guided | counts + guided | function sheet (covers/beo) + prep_plan + qty_draft |

---

## 7. Hard rules (non-negotiable)

1. Covers never required to open a board (except banquet scale path).  
2. Skip ≠ 0.  
3. 401 never drops client data.  
4. Dashed pending / solid decided.  
5. Check-mode lines never show quantities.  
6. Ordering mode never shows count UI.  
7. Don’t invent catalogue names — only API candidates / board data.

---

## 8. Quick smoke

```bash
curl -sS https://api.apidiscoverysolution.uk/api/v1/version
# login → Bearer
curl -sS -H "Authorization: Bearer $T" \
  https://api.apidiscoverysolution.uk/api/v1/sections/settings
curl -sS -H "Authorization: Bearer $T" \
  https://api.apidiscoverysolution.uk/api/v1/boards/days/YYYY-MM-DD/sections/skybar
```

Build order: **F1 mode prompt → F2 ordering (skybar/ALC) → F3 banqueting guided → counts qty_draft strip.**
