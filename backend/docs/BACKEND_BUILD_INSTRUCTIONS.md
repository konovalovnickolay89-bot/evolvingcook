# Evolving Cook — backend build instructions (single file, complete)

You are the backend build agent on a Debian box. This file is your entire brief — everything is decided; nothing else needs reading. **You execute; you do not decide.** If anything is ambiguous, blocked, or seems wrong: stop, state the question in your report, and wait. Never work around a non-negotiable.

Report after each numbered block, in this shape (it gets relayed to the orchestrator for gating):

```
## Phase / block
## Done
## Contract change   none | endpoints + regenerated openapi.json
## Gate status       green | blocked | needs decision
## Evidence          command output / test run — never a verbal "done"
## Blocked on
## Next
```

---

## 1. Context

Sole user: Mykola — chef (production, prep, ordering) at Hilton London Wembley. Phone-first, one-handed, sometimes wet hands. He maintains this alone for years: **boring and legible beats clever.** The bar: on a Tuesday, opening the app must beat the notes app and the printed sheet.

Daily core functions, in his words: **mise en place readiness, ordering, post-service par/stock levels.** Service running (e.g. breakfast buffet replenishment) is part of the boards and differs per section.

v1 died because one day-level covers dial (default 120) scaled every section's quantities and derived par from covers. He went back to paper. Correctly.

---

## 2. Non-negotiables (violating any of these is project failure)

