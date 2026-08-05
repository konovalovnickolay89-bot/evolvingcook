# Catalogue ingest + qcluster ops

## Units

| Unit | Role |
|------|------|
| `evolving-cook-django.service` | Gunicorn API `127.0.0.1:8000` |
| `evolving-cook-qcluster.service` | django-q2 worker (ORM broker; **no port**) |

Both use the same `EnvironmentFile=%h/src/evolving-cook/.env` (includes `MISTRAL_API_KEY`).

```bash
./scripts/deploy.sh   # migrates, installs both units, restarts both
systemctl --user is-active evolving-cook-django.service evolving-cook-qcluster.service
journalctl --user -u evolving-cook-qcluster.service -f
```

## Queue extraction (operator)

1. Django admin → **Catalog ingest uploads**
2. Add upload: `source_kind=text` + paste sheet lines, **or** photo JPEG/PNG/WebP
3. Select row(s) → action **Queue extraction job (django-q2 → Mistral)** → Go
4. Status path: `pending` → `queued` → `running` → **`review`** (success) or `failed`
5. Review **Catalog ingest proposals** — accept/reject is **human only** (LLM never writes Item)

Equivalent service call (shell, after `set -a; source .env; set +a`):

```bash
cd ~/src/evolving-cook
. .venv/bin/activate
python manage.py shell -c "from catalog.ingest import queue_ingest_extraction; print(queue_ingest_extraction(<upload_id>))"
```

## Failure modes

| Symptom | Likely cause |
|---------|----------------|
| Upload stuck `queued` | qcluster not running |
| `failed` mentions `MISTRAL_API_KEY` | key missing in worker env (check unit EnvironmentFile) |
| `failed` Mistral HTTP 4xx/5xx | billing, model name, payload — see upload.error |
| HEIC rejected | re-export JPEG/PNG on phone |
| Zero proposals + `review` | model returned empty items — re-queue or fix text |

Never print `MISTRAL_API_KEY`. Prove presence only:

```bash
pid=$(systemctl --user show evolving-cook-qcluster.service -p MainPID --value)
tr '\0' '\n' < /proc/$pid/environ | grep -c '^MISTRAL_API_KEY='
# expect 1
```

## Smoke (optional)

```bash
cd ~/src/evolving-cook
PATH="$PWD/.venv/bin:$PATH" python3 scripts/ingest_smoke.py
```

Default model: `mistral-medium-latest` (via `LLM_MODEL` or code default). `pixtral-large-latest` is retired on the Mistral API.