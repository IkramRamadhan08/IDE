from __future__ import annotations

from pathlib import Path
from typing import Literal
import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .settings import ROOT, ENV_PATH, load_settings
from . import settings as settings_mod
from .fs import list_tree, read_text, write_text, diff_text, safe_join


app = FastAPI(title="Voice IDE Backend", version="0.1.0")

# Serialize scaffold calls to avoid LLM provider rate-limit bursts (429).
SCAFFOLD_LOCK = threading.Lock()


def _reload_settings():
    settings_mod.settings = load_settings()

# Local app: allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    # Vite dev server ports can shift if one is already in use.
    # Keep this permissive for local dev.
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://localhost:8788",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Workspace root (selected by UI later)
STATE = {
    "workspace": None,  # Path
    "runners": {},  # id -> dict(proc, logs, cwd, port, started)
}


class WorkspaceSetReq(BaseModel):
    path: str


class WorkspaceInfo(BaseModel):
    path: str | None
    default: str | None


@app.get("/api/workspace", response_model=WorkspaceInfo)
def get_workspace():
    p: Path | None = STATE["workspace"]
    return WorkspaceInfo(path=str(p) if p else None, default=settings_mod.settings.default_workspace)


@app.post("/api/workspace")
def set_workspace(req: WorkspaceSetReq):
    p = Path(req.path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, "Workspace path must be an existing directory")
    STATE["workspace"] = p
    return {"ok": True, "path": str(p)}


# Settings endpoints
class SettingsInfo(BaseModel):
    default_workspace: str | None

    stt_provider: str
    llm_provider: str
    tts_provider: str

    groq_whisper_model: str
    groq_chat_model: str
    openai_chat_model: str
    gemini_chat_model: str

    has_groq_key: bool
    has_openai_key: bool
    has_gemini_key: bool
    has_elevenlabs_key: bool


@app.get("/api/settings", response_model=SettingsInfo)
def get_settings():
    s = settings_mod.settings
    return SettingsInfo(
        default_workspace=s.default_workspace,
        stt_provider=s.stt_provider,
        llm_provider=s.llm_provider,
        tts_provider=s.tts_provider,
        groq_whisper_model=s.groq_whisper_model,
        groq_chat_model=s.groq_chat_model,
        openai_chat_model=s.openai_chat_model,
        gemini_chat_model=s.gemini_chat_model,
        has_groq_key=bool(s.groq_api_key),
        has_openai_key=bool(s.openai_api_key),
        has_gemini_key=bool(s.gemini_api_key),
        has_elevenlabs_key=bool(s.elevenlabs_api_key),
    )


class SettingsUpdateReq(BaseModel):
    default_workspace: str | None = None

    stt_provider: str | None = None
    llm_provider: str | None = None
    tts_provider: str | None = None

    groq_whisper_model: str | None = None
    groq_chat_model: str | None = None
    openai_chat_model: str | None = None
    gemini_chat_model: str | None = None

    groq_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    elevenlabs_api_key: str | None = None


def _env_set(key: str, value: str) -> None:
    import subprocess
    import sys

    script = ROOT / "scripts" / "env.py"
    if not script.exists():
        raise RuntimeError(f"Missing env helper: {script}")

    # Call the helper so we preserve formatting/comments
    subprocess.run(
        [sys.executable, str(script), "set", key, value],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    )