1. **Six independent per-section cover counts**, each with a labelled source. No day-level covers dial, no "set all sections" control — not as API convenience, UI shortcut, or default.
2. **Par is never a function of covers.** Par = throughput + storage + delivery cadence. Own table: item + area + weekday.
3. **Every quantity is three columns:** `proposed_*` (system, always visible, never binding) / `planned_*` (Mykola's — the only number treated as real) / `actual_*` (reality). Every displayed number must carry its breakdown so the UI can show where it came from.
4. **Base units are `g`, `ml`, `ea` — only.** Everything else (case, tray, bottle, portion) is a `UnitConversion` row. Conversion at entry.
5. **Stock ledger is append-only.** Corrections are compensating entries. Balances written only in the same transaction as their movement.
6. **Partial catalogue is a normal state.** Screens/endpoints degrade per-item, never per-screen. An item with no supplier, no par, no price must flow through everything cleanly.
7. **A skipped count is not a zero.** Blank = skipped; typed 0 = empty shelf. Separate fields, never coerced.
8. **Postgres is the source of truth.** No derived state elsewhere.
9. **The LLM never writes domain state.** It writes a proposal row; an accept handler performs a normal validated write.
10. **Never invent catalogue data.** Placeholders only when visibly labelled unverified.

---

## 3. Locked decisions

| Decision | Value |
|----------|-------|
| Serving | **Split origins.** Frontend hosted on grok.com (xAI); you serve NO frontend. No BFF — browser calls this API directly |
| API hostname | `https://api.apidiscoverysolution.uk` (Cloudflare tunnel → `127.0.0.1:8000`) |
| Auth | `/admin/*` = Cloudflare Access (path-scoped). `/api/v1/*` = Bearer token (see §6) |
| CORS | Exact env-driven allowlist. Preview: regex `^https://.*\.grok-sandbox\.com$`. Published origin added later — **never hardcode it** |
| Sections | `breakfast_buffet, a_la_carte, banquet_buffet, banqueting, canteen, skybar`. Executive lounge = outlet of ALC (`supports_lounge`), not a peer. No hot veg section. Skybar food only |
| Storage areas (seed) | main freezer · veg fridge · dairy+breakfast fridge · breakfast freezer · dry store · fruit+pastry fridge · pastry freezer · à la carte fridge · **meat fridge** (added). `walk_order` NOT yet known — leave orderable, do not guess |
| Items | **Global, never section-scoped.** Same item lives in multiple areas simultaneously (normal case). Preps are made once, consumed by many sections |
| Priority | **Items before supplier data** (name+unit is enough to exist); supplier/code/pack second (only ordering blocks on them); prices last, nullable |
| Covers | **Scaling input for banqueting/banquet_buffet only** (BEO-driven). Optional and informational everywhere else — nothing ever blocks on a cover count. When used: per-section, labelled source, no global dial |
| Timezone | Europe/London. Service dates are `DateField`, never datetime |
| Phase order | 0 → 1 → **1.5 (MEP/service boards)** → 2 (walk/ordering) → 3 (ledger) → 4 (full planner) → 5 (LLM loop) |

---

## 4. Stack (exactly this; nothing else)

Python 3.12+ · **Django 5.2 LTS** · **PostgreSQL 15+** (verify; decides §8 B11) · `psycopg[binary]` · **django-ninja** (Pydantic schemas → auto OpenAPI = the contract) · `django-cors-headers` · `django-q2` ORM broker (LLM jobs only) · `whitenoise` (admin static only) · `gunicorn` bound `127.0.0.1:8000` · `uv` (fallback pip) · `pytest-django` + `factory-boy` + `hypothesis` (property tests for all arithmetic) · **Mistral** chat completions via `httpx` (D10; default model `mistral-medium-latest`).

**Not used:** DRF, Celery, Redis, Docker, nginx, Node.

Apps: `config core catalog walks purchasing inventory planning assist api`. Business rules in each app's `services.py`; models validate; routers orchestrate; nothing important in views.

---

## 5. Data model

Single user: no tenant_id, no created_by, no roles.

```
# catalog
StorageArea    name, kind (walkin|freezer|dry|bar|section), walk_order
Item           code, name, base_unit (g|ml|ea), category, default_area,
               walk_order, allergens (ArrayField), active, notes
UnitConversion item, unit, factor_to_base, countable        unique(item, unit)
Supplier       name, account_code, order_days (ArrayField[int]), cutoff_time,
               lead_time_days, min_order_value, contact (JSON), active
SupplierItem   supplier, item, supplier_code, pack_description, pack_qty,
               price (nullable), preferred, active          unique(supplier, item)
ParLevel       item, area, weekday (nullable), qty          see B11

# walks
Walk       kind (order|stock|both), area (nullable=all), started_at,
           submitted_at, status (draft|submitted|locked), notes
WalkLine   walk, item, area, counted_qty, counted_unit, qty_base,
           proposed_order_qty, planned_order_qty,
           theoretical_qty, variance_qty (both Phase 3),
           skipped (bool), note, sort_order
           # generated at walk start from Item by area, ordered by walk_order

# purchasing
PurchaseOrder      supplier, walk, order_date, delivery_date,
                   status (draft|sent|confirmed|received|closed), total, notes, sent_at
PurchaseOrderLine  purchase_order, supplier_item, proposed_packs, packs, qty_base, price
Delivery           purchase_order, supplier, received_on, status
DeliveryLine       delivery, supplier_item, packs_expected, packs_received, price,
                   note (short|over|substituted|rejected)

# inventory  (Phase 3)
StockMovement   item, area, qty (SIGNED, base unit),
                kind (receipt|consume|yield|waste|transfer_in|transfer_out|count_adjustment),
                source_type, source_id, occurred_at, note      APPEND ONLY
StockBalance    item, area, qty, updated_at                    unique(item, area)

# planning
ServiceDay      service_date (unique, DateField), status (open|closed),
                occupancy_rooms, occupancy_guests, notes, opened_at, closed_at
ServiceSection  service_day, section, active, covers,
                covers_source (occupancy|booked|beo|forecast|manual), notes
                                                        unique(service_day, section)
ServiceOutlet   service_section, outlet (executive_lounge), active, covers
Wave            service_section, name, serve_at, covers, sort_order
ProductionLine  service_section, item, name, mode (produce|replenish|check),
                kind (dish|sauce|prep|stock|buffet|service), category, unit,
                proposed_qty, planned_qty, actual_qty, par_level,
                status (planned|prep|ready|served|held|eighty_six),
                supports_lounge, source (menu|template|manual|assist), notes, sort_order
LineComponent   line, item, supplier_item, planned_qty, unit, done, sort_order
WaveAllocation  line, wave, qty                         unique(line, wave)
LineEvent       line, kind, payload (JSON), created_at

# assist  (Phase 5)
AssistProposal  kind, context (JSON), proposal (JSON), rationale, model,
                status (pending|accepted|rejected), decided_at, reject_reason
```

Line modes (this fixes breakfast-is-half-replenishment and the ALC prep/check split):

| mode | Means | Complete when |
|------|-------|---------------|
| `produce` | make N | actual ≥ planned |
| `replenish` | keep at par | topped up — no target qty |
| `check` | fire-to-order: present? | confirmed or 86'd |

A `check` line has no meaningful actual quantity — make that explicit in the schema so the frontend never renders a progress bar for one.

---

## 6. Auth

- `POST /api/v1/auth/login` — email + password → signed token (Django `signing`; no JWT lib). **30-day expiry.** `POST /api/v1/auth/refresh` extends
- One account. Password set by Mykola on the box (`manage.py changepassword`) — never a placeholder
- **The 401 shape is contract-critical:** a walk is 30–60 min offline in a cold room; token may expire mid-walk. The batch submit's 401 must be clearly distinguishable from a data error so the frontend re-auths and retries. **A 401 is never a reason to drop data** — document this in the contract
- Public API posture: rate limit `/auth/login` (`django-ratelimit`) in Phase 0 + Cloudflare WAF rate limiting at the edge; `DEBUG=False`; `ALLOWED_HOSTS=["api.apidiscoverysolution.uk"]` exact; `SECURE_*` headers

CORS:
```python
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://.*\.grok-sandbox\.com$"]   # preview
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])  # published, added later
CORS_ALLOW_CREDENTIALS = False
CORS_PREFLIGHT_MAX_AGE = 86400   # Authorization header → every request preflights
```

---

## 7. Contract discipline

- You ship the endpoint + regenerated `openapi.json` **before** the frontend builds against it. The frontend cannot read your code — a mismatch surfaces as a CORS error or 422 at runtime
- Versioned path `/api/v1/` from day one. `GET /api/v1/version` returns app + contract version (frontend shows a refresh banner on skew). Breaking changes deploy backend-first, always
- Walk batch submit **idempotent on (walk_id, item_id)** — double submit from a phone that lost signal is normal
- Every list endpoint the walk/boards use is fetchable in **one request** with breakdown included (par, counted, on-order, shortfall on order lines) — cross-origin makes extra round-trips expensive
- `select_related`/`prefetch_related` from the first query on any list endpoint (600 items × supplier × par lookups)

---

## 8. Gotchas (each fails silently or at the worst moment)

- **B1** `Decimal` must serialise as JSON number, not `"6.000"` string. django-ninja+Pydantic handles it when schemas declare `Decimal` — **verify in a real response body**
- **B2** Never mix `float` and `Decimal`. `Decimal` end to end, including schemas
- **B3** Blank input → `None`, never `0` (skip vs empty shelf)
- **B4** `auto_now_add=True` can't be overridden; movements need backdating → `default=timezone.now`
- **B6** Admin: a `list_editable` field can't be in `list_display_links` — set links explicitly
- **B7** Service dates: `DateField`. With `USE_TZ=True` a datetime silently shifts the date across midnight
- **B8** `ArrayField` needs `django.contrib.postgres` in `INSTALLED_APPS`
- **B9** After `IntegrityError` inside `atomic()` the transaction is dead — nested savepoint if you catch-and-continue
- **B10** Append-only = `save()` guard raising when `self.pk` set **and** a Postgres `BEFORE UPDATE OR DELETE` trigger via `RunSQL` (with `reverse_sql`)
- **B11** NULL is distinct in unique constraints: `ParLevel(item, area, weekday=None)` inserts twice. PG 15+: `UniqueConstraint(..., nulls_distinct=False)`. PG < 15: sentinel `weekday=-1`. **Decide in Phase 0 from the actual PG version**
- **B12** Balance updates: `F()` expressions inside the same `atomic()` as the movement insert. Never read-modify-write
- **B13** `collectstatic` in the deploy path or admin renders unstyled
- **B15** Recipe explosion (Phase 5): recursive CTE, depth cap 6, visited-path array, **raise on cycle** — a plausible wrong quantity is worse than a crash

---

## 9. Build order

### Phase 0 — skeleton

0. Report ground truth first: `psql --version` (→ B11 decision, record in repo), Python version, tunnel ingress config
1. Project + apps + env-driven settings (`EnvironmentFile` pattern, TZ Europe/London), DB + role, migrations clean
2. ninja at `/api/v1/`, `GET /api/v1/version`, `openapi.json` at a stable path, committed
3. Auth per §6 incl. rate limiting; account created (password: ask Mykola to set on the box)
4. CORS per §6
5. gunicorn + systemd **user** unit (`Restart=on-failure`, linger) + whitenoise/collectstatic + one-command deploy and rollback + Cloudflare: tunnel → :8000, **Access app scoped `/admin*` only**, WAF rate limit `/api/v1/auth/*`

**Gate (all, with evidence):** external `curl` of `/api/v1/version` → 200; login via curl → token; bad password repeatedly → 429; `/admin` prompts Access then renders styled; `systemctl --user restart` recovers and kill -9 auto-restarts; deploy + rollback output; PG version + B11 decision recorded.

### Phase 1 — catalogue

- All catalog models + migrations. Seed storage areas (leave `walk_order` null/orderable); includes meat fridge
- **Admin is a product surface, not scaffolding:** `list_display` of scanned fields; `list_editable` for price/pack_qty/par; `list_filter` supplier/area/category/active; `search_fields` name + supplier_code; `autocomplete_fields` on every FK; `TabularInline` for UnitConversion + SupplierItem on Item; bulk actions (activate/deactivate, set area)
- **Seed from the pack's real transcriptions** in `sheets/`: `alc-dish-sheet-p1.csv`, `alc-dish-sheet-p2.csv` (~85 items with supplier codes across 10 suppliers: Brakes, UFC, BPM, Belazu, H&B, LBP, Direct Seafood, Essential Cuisine, Braehead, Veg Express), `skybar-mep-list.csv` (~130 component names → items with no supplier — that's fine). Dedupe on (supplier, code). Rows marked "verify"/"uncertain" → import flagged unverified, never silently
- `ingest_catalog`: photo/text upload → django-q2 job → **Mistral** strict-JSON extraction (`MISTRAL_API_KEY`, model `LLM_MODEL` default `mistral-medium-latest`, httpx OpenAI-compatible) → review table flagged by confidence → accept writes Item + SupplierItem in one transaction. Extraction schema must handle the real sheet shape: **dish-organised, mixed suppliers, dual codes ("112724 / 591085"), alternative suppliers ("BPM or Brakes"), spec-in-name ("Chicken fillet 140g-170g"), rotated photos, no pack sizes or prices present.** Never guess a code (emit null + low confidence); never drop an item for missing supplier data; convert kg→g, L→ml at extraction; pack_qty in base units. Review UI = Django admin, bulk-first — **review speed matters more than extraction accuracy**
- Prompt rules for extraction: JSON only, no prose/fences; `base_unit` ∈ {g,ml,ea}; flag ambiguous units rather than resolving

