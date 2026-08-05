# Phase 0 ground truth (recorded 2026-08-03)

| Fact | Value | Notes |
|------|--------|-------|
| Host | Debian discovery-system | Linux 6.12.95+deb13-amd64 |
| Python | 3.13.5 (`python3`) | No bare `python` |
| Postgres client/server | **17.10** (Debian 17.10-0+deb13u1) | |
| **B11 decision** | `UniqueConstraint(..., nulls_distinct=False)` | PG 15+; preferred over sentinel `weekday=-1` |
| uv | install user-local if missing | fallback: venv + pip |
| Bind | `127.0.0.1:8000` | NOT 4100 (old Node) |
| Public host | `https://api.apidiscoverysolution.uk` | Cloudflare tunnel |
| DB name | `evolving_cook` | siblings `evolving_cook_dev`, `evolving_cook_v2` **untouched** |
| App role | `evolving_cook_app` | LOGIN, no superuser, no CREATEDB |
| TZ | Europe/London | |
| Linger | yes | user systemd |

## B11 (ParLevel unique with NULL weekday)

Postgres 17.10 treats NULL as distinct in unique constraints by default.
Phase 1+ must use:

```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["item", "area", "weekday"],
            name="uniq_parlevel_item_area_weekday",
            nulls_distinct=False,
        )
    ]
```

Do **not** use weekday sentinel `-1` on this host.

## Tunnel (as observed)

- Unit: system `cloudflared.service` (active)
- Cmdline: `cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token`
- Config is token-managed (no readable local ingress YAML for this user)
- Required ingress target for this API: **`http://127.0.0.1:8000`**
- If public host still points at :4100, Nick must update tunnel ingress (agent cannot read/edit `/etc/cloudflared` without elevated host shell)

## Access / WAF (ops notes for Nick)

- Cloudflare Access: path-scope **`/admin*` only** (not whole hostname)
- WAF / rate limit edge: `/api/v1/auth/*` (app also rate-limits login via django-ratelimit)
- API auth is Bearer token; Access must not sit in front of `/api/v1/*`