@app.get("/api/models")
def list_models(provider: str = Query("", description="llm provider, e.g. groq|openai|gemini")):
    prov = provider.lower().strip()

    import json
    import urllib.request
    import urllib.error

    if prov == "groq":
        key = (settings_mod.settings.groq_api_key or "").strip()
        if not key:
            raise HTTPException(400, "GROQ_API_KEY is not set")

        req_ = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req_, timeout=10) as resp:  # nosec
                raw_body = resp.read().decode("utf-8")
                data = json.loads(raw_body) if raw_body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            try:
                j = json.loads(body) if body else {}
                msg = j.get("error", {}).get("message") or j.get("message")
            except Exception:
                msg = None
            raise HTTPException(exc.code, msg or body or f"Groq models error ({exc.code})")
        except Exception as exc:
            raise HTTPException(502, f"Failed to fetch Groq models: {exc}")

        models = data.get("data") or []
        out = []
        for m in models:
            mid = (m.get("id") if isinstance(m, dict) else None) or None
            if mid:
                out.append(str(mid))
        out = sorted(set(out))
        return {"provider": "groq", "models": out}

    if prov == "openai":
        key = (settings_mod.settings.openai_api_key or "").strip()
        if not key:
            raise HTTPException(400, "OPENAI_API_KEY is not set")

        req_ = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req_, timeout=10) as resp:  # nosec
                raw_body = resp.read().decode("utf-8")
                data = json.loads(raw_body) if raw_body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(exc.code, body or f"OpenAI models error ({exc.code})")
        except Exception as exc:
            raise HTTPException(502, f"Failed to fetch OpenAI models: {exc}")

        models = data.get("data") or []
        out = []
        for m in models:
            mid = (m.get("id") if isinstance(m, dict) else None) or None
            if mid and any(k in mid for k in ["gpt", "codex"]):
                out.append(str(mid))
        out = sorted(set(out))
        return {"provider": "openai", "models": out}

    if prov == "gemini":
        key = (settings_mod.settings.gemini_api_key or "").strip()
        if not key:
            raise HTTPException(400, "GEMINI_API_KEY is not set")

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        req_ = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req_, timeout=10) as resp:  # nosec
                raw_body = resp.read().decode("utf-8")
                data = json.loads(raw_body) if raw_body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(exc.code, body or f"Gemini models error ({exc.code})")
        except Exception as exc:
            raise HTTPException(502, f"Failed to fetch Gemini models: {exc}")

        models = data.get("models") or []
        out = []
        for m in models:
            mid = (m.get("name") if isinstance(m, dict) else None) or None
            if mid:
                # normalize "models/xxx" -> "xxx"
                out.append(str(mid).replace("models/", ""))
        out = sorted(set(out))
        return {"provider": "gemini", "models": out}

    raise HTTPException(400, "provider must be groq|openai|gemini")


@app.put("/api/settings")
def update_settings(req: SettingsUpdateReq):
    # Behavior A: if a key field is empty string, do NOT overwrite.
    # (Only overwrite when user actually provides a non-empty string.)

    mapping: list[tuple[str, str | None, bool]] = [
        ("DEFAULT_WORKSPACE", req.default_workspace if req.default_workspace is not None else None, False),
        ("STT_PROVIDER", req.stt_provider, False),
        ("LLM_PROVIDER", req.llm_provider, False),
        ("TTS_PROVIDER", req.tts_provider, False),
        ("GROQ_WHISPER_MODEL", req.groq_whisper_model, False),
        ("GROQ_CHAT_MODEL", req.groq_chat_model, False),
        ("OPENAI_CHAT_MODEL", req.openai_chat_model, False),
        ("GEMINI_CHAT_MODEL", req.gemini_chat_model, False),
        ("GROQ_API_KEY", req.groq_api_key, True),
        ("OPENAI_API_KEY", req.openai_api_key, True),
        ("GEMINI_API_KEY", req.gemini_api_key, True),
        ("ELEVENLABS_API_KEY", req.elevenlabs_api_key, True),
    ]

    changed: list[str] = []

    # Ensure .env exists (if not, create from .env.example)
    if not ENV_PATH.exists():
        import shutil

        example = ROOT / ".env.example"
        if example.exists():
            shutil.copyfile(example, ENV_PATH)
        else:
            ENV_PATH.write_text("", encoding="utf-8")

    for env_key, val, is_secret in mapping:
        if val is None:
            continue
        if is_secret and val.strip() == "":
            # don't overwrite existing secrets with blank
            continue
        _env_set(env_key, val)
        changed.append(env_key)

    _reload_settings()
    return {"ok": True, "changed": changed}


