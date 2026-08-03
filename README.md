# Evolving Cook — Django backend

**Phase 0 skeleton** on Debian (discovery-system). Stack per `docs/BACKEND_BUILD_INSTRUCTIONS.md`.

| Item | Value |
|------|--------|
| Bind | `127.0.0.1:8000` |
| Public | `https://api.apidiscoverysolution.uk` (CF tunnel → :8000) |
| Stack | Django 5.2 + django-ninja + gunicorn + Postgres 17 |
| TZ | Europe/London |
| DB | `evolving_cook` / role `evolving_cook_app` |
| Unit | `systemctl --user` → `evolving-cook-django.service` |

## Layout

```
config/          Django project (settings, urls, wsgi)
api/             ninja routers + auth helpers
core catalog walks purchasing inventory planning assist
                 empty apps ready for Phase 1+
docs/            BACKEND_BUILD_INSTRUCTIONS.md, GROUND_TRUTH.md, openapi.json
deploy/          systemd user unit
scripts/         deploy.sh, rollback.sh, export_openapi.py
sheets/          Phase 1 CSV seeds (not required for Phase 0)
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
```

### Set the one account password (Mykola)

Password is **never** invented by the agent. After deploy:

```bash
cd ~/src/evolving-cook
set -a; source .env; set +a
. .venv/bin/activate
python manage.py changepassword "$DJANGO_SUPERUSER_EMAIL"
# or: python manage.py changepassword mykola
```

Account is created without a usable password until you run `changepassword`.

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

Phase 1+ catalogue, frontend, Elixir/Phoenix, Node :4100, Casual Board.