**Gate:** 50+ real items usable in under an hour, mostly via ingest (if typing is faster, ingest is broken — fix before proceeding). A walk-style query over items with no supplier/par/price returns cleanly.

### Phase 1.5 — MEP/service boards (backend slice)

MEP is a main product function and ships before ordering. Build the minimal planning slice — **on the real planning schema, no throwaway models:**

- `ServiceDay`, `ServiceSection`, `ProductionLine` (mode check/replenish), `LineComponent`, `LineEvent` migrations
- Dish templates seeded from `skybar-mep-list.csv` (~20 dishes → check-mode lines with components); ALC dishes from the two CSVs. Off-menu (inactive, keep items): sticky pigs in blankets, wild-caught crab cake
- Endpoints: open a day/section → generate lines from templates; tick/untick a line or component; **quick-add an ad-hoc line** (name only, no item FK required); board fetch = one request per section
- Breakfast board second: replenish-mode lines against `ParLevel` rows on a section-kind area — no covers, no waves
- Preps are global: a prep line covers multiple sections — model demand once, don't duplicate lines per section

**Gate:** skybar board fetch/tick/quick-add round-trips work via curl against seeded real data; contract published.

### Phase 2 — walk + ordering (the viability test)

- Walk lifecycle: start (lines generated by area, ordered by walk_order), batch submit (idempotent, B3 skip handling), lock
- Order proposal per line: `shortfall = max(0, par − counted − on_order)`; **sum shortfalls across ALL areas per (item, supplier) before `ceil(total/pack_qty)`** — same item lives in many areas, never emit one PO line per area. Suppress packs=0 / below noise floor. `deliver_on` = next supplier order_day respecting cutoff + lead time. Breakdown (par, counted, on-order, shortfall) returned on every line
- PO: draft → send, delivery receipt (short/over/substituted/rejected)