def _ws() -> Path:
    p: Path | None = STATE["workspace"]
    if p is None:
        raise HTTPException(400, "Workspace not set")
    return p


# ---- Runner (v0) ----
# Minimal, guarded process runner for web projects.
# Not a general shell. We only allow: npm install + npm run dev (Vite-like).


def _runners() -> dict:
    return STATE["runners"]


def _is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def _next_port(start: int = 8800, end: int = 8899) -> int:
    used = {r.get("port") for r in _runners().values()}
    for p in range(start, end + 1):
        if p not in used and not _is_port_in_use(p):
            return p
    raise HTTPException(400, "No free ports")


class DetectedProject(BaseModel):
    root: str
    name: str
    has_dev: bool


@app.get("/api/run/detect")
def run_detect():
    base = _ws()
    out: list[dict] = []
    seen = set()

    # Find package.json up to depth 4
    for pj in base.rglob("package.json"):
        try:
            rel = str(pj.parent.relative_to(base)) or "."
        except Exception:
            continue
        if rel.startswith("node_modules") or "/node_modules" in rel:
            continue
        if rel in seen:
            continue
        seen.add(rel)

        try:
            import json

            data = json.loads(pj.read_text(encoding="utf-8"))
            name = str(data.get("name") or pj.parent.name)
            scripts = data.get("scripts") or {}
            has_dev = isinstance(scripts, dict) and ("dev" in scripts)
        except Exception:
            continue

        out.append({"root": rel, "name": name, "has_dev": bool(has_dev)})

    # Also detect folders with only index.html (static preview)
    for idx in base.rglob("index.html"):
        try:
            rel = str(idx.parent.relative_to(base)) or "."
        except Exception:
            continue
        if rel in seen:
            continue
        seen.add(rel)

        out.append({"root": rel, "name": idx.parent.name, "has_dev": True})

    # prefer root-level first
    out.sort(key=lambda x: (x["root"] != ".", x["root"]))
    return {"ok": True, "projects": out}


class RunStartReq(BaseModel):
    project_root: str
    port: int | None = None


