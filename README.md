# Evolving Cook — Django backend

Kitchen ops API on Debian (discovery-system). Stack per `docs/BACKEND_BUILD_INSTRUCTIONS.md`.  
**Live contract `0.1.18`** — phases 0–5 + D10–D15 (section modes, assist, ordering board).

| Item | Value |
|------|--------|
| Bind | `127.0.0.1:8000` |
| Public | `https://api.apidiscoverysolution.uk` (CF tunnel → :8000) |
| Stack | Django 5.2 + django-ninja + django-q2 + gunicorn + Postgres 17 |
| TZ | Europe/London |
| DB | `evolving_cook` / role `evolving_cook_app` |
| Unit | `systemctl --user` → `evolving-cook-django.service` |
| Contract | `APP_VERSION` / `CONTRACT_VERSION` = **0.1.18** (`.env` + settings) |
| FE | Grok monorepo root — this tree is API only |
| FE handoff | `docs/FE-SECTION-MODES.md` · `docs/FE-OPENAPI-SLICE.json` |
| GitHub | `konovalovnickolay89-bot/evolvingcook` → `backend/` |

## Layout

```
config/          Django project (settings, urls, wsgi)
api/             ninja routers + auth + boards + sections + walks + purchasing + assist
catalog/         Phase 1 models, admin, seed, ingest_catalog
planning/        boards, section modes, prep_plan, qty drafts, ordering_assist
walks/           Phase 2 Walk / WalkLine + services
purchasing/      Phase 2 PO / Delivery + services
core inventory assist
docs/            BACKEND_BUILD_INSTRUCTIONS, D10–D15, FE handoff, openapi.json
deploy/          systemd user unit
scripts/         deploy.sh, rollback.sh, export_openapi.py, phase*_gate.py
sheets/          ALC CSVs + skybar-mep-list.csv when present
manage.py
requirements.txt
.env             secrets (mode 600, gitignored)
```

## Quick start (this host)

```bash
cd ~/src/evolving-cook
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# .env already mode 600 on this box; else: cp .env.example .env && chmod 600 .env
./scripts/deploy.sh
python manage.py seed_catalog          # 8 areas + ALC item sheets
python manage.py seed_dish_templates   # ALC dish templates for boards
```

### Catalogue seed

```bash
python manage.py seed_catalog
# skybar-mep-list.csv missing → ALC only (never invent)
PYTHONPATH=. python scripts/phase1_verify.py
```

### Dish templates + boards (Phase 1.5)

```bash
python manage.py seed_dish_templates
# Off-menu inactive (kept): STICKY PIGS IN BLANKETS, WILD-CAUGHT CRAB CAKE
# When skybar-mep-list.csv arrives:
python manage.py seed_dish_templates --skybar-only
# Gate (local Bearer via signed token):
python scripts/phase15_gate.py
```

Board paths (Bearer):

- `POST /api/v1/boards/days/open` — open day/section, generate lines (covers never required)
- `GET  /api/v1/boards/days/{date}/sections/{section}` — **one request** board
- `POST /api/v1/boards/lines/{id}/tick|untick`
- `POST /api/v1/boards/components/{id}/tick|untick`
- `POST /api/v1/boards/lines/quick-add` — name only, no item FK

### Walks + ordering (Phase 2)

```bash
# Gate (Bearer via signed token; seeds minimal pack_qty/par for evidence only — does not invent walk_order)
python scripts/phase2_gate.py
```

Walk / purchasing paths (Bearer):

- `POST /api/v1/walks/start` — kind order|stock|both; optional area_id; lines by area, walk_order nulls last
- `GET  /api/v1/walks/{id}` — **one request** with lines + par/on_order/shortfall when known
- `POST /api/v1/walks/{id}/lines/batch` — idempotent on (walk, item, area); B3 skip≠0; **401 → re-auth+retry, never drop data**
- `POST /api/v1/walks/{id}/submit` · `POST /api/v1/walks/{id}/lock`
- `POST /api/v1/walks/{id}/order-proposal` — sum shortfalls across areas per (item,supplier) then ceil/pack
- `GET  /api/v1/purchasing/orders/{id}` · `POST .../send` · `POST .../deliveries`
- Delivery notes: short|over|substituted|rejected|ok — **no StockMovement** (Phase 3)