**Gate:** a real order for real stock placed and received through the app — and the walk beat the clipboard. If not faster: stop, report; the fix is design, not features.

### Phase 3 — ledger

Movements + balances (B10, B12), variance from walk counts already collected (no second walk), waste capture. Gate: a real area counted, variance reconciles, no manual balance edits anywhere.

### Phase 4 — full planner

**Covers are NOT a core daily input. They drive scaling only for `banqueting` and `banquet_buffet` (from BEO events). All other sections run on MEP, pars and replenishment; covers there are optional, informational, and never required.** Consequences:

- Day open / section boards must never block on, prompt for, or default a cover count. `ServiceSection.covers` stays nullable
- Build covers entry + wave scaling for banqueting/banquet_buffet only: per-BEO event covers, summed; waves (one line allocated across waves — never duplicated); produce quantities scale from event covers as `proposed_qty`, Mykola sets `planned_qty`
- The other sections' covers-derivation rules (occupancy take-rate, rolling means, lounge banding, canteen headcount, skybar weather) are **deferred indefinitely — do not build** unless explicitly re-requested
- The v1 rule is unchanged wherever covers do appear: per-section, labelled source, no global dial, no "set all"

Also in Phase 4: produce-mode quantities for canteen boards (entered, not covers-derived), day open/close with outturn capture. Gate: full service day worked from the phone without paper.