@app.post("/api/run/start")
def run_start(req: RunStartReq):
    import subprocess
    import threading
    import time
    import uuid

    base = _ws()
    proj = safe_join(base, req.project_root)
    if not proj.exists() or not proj.is_dir():
        raise HTTPException(400, "project_root must exist inside workspace")

    port = req.port or _next_port()
    rid = uuid.uuid4().hex[:8]
    logs: list[str] = []

    def pump(proc):
        assert proc.stdout
        for line in proc.stdout:
            logs.append(line.rstrip("\n"))
            if len(logs) > 2000:
                del logs[:500]

    # Check if this is a static project (no package.json or no dev script)
    pj_path = proj / "package.json"
    is_static = not pj_path.exists()

    if not is_static:
        try:
            import json
            data = json.loads(pj_path.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            is_static = "dev" not in scripts
        except Exception:
            is_static = True

    if is_static:
        # Serve static files with Python http.server
        logs.append(f"$ python -m http.server {port}")
        proc = subprocess.Popen(
            ["python", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            cwd=str(proj),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    else:
        # npm project with dev script
        logs.append("$ npm install")
        install = subprocess.run(["npm", "install"], cwd=str(proj), capture_output=True, text=True)
        if install.stdout:
            logs.extend([l for l in install.stdout.splitlines() if l.strip()])
        if install.stderr:
            logs.extend([l for l in install.stderr.splitlines() if l.strip()])
        if install.returncode != 0:
            raise HTTPException(400, "npm install failed")

        # strictPort so we know the port; if it's taken, user can run again (we'll pick a new port)
        cmd = ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--strictPort", "--port", str(port)]
        logs.append(f"$ {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, cwd=str(proj), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    t = threading.Thread(target=pump, args=(proc,), daemon=True)
    t.start()

    _runners()[rid] = {
        "proc": proc,
        "logs": logs,
        "started": time.time(),
        "cwd": str(proj),
        "port": port,
        "project_root": req.project_root,
    }
    return {"ok": True, "id": rid, "pid": proc.pid, "url": f"http://localhost:{port}", "project_root": req.project_root}


@app.get("/api/run/list")
def run_list():
    items = []
    for rid, r in _runners().items():
        proc = r.get("proc")
        running = bool(proc and proc.poll() is None)
        items.append({
            "id": rid,
            "project_root": r.get("project_root"),
            "port": r.get("port"),
            "url": f"http://localhost:{r.get('port')}",
            "pid": getattr(proc, "pid", None),
            "running": running,
        })
    return {"ok": True, "items": items}


@app.get("/api/run/logs")
def run_logs(id: str, limit: int = 300):
    r = _runners().get(id)
    if not r:
        raise HTTPException(404, "runner not found")
    logs = r.get("logs") or []
    proc = r.get("proc")
    return {"ok": True, "id": id, "pid": getattr(proc, "pid", None), "running": bool(proc and proc.poll() is None), "logs": logs[-limit:]}


@app.post("/api/run/stop")
def run_stop(id: str):
    r = _runners().get(id)
    if not r:
        raise HTTPException(404, "runner not found")
    proc = r.get("proc")
    if proc and proc.poll() is None:
        proc.terminate()
    return {"ok": True}


@app.post("/api/run/close")
def run_close(id: str):
    # stop + remove
    r = _runners().get(id)
    if not r:
        return {"ok": True}
    proc = r.get("proc")
    if proc and proc.poll() is None:
        proc.terminate()
    _runners().pop(id, None)
    return {"ok": True}


class ListReq(BaseModel):
    path: str = "."


@app.post("/api/fs/list")
def fs_list(req: ListReq):
    return {"items": list_tree(_ws(), req.path)}


class ReadReq(BaseModel):
    path: str


@app.post("/api/fs/read")
def fs_read(req: ReadReq):
    try:
        return {"content": read_text(_ws(), req.path)}
    except FileNotFoundError:
        raise HTTPException(404, "Not found")


class WriteReq(BaseModel):
    path: str
    content: str
    expected_sha256: str | None = None  # reserved for optimistic locking


@app.post("/api/fs/write")
def fs_write(req: WriteReq):
    write_text(_ws(), req.path, req.content)
    return {"ok": True}


class WriteOp(BaseModel):
    path: str
    content: str


class ApplyManyReq(BaseModel):
    ops: list[WriteOp]
    overwrite: bool = False


@app.post("/api/fs/apply_many")
def fs_apply_many(req: ApplyManyReq):
    root = _ws()
    conflicts: list[str] = []

    # preflight
    for op in req.ops:
        p = safe_join(root, op.path)
        if p.exists() and not req.overwrite:
            conflicts.append(op.path)

    if conflicts:
        raise HTTPException(409, f"Conflicts (already exist): {', '.join(conflicts[:20])}")

    for op in req.ops:
        write_text(root, op.path, op.content)

    return {"ok": True, "count": len(req.ops)}


class DiffReq(BaseModel):
    path: str
    new_content: str


@app.post("/api/fs/diff")
def fs_diff(req: DiffReq):
    old = read_text(_ws(), req.path)
    d = diff_text(old, req.new_content, filename=req.path)
    return {"diff": d}


# Agent endpoint (v0): suggest patch for active file, return diff.
class AgentReq(BaseModel):
    input: str
    mode: Literal["type", "voice"] = "type"
    active_file: str | None = None
    selection: str | None = None


# Project builder endpoint (v0): scaffold a new app from scratch.
class ScaffoldReq(BaseModel):
    name: str
    goal: str
    ref_url: str | None = None


class PrdReq(BaseModel):
    name: str
    goal: str
    ref_url: str | None = None


class ScaffoldOp(BaseModel):
    path: str
    content: str


class ScaffoldResp(BaseModel):
    spoken: str
    log: str
    project_root: str
    ops: list[ScaffoldOp]


@app.post("/api/agent/scaffold", response_model=ScaffoldResp)
def scaffold(req: ScaffoldReq):
    # kept for backward compatibility; UI no longer uses "Create App".
    _ws()
    from .agent import scaffold_webapp

    try:
        # Block (queue) scaffold requests instead of failing fast; user prefers waiting over 429 spam.
        with SCAFFOLD_LOCK:
            res = scaffold_webapp(name=req.name, goal=req.goal, ref_url=req.ref_url)

        return ScaffoldResp(
            spoken=res.spoken,
            log=res.log,
            project_root=res.project_root,
            ops=[ScaffoldOp(path=o.path, content=o.content) for o in res.ops],
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/agent/prd")
def prd(req: PrdReq):
    """Generate a Product Requirements Document only (no code)."""
    _ws()
    from .agent import generate_prd

    try:
        with SCAFFOLD_LOCK:
            out = generate_prd(name=req.name, goal=req.goal, ref_url=req.ref_url)
        if not out.get("prd_markdown"):
            raise RuntimeError("LLM returned empty PRD")
        return {"ok": True, **out}
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/agent")
def agent(req: AgentReq):
    """Suggest a multi-file patch. Adds per-file unified diffs."""
    ws_root = _ws()
    try:
        current = read_text(ws_root, req.active_file) if req.active_file else ""

        # Get all file paths as context
        all_files = [
            str(p.relative_to(ws_root))
            for p in ws_root.rglob("*")
            if p.is_file() and "node_modules" not in str(p) and ".git" not in str(p)
        ]

        relevant_files: dict[str, str] = {}

        def add_relevant(rel_path: str, max_chars: int = 20_000):
            try:
                p = ws_root / rel_path
                if not p.exists() or not p.is_file():
                    return
                txt = read_text(ws_root, rel_path)
                relevant_files[rel_path] = txt[:max_chars]
            except Exception:
                return

        # Always include: active file (if any) + some key files
        if req.active_file:
            add_relevant(req.active_file)
        for key_file in ["package.json", "README.md", "src/App.tsx", "src/main.tsx", "src/app.css"]:
            add_relevant(key_file)

        # Heuristic: if user mentions CSS/styles/theme, include CSS files under src/styles/
        hint = (req.input or "").lower()
        wants_style = any(k in hint for k in ["css", "style", "styles", "tema", "theme", "warna", "color", "font", "spacing"])
        if wants_style:
            for p in (ws_root / "src" / "styles").glob("*.css"):
                try:
                    rel = str(p.relative_to(ws_root))
                except Exception:
                    continue
                if rel not in relevant_files:
                    add_relevant(rel, max_chars=30_000)

        # If active file is HTML, include linked CSS files (best-effort)
        try:
            if (req.active_file or "").endswith(".html"):
                import re

                html = read_text(ws_root, req.active_file) if req.active_file else ""
                for m in re.findall(r"href=[\"']([^\"']+\.css)[\"']", html, flags=re.IGNORECASE):
                    css_path = m.lstrip("/")
                    if css_path and css_path not in relevant_files:
                        add_relevant(css_path)
        except Exception:
            pass

    except Exception:
        current = ""
        all_files = []
        relevant_files = {}

    try:
        from .agent import suggest

        sug = suggest(
            instruction=req.input,
            path=req.active_file or "(no-active-file)",
            content=current,
            file_tree=all_files,
            relevant_files=relevant_files,
        )

        out_changes: list[dict[str, str]] = []
        for ch in (sug.changes or []):
            if not isinstance(ch, dict):
                continue
            p = str(ch.get("path") or "").strip()
            nc = ch.get("new_content")
            if not p or not isinstance(nc, str):
                continue

            try:
                old = read_text(ws_root, p)
            except FileNotFoundError:
                old = ""

            out_changes.append({
                "path": p,
                "new_content": nc,
                "diff": diff_text(old, nc, filename=p),
            })

        if not out_changes:
            raise RuntimeError("LLM returned no changes")

        return {
            "spoken": sug.spoken,
            "log": sug.log,
            "changes": out_changes,
        }
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))
