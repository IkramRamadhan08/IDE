# Voice IDE Backend

FastAPI backend for local-first IDE:
- File tree / read / write
- Diff preview
- Guarded shell commands
- Agent planning (provider-agnostic, keys via .env)
- (Next) wakeword + STT streaming

## Run (dev)
```bash
cd ~/voice-ide/backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn voice_ide_backend.main:app --reload --port 8787
```

Config is loaded from `~/voice-ide/.env` if present.

To avoid manually editing `.env`, use:
```bash
cd ~/voice-ide
./scripts/env.py wizard
```

(or copy from `.env.example`).