### ingest_catalog (LLM proposals only)

- Admin: Catalog ingest uploads → queue extraction (django-q2)
- Provider **Mistral** (D10): `MISTRAL_API_KEY` + `LLM_MODEL` (default `mistral-medium-latest`, **multi-modal**)
- Thin module: `catalog/llm_provider.py` → chat completions via httpx (text and/or sheet photos as `image_url` data-URLs)
- Without the key, extraction **fails with env name `MISTRAL_API_KEY`** — never fakes rows
- LLM output → review/proposal rows only; accept writes Item + SupplierItem
- Photo: admin upload `source_kind=photo` + image (JPEG/PNG/WebP). HEIC not supported — convert on phone first.

#### qcluster worker (persistent)

Same `.env` as Django (`EnvironmentFile` on the user unit). ORM broker only — no extra port.

```bash
# install/restart with API (preferred)
./scripts/deploy.sh

# or unit-only
systemctl --user enable --now evolving-cook-qcluster.service
systemctl --user status evolving-cook-qcluster.service
systemctl --user restart evolving-cook-qcluster.service
journalctl --user -u evolving-cook-qcluster.service -f
```

**Queue from admin:** Django admin → Catalog ingest uploads → select row(s) → action **Queue extraction job (django-q2 → Mistral)** → Go. Watch status: `queued` → `running` → `review` (or `failed` + `error`).

**Failure modes:**
- `MISTRAL_API_KEY` unset in worker env → upload `failed`, error names `MISTRAL_API_KEY` (no fake rows)
- qcluster down → upload stays `queued` until worker starts
- Mistral HTTP 4xx/5xx → upload `failed` with status/body class in `error`
- HEIC/HEIF photo → fail closed; re-export JPEG/PNG on phone
- Proposals stay **pending** until a human accept/reject — never auto-write catalogue

```bash
# manual foreground worker (dev only; prefer systemd unit above)
. .venv/bin/activate
python manage.py qcluster
```

### Phase 5 assist (D11 — locked, not built yet)

- Heavy assist → **Hermes A2A v1.0** loopback + **signed push** → `POST /api/internal/agent-events` (not on public `/api/v1`)
- Write `AssistProposal` only; idempotent on `task_id`; no polling happy path
- Lock: `docs/D11-HERMES-A2A-ASSIST.md`

### Set the one account password (Mykola)

Password is **never** invented by the agent. After deploy:

```bash
cd ~/src/evolving-cook
set -a; source .env; set +a
. .venv/bin/activate
python manage.py changepassword "$DJANGO_SUPERUSER_EMAIL"
```

### Local checks

```bash
curl -sS -H 'Host: api.apidiscoverysolution.uk' http://127.0.0.1:8000/api/v1/version
curl -sS -X POST -H 'Content-Type: application/json' -H 'Host: api.apidiscoverysolution.uk' \
  -d '{"email":"…","password":"…"}' http://127.0.0.1:8000/api/v1/auth/login
```

### Deploy / rollback

```bash
./scripts/deploy.sh     # migrate + collectstatic + openapi export + restart unit
./scripts/rollback.sh   # checkout .deploy-previous-ref then redeploy
```

## Auth contract (Phase 0)

- `POST /api/v1/auth/login` → signed Bearer token (Django `signing`, **30 days**)
- `POST /api/v1/auth/refresh` extends
- **401 is never a reason to drop data** — client re-auths and retries (cold-room walk)
- Login rate-limited (`django-ratelimit`, default `10/5m` per IP)
- Edge WAF on `/api/v1/auth/*` is Nick/Cloudflare (app-side limit is always on)

## CORS

- Regex: `^https://.*\.grok-sandbox\.com$`
- Exact list: `CORS_ALLOWED_ORIGINS` env (default empty — do not hardcode published FE origin)

## Cloudflare (ops)

- Tunnel must target **`http://127.0.0.1:8000`** (not :4100)
- Access app: **`/admin*` only**
- WAF rate limit: `/api/v1/auth/*`

See `docs/GROUND_TRUTH.md` for PG version + **B11** (`nulls_distinct=False`).

## Out of scope here

Phase 3 ledger / StockMovement, full Phase 4 covers derivation, Phase 5/D11 assist runtime, planner FE, Elixir/Phoenix, Node :4100.