### Phase 5 — LLM loop

Recipes + explosion (B15), demand → proposals, assist verbs. All LLM output lands as `AssistProposal`; accept handlers write. Gate: proposals accepted/rejected with audit trail.

**D11 (Hermes A2A assist — locked):** heavy assist tasks go **Hermes A2A v1.0 on loopback**, completion via **signed A2A push webhook** (no polling). Receiver: `POST /api/internal/agent-events` (loopback only — **not** on the tunnel-facing `/api/v1` router). Verify HMAC before touch; upsert proposal **idempotent on `task_id`**. Catalogue photo ingest stays **D10 Mistral**. Full lock: `docs/D11-HERMES-A2A-ASSIST.md`.

**D12 (notes + house-made — locked):** ProductionLine/Item notes in board payload; `Item.house_made` + `ItemComponent` recipe-lite (admin inline); seed Asian slaw + aioli unverified; A2A task type `parse_note` in contract file; ordering ignores house_made until Phase 5. Full lock: `docs/D12-NOTES-HOUSE-MADE.md`.

**D13 (purchasing scope + variance — locked):** `PurchaseOrder.scope` = `replenishment` (default) | `event`. Order proposal `on_order` sums **replenishment only**. Phase 3 variance = **unexplained** (never “error”); per-item noise floor; never auto-correct pars/balances. No global-inventory ambition. Full lock: `docs/D13-PURCHASING-SCOPE-VARIANCE.md`.

---

## 10. Deploy reference

systemd user unit + `EnvironmentFile=` + linger · gunicorn `127.0.0.1:8000` · `collectstatic` on deploy · one-command deploy + rollback · Cloudflare tunnel → :8000 · Access scoped `/admin*` only · WAF on `/api/v1/auth/*` · Postgres and q2 worker never exposed.

**Known operational sequence you'll receive later (do not block on now):** the published frontend origin (add to CORS env and restart), `walk_order` values for the 8 areas, canteen covers frame.
