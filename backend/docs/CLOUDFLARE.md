# Cloudflare / ops checklist (Phase 0)

Agent cannot edit system `cloudflared` (token-file under `/etc/cloudflared`, root unit). Nick host-shell steps:

## Tunnel ingress

Target must be:

```yaml
# conceptual — actual config may be dashboard/token managed
ingress:
  - hostname: api.apidiscoverysolution.uk
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Verify after change:

```bash
curl -sS https://api.apidiscoverysolution.uk/api/v1/version
# expect 200 JSON app_version/contract_version
```

If still on :4100 (old Node), update tunnel and restart:

```bash
sudo systemctl restart cloudflared
```

## Access

- Zero Trust Application covering **only** path `/admin*` on `api.apidiscoverysolution.uk`
- Do **not** put Access in front of `/api/v1/*` (Bearer token auth)

## WAF

- Rate limit rule on `/api/v1/auth/*` (login abuse)
- App rate-limits login per IP and per username via django-ratelimit

## Internal routes

`/api/internal/*` is not on `/api/v1`, but the tunnel still forwards every path to `127.0.0.1:8000`. The app rejects those requests because they carry `CF-*` or forwarding headers. Do not strip those headers on the tunnel to "make internal routes work" from the public hostname — that is the hole. Hermes and gate scripts call `http://127.0.0.1:8000` directly and do not send those headers.

`/api/internal/intelligence/assign` also needs `X-Internal-Token: $INTERNAL_API_TOKEN` (16+ characters). Leave it unset and the route stays closed.

## Admin static

Deploy runs `collectstatic` + whitenoise so `/admin` is styled once Access lets you through.
