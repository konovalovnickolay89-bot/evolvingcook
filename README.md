# Evolving Cook (monorepo)

| Path | What |
|------|------|
| **/** (repo root) | Grok-hosted kitchen FE (Vite / React) |
| **`backend/`** | Django 5.2 API — catalogue, boards, walks, purchasing, ledger, planner, assist |

## Origins

| Piece | Value |
|-------|--------|
| FE (CORS) | `https://evolvingcook.grok.me` |
| API public | `https://api.apidiscoverysolution.uk` → tunnel → `127.0.0.1:8000` |
| Contract | see `backend/` live `/api/v1/version` (0.1.17+) |

## Backend (this host)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env   # fill secrets
./scripts/deploy.sh
```

Full build brief: `backend/docs/BACKEND_BUILD_INSTRUCTIONS.md`

## Frontend

```bash
npm install
npm run dev
```

See `ORIGIN.md` for published origin / Vite `allowedHosts`.
