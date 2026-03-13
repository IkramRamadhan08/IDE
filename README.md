# voice-ide

Monorepo:
- `frontend/` (Vite + React)
- `backend/` (FastAPI)

## Env (no more manual editing)

Root config lives in `~/voice-ide/.env` (ignored by git). Template: `~/voice-ide/.env.example`.

Use the env helper:

```bash
cd ~/voice-ide

# create .env from .env.example if missing
./scripts/env.py init

# interactive prompt (recommended)
./scripts/env.py wizard

# set a single key
./scripts/env.py set OPENAI_API_KEY "..."

# read a key
./scripts/env.py get LLM_PROVIDER
```

Notes:
- This script **writes only** to `~/voice-ide/.env`.
- Secrets stay local; don’t commit `.env`.
