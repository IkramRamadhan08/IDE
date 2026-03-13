from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

# Simple in-memory caches to reduce repeated external fetches / LLM calls (rate-limit friendly)
_REF_CACHE: dict[str, tuple[float, str]] = {}
_SCAFFOLD_CACHE: dict[str, tuple[float, "ScaffoldResult"]] = {}
_PRD_CACHE: dict[str, tuple[float, dict[str, str]]] = {}

# Very small global throttle to avoid spamming LLM providers from concurrent requests.
# This is intentionally simple and process-local: good enough for a single-user local IDE.
_LLM_LAST_CALL_TS: float = 0.0
_MIN_LLM_GAP_SECONDS: float = 0.5  # minimum gap between outbound LLM calls


def _throttle_llm_calls() -> None:
    """Serialize LLM calls with a small delay to be friendlier to rate limits.

    This does not enforce a strict QPS budget, but smooths out bursts when
    multiple requests arrive at nearly the same time (e.g., scaffold + PRD).
    """
    global _LLM_LAST_CALL_TS
    now = time.time()
    gap = now - _LLM_LAST_CALL_TS
    if gap < _MIN_LLM_GAP_SECONDS:
        time.sleep(_MIN_LLM_GAP_SECONDS - gap)
    _LLM_LAST_CALL_TS = time.time()

from . import settings as settings_mod


@dataclass
class AgentSuggestion:
    spoken: str
    log: str
    changes: list[dict[str, str]]


@dataclass
class ScaffoldFile:
    path: str
    content: str


@dataclass
class ScaffoldResult:
    spoken: str
    log: str
    project_root: str
    ops: list[ScaffoldFile]


SYSTEM_PATCH = """You are an expert software engineer working inside a local IDE.
You have access to the *entire* file tree of the project.
You will be given:
- a user instruction (natural language)
- the active file path
- the full current content of that file
- a list of all files in the project (file_tree)
- content of key project files (relevant_files)

Return ONLY valid JSON with this schema:
{
  "spoken": "short explanation for the user, listing exactly which files will be modified",
  "changes": [
    {"path": "path/to/file1", "new_content": "full updated content of file1"},
    {"path": "path/to/file2", "new_content": "full updated content of file2"}
  ]
}
Rules:
- You are free to edit ANY file in the project, not just the active file.
- If you need to modify a file, propose the full updated content for that file in the 'changes' list.
- Keep changes minimal and consistent with existing style.
- Do not include markdown fences.
- In the 'spoken' field, explicitly state which files you are modifying (e.g., "I'm updating App.tsx and App.css").
- If the instruction is unclear, explain in spoken.
"""


SYSTEM_SCAFFOLD = """You are an expert product engineer.
You will be given:
- an app name
- an app goal/description
- (optional) a reference design snapshot from a URL

Create a BRAND NEW web app project (React + Vite + TypeScript) that a non-coder can run.

Hard requirements (do not ignore):
- Structural Integrity: include modular folders at minimum:
  - src/components/
  - src/styles/
  - src/assets/
- Theming: set CSS variables in src/styles/theme.css under :root so later theme changes are easy.
- Zero-Empty File Policy: every file you output must contain functional content (no placeholders like "TODO").
- Wiring: ensure the app actually runs with `npm install` then `npm run dev`.
- Keep it minimal but complete: include a small set of components and dummy data relevant to the app goal.

Reference URL behavior:
- If a reference snapshot is provided, infer its design DNA (layout, spacing, typography, vibe).
- Asset Bridge (self-sufficient assets):
  - Prefer local/inline SVG (do not depend on external logo/icon URLs).
  - If SVG samples are provided (svg_path_samples/svg_assets), create at least one local SVG under src/assets/ (e.g., src/assets/mark.svg) and/or an inline React component (e.g., src/components/BrandMark.tsx) that embeds the SVG paths.
  - Convert palette into CSS design tokens under :root.
  - If reference uses Google Fonts, include the appropriate <link> tags in index.html; otherwise use a similar system font.
- Do NOT copy branding/assets verbatim; adapt the vibe to the new app goal.

Return ONLY valid JSON with this schema:
{
  "spoken": "short explanation for the user",
  "project_root": "relative folder name to create (kebab-case)",
  "files": [
    {"path": "relative/path/from/project_root", "content": "file contents"}
  ]
}

Output rules:
- Provide full file contents (not diffs).
- Use Vite + React + TypeScript defaults where reasonable.
- Include package.json, index.html, src/main.tsx, src/App.tsx.
- Ensure imports reference the modular structure (components/styles).
"""

SYSTEM_PRD = """You are a product engineer.
You will be given:
- product name
- product goal/description
- optional reference design snapshot

Your job is to write a Product Requirements Document (PRD) as Markdown.

Rules:
- Do NOT generate source code.
- Output MUST be a single Markdown document.
- Include: Vision, Target Users, User Stories, Scope (MVP vs later), Information Architecture, UI components list, Design Tokens proposal, Data model (if needed), Acceptance Criteria, and Build Plan (atomic steps).
- If a reference snapshot is provided, extract 'design DNA' and propose tokens and component structure accordingly.

Return ONLY valid JSON:
{
  "spoken": "short message",
  "prd_markdown": "..."
}
"""

def _openai_suggest(*, instruction: str, path: str, content: str, context: str = "") -> AgentSuggestion:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("openai python package is not installed") from exc

    s = settings_mod.settings

    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=s.openai_api_key)

    user_msg = f"Active file: {path}\n\nInstruction: {instruction}\n\nCurrent file content:\n{content}{context}"

    _throttle_llm_calls()

    resp = client.chat.completions.create(
        model=s.openai_chat_model,
        messages=[
            {"role": "system", "content": SYSTEM_PATCH},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )

    raw = resp.choices[0].message.content or "{}"
    data: dict[str, Any] = json.loads(raw)
    spoken = str(data.get("spoken") or "OK.")
    changes = data.get("changes") or []
    
    if not changes:
        raise RuntimeError("LLM returned no changes")

    log = f"provider=openai model={s.openai_chat_model}"
    return AgentSuggestion(spoken=spoken, log=log, changes=changes)


def _groq_suggest(*, instruction: str, path: str, content: str, context: str = "") -> AgentSuggestion:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("openai python package is not installed") from exc

    s = settings_mod.settings

    if not s.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    client = OpenAI(api_key=s.groq_api_key, base_url="https://api.groq.com/openai/v1")

    user_msg = f"Active file: {path}\n\nInstruction: {instruction}\n\nCurrent file content:\n{content}{context}"

    _throttle_llm_calls()

    resp = client.chat.completions.create(
        model=s.groq_chat_model,
        messages=[
            {"role": "system", "content": SYSTEM_PATCH},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )

    raw = resp.choices[0].message.content or "{}"
    data: dict[str, Any] = json.loads(raw)
    spoken = str(data.get("spoken") or "OK.")
    changes = data.get("changes") or []
    
    if not changes:
        raise RuntimeError("LLM returned no changes")

    log = f"provider=groq model={s.groq_chat_model}"
    return AgentSuggestion(spoken=spoken, log=log, changes=changes)


def _gemini_suggest(*, instruction: str, path: str, content: str, context: str = "") -> AgentSuggestion:
    s = settings_mod.settings
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    prompt = (
        f"{SYSTEM_PATCH}\n\n"
        f"Active file: {path}\n\nInstruction: {instruction}\n\nCurrent file content:\n{content}\n{context}"
    )

    data = _gemini_generate_json(model=s.gemini_chat_model, api_key=s.gemini_api_key, prompt=prompt)
    spoken = str(data.get("spoken") or "OK.")
    changes = data.get("changes") or []
    
    if not changes:
        raise RuntimeError("LLM returned no changes")

    log = f"provider=gemini model={s.gemini_chat_model}"
    return AgentSuggestion(spoken=spoken, log=log, changes=changes)


def _gemini_generate_json(*, model: str, api_key: str, prompt: str) -> dict[str, Any]:
    import urllib.request
    import urllib.error

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ]
        }
    ).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    _throttle_llm_calls()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(body or f"Gemini error ({exc.code})")

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text")
    if not text:
        raise RuntimeError("Gemini returned empty text")

    try:
        return json.loads(text)
    except Exception as exc:
        raise RuntimeError(f"Gemini returned non-JSON: {exc}")


def _safe_fetch_reference(ref_url: str) -> str:
    """Fetch a small, sanitized snapshot of a reference URL for 'design DNA' only.

    Cached to avoid repeated network calls when users retry.
    """
    ref_url = (ref_url or "").strip()
    if not ref_url:
        return ""

    now = time.time()
    cached = _REF_CACHE.get(ref_url)
    if cached and (now - cached[0]) < 10 * 60:
        return cached[1]

    u = urllib.parse.urlparse(ref_url)
    if u.scheme not in {"http", "https"}:
        return ""

    req = urllib.request.Request(
        ref_url,
        headers={
            "User-Agent": "voice-ide/1.0 (design-dna fetch)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:  # nosec - user supplied URL, but limited.
            ctype = str(resp.headers.get("Content-Type") or "")
            raw = resp.read(180_000)  # cap ~180KB
    except Exception:
        return ""

    if "text/html" not in ctype and "application/xhtml" not in ctype and ctype:
        # Only HTML-ish.
        return ""

    try:
        html = raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""

    # strip scripts/styles
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)

    # grab title + meta description
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:200]

    desc = ""
    m = re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        desc = re.sub(r"\s+", " ", m.group(1)).strip()[:280]

    # extract class/id tokens + inline style hints
    classes = re.findall(r"class=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
    class_tokens: list[str] = []
    for c in classes[:500]:
        for tok in re.split(r"\s+", c.strip()):
            if tok and tok not in class_tokens:
                class_tokens.append(tok)
            if len(class_tokens) >= 80:
                break
        if len(class_tokens) >= 80:
            break

    # --- CSS bridge: fetch a few linked stylesheets for better palette/font extraction ---
    stylesheet_hrefs = re.findall(
        r"<link[^>]+rel=[\"']stylesheet[\"'][^>]+href=[\"']([^\"']+)[\"']",
        html,
        flags=re.IGNORECASE,
    )
    css_texts: list[str] = []
    for href in stylesheet_hrefs[:6]:
        href = href.strip()
        if not href:
            continue
        css_url = urllib.parse.urljoin(ref_url, href)
        try:
            cu = urllib.parse.urlparse(css_url)
            if cu.scheme not in {"http", "https"}:
                continue

            req2 = urllib.request.Request(
                css_url,
                headers={
                    "User-Agent": "voice-ide/1.0 (design-dna fetch)",
                    "Accept": "text/css,*/*;q=0.1",
                },
                method="GET",
            )
            with urllib.request.urlopen(req2, timeout=6) as resp2:  # nosec
                ctype2 = str(resp2.headers.get("Content-Type") or "")
                raw2 = resp2.read(120_000)  # cap per CSS
            if "text/css" not in ctype2 and ctype2 and "css" not in ctype2:
                continue
            css = raw2.decode("utf-8", errors="ignore")
            css_texts.append(css)
            if sum(len(x) for x in css_texts) > 220_000:
                break
        except Exception:
            continue

    css_blob = "\n".join(css_texts)

    # crude palette: hex colors in HTML + CSS
    colors = re.findall(r"#[0-9a-fA-F]{3,8}", html + "\n" + css_blob)
    uniq_colors: list[str] = []
    for col in colors:
        col = col.lower()
        if col not in uniq_colors:
            uniq_colors.append(col)
        if len(uniq_colors) >= 24:
            break

    # fonts: detect google fonts links and font-family mentions
    gf_links = re.findall(r"<link[^>]+href=[\"']([^\"']*fonts\.googleapis\.com[^\"']+)[\"']", html, flags=re.IGNORECASE)
    gf_links += re.findall(r"@import\s+url\([\"']?([^\"')]*fonts\.googleapis\.com[^\"')]+)[\"']?\)", css_blob, flags=re.IGNORECASE)
    gf_links = [x.strip() for x in gf_links if x.strip()]
    # de-dup
    gf_uniq: list[str] = []
    for x in gf_links:
        if x not in gf_uniq:
            gf_uniq.append(x)
        if len(gf_uniq) >= 6:
            break

    font_families = re.findall(r"font-family\s*:\s*([^;}{]+)", (html + "\n" + css_blob), flags=re.IGNORECASE)
    fonts: list[str] = []
    for ff in font_families[:400]:
        ff = re.sub(r"\s+", " ", ff).strip()
        if ff and ff not in fonts:
            fonts.append(ff)
        if len(fonts) >= 12:
            break

    # svg: extract path 'd' values from inline SVGs
    svg_paths = re.findall(r"<path[^>]+d=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
    svg_paths = [p.strip() for p in svg_paths if p.strip()][:18]

    # svg: also try to fetch a few external .svg assets referenced in HTML/CSS
    svg_urls: list[str] = []

    # <img src="...svg">
    for s in re.findall(r"<img[^>]+src=[\"']([^\"']+\.svg[^\"']*)[\"']", html, flags=re.IGNORECASE):
        u2 = urllib.parse.urljoin(ref_url, s.strip())
        if u2 and u2 not in svg_urls:
            svg_urls.append(u2)
        if len(svg_urls) >= 4:
            break

    # css url(...svg)
    for s in re.findall(r"url\(([^)]+\.svg[^)]*)\)", css_blob, flags=re.IGNORECASE):
        s = s.strip().strip("\"'")
        if not s:
            continue
        u2 = urllib.parse.urljoin(ref_url, s)
        if u2 and u2 not in svg_urls:
            svg_urls.append(u2)
        if len(svg_urls) >= 6:
            break

    svg_assets: list[dict[str, Any]] = []
    for u2 in svg_urls:
        try:
            req3 = urllib.request.Request(
                u2,
                headers={
                    "User-Agent": "voice-ide/1.0 (design-dna fetch)",
                    "Accept": "image/svg+xml,*/*;q=0.1",
                },
                method="GET",
            )
            with urllib.request.urlopen(req3, timeout=6) as resp3:  # nosec
                ctype3 = str(resp3.headers.get("Content-Type") or "")
                raw3 = resp3.read(120_000)
            if ctype3 and "svg" not in ctype3:
                continue
            svg = raw3.decode("utf-8", errors="ignore")
            svg = svg.strip()
            # Extract some path data for inline reconstruction.
            paths = re.findall(r"<path[^>]+d=[\"']([^\"']+)[\"']", svg, flags=re.IGNORECASE)
            paths = [p.strip() for p in paths if p.strip()][:12]
            svg_assets.append({
                "url": u2,
                "path_samples": paths,
            })
        except Exception:
            continue

    snapshot = {
        "url": ref_url,
        "title": title,
        "description": desc,
        "sample_classes": class_tokens,
        "stylesheet_urls": [urllib.parse.urljoin(ref_url, h.strip()) for h in stylesheet_hrefs[:6] if h.strip()],
        "sample_colors": uniq_colors,
        "google_fonts_links": gf_uniq,
        "font_family_samples": fonts,
        "svg_path_samples": svg_paths,
        "svg_assets": svg_assets,
    }

    out = json.dumps(snapshot, ensure_ascii=False)
    _REF_CACHE[ref_url] = (time.time(), out)
    return out


def _is_rate_limited(exc: Exception) -> bool:
    s = str(exc)
    if "429" in s or "rate limit" in s.lower() or "ratelimit" in s.lower():
        return True
    # openai python client may attach status_code
    code = getattr(exc, "status_code", None)
    if code == 429:
        return True
    return False


def _scaffold_via_openai_compatible(*, base_url: str | None, api_key: str, model: str, name: str, goal: str, ref_url: str | None = None) -> ScaffoldResult:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("openai python package is not installed") from exc

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    ref_block = ""
    if ref_url:
        snap = _safe_fetch_reference(ref_url)
        if snap:
            ref_block = (
                "\nReference design snapshot (for style DNA only):\n"
                + snap
                + "\n"
            )
        else:
            ref_block = f"\nReference URL: {ref_url}\n"

    user_msg = f"App name: {name}\n\nGoal:\n{goal}\n{ref_block}"

    # Retry on provider 429 / rate limits (avoid "spam" failures)
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            _throttle_llm_calls()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_SCAFFOLD},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
            )
            last_exc = None
            break
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            if not _is_rate_limited(exc) or attempt >= 3:
                raise
            # exponential backoff
            time.sleep(0.8 * (2**attempt))

    if last_exc is not None:  # pragma: no cover
        raise last_exc

    raw = resp.choices[0].message.content or "{}"
    data: dict[str, Any] = json.loads(raw)

    spoken = str(data.get("spoken") or "OK.")
    project_root = str(data.get("project_root") or "").strip() or "app"

    files = data.get("files") or []
    if not isinstance(files, list) or not files:
        raise RuntimeError("LLM returned no files")

    ops: list[ScaffoldFile] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        p = str(f.get("path") or "").strip()
        c = str(f.get("content") or "")
        if not p or c == "":
            continue
        ops.append(ScaffoldFile(path=f"{project_root}/{p}", content=c))

    if not ops:
        raise RuntimeError("LLM returned empty file list")

    log = f"provider={settings_mod.settings.llm_provider} model={model} files={len(ops)}"
    return ScaffoldResult(spoken=spoken, log=log, project_root=project_root, ops=ops)


def scaffold_webapp(*, name: str, goal: str, ref_url: str | None = None) -> ScaffoldResult:
    s = settings_mod.settings
    prov = (s.llm_provider or "").lower()

    # Cache scaffold results briefly to prevent re-running the LLM when the user retries quickly.
    cache_key = json.dumps({"prov": prov, "model": getattr(s, f"{prov}_chat_model", None), "name": name, "goal": goal, "ref_url": ref_url or ""}, sort_keys=True)
    now = time.time()
    cached = _SCAFFOLD_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 90:
        return cached[1]
    if prov == "openai":
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        res = _scaffold_via_openai_compatible(
            base_url=None,
            api_key=s.openai_api_key,
            model=s.openai_chat_model,
            name=name,
            goal=goal,
            ref_url=ref_url,
        )
        _SCAFFOLD_CACHE[cache_key] = (time.time(), res)
        return res
    if prov == "groq":
        if not s.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        res = _scaffold_via_openai_compatible(
            base_url="https://api.groq.com/openai/v1",
            api_key=s.groq_api_key,
            model=s.groq_chat_model,
            name=name,
            goal=goal,
            ref_url=ref_url,
        )
        _SCAFFOLD_CACHE[cache_key] = (time.time(), res)
        return res
    if prov == "gemini":
        if not s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        ref_block = ""
        if ref_url:
            ref_block = (
                f"\nReference URL: {ref_url}\n"
                "If the URL is provided, infer its design DNA (layout, spacing, typography, vibe) and adapt it to the new app goal.\n"
            )

        prompt = f"{SYSTEM_SCAFFOLD}\n\nApp name: {name}\n\nGoal:\n{goal}\n{ref_block}"
        data = _gemini_generate_json(model=s.gemini_chat_model, api_key=s.gemini_api_key, prompt=prompt)

        spoken = str(data.get("spoken") or "OK.")
        project_root = str(data.get("project_root") or "").strip() or "app"

        files = data.get("files") or []
        if not isinstance(files, list) or not files:
            raise RuntimeError("LLM returned no files")

        ops: list[ScaffoldFile] = []
        for f in files:
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "").strip()
            c = str(f.get("content") or "")
            if not p or c == "":
                continue
            ops.append(ScaffoldFile(path=f"{project_root}/{p}", content=c))

        if not ops:
            raise RuntimeError("LLM returned empty file list")

        log = f"provider=gemini model={s.gemini_chat_model} files={len(ops)}"
        res = ScaffoldResult(spoken=spoken, log=log, project_root=project_root, ops=ops)
        _SCAFFOLD_CACHE[cache_key] = (time.time(), res)
        return res

    raise RuntimeError(f"LLM_PROVIDER '{s.llm_provider}' not implemented yet")


def _compact_reference_snapshot(snap_json: str) -> str:
    """Reduce snapshot size to stay rate-limit/token friendly."""
    try:
        data = json.loads(snap_json)
    except Exception:
        return snap_json[:6000]

    keep = {
        "url": data.get("url"),
        "title": data.get("title"),
        "description": data.get("description"),
        "sample_colors": (data.get("sample_colors") or [])[:10],
        "google_fonts_links": (data.get("google_fonts_links") or [])[:3],
        "font_family_samples": (data.get("font_family_samples") or [])[:6],
        "stylesheet_urls": (data.get("stylesheet_urls") or [])[:3],
    }
    # summarize svg assets without huge payloads
    svg_assets = data.get("svg_assets") or []
    if isinstance(svg_assets, list):
        keep["svg_assets_count"] = len(svg_assets)
        keep["svg_path_samples_count"] = len(data.get("svg_path_samples") or [])
    return json.dumps(keep, ensure_ascii=False)[:6000]


def generate_prd(*, name: str, goal: str, ref_url: str | None = None) -> dict[str, str]:
    s = settings_mod.settings
    prov = (s.llm_provider or "").lower()

    # short cache to avoid repeated PRD generation on retries
    cache_key = json.dumps({"prov": prov, "model": getattr(s, f"{prov}_chat_model", None), "name": name, "goal": goal, "ref_url": ref_url or ""}, sort_keys=True)
    now = time.time()
    cached = _PRD_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 5 * 60:
        return cached[1]

    ref_block = ""
    if ref_url:
        snap = _safe_fetch_reference(ref_url)
        if snap:
            ref_block = "\nReference design snapshot:\n" + _compact_reference_snapshot(snap) + "\n"
        else:
            ref_block = f"\nReference URL: {ref_url}\n"

    prompt = f"{SYSTEM_PRD}\n\nProduct name: {name}\n\nGoal:\n{goal}\n{ref_block}"

    # Use the same providers, but require JSON output.
    if prov in {"openai", "groq"}:
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("openai python package is not installed") from exc

        if prov == "openai":
            if not s.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            client = OpenAI(api_key=s.openai_api_key)
            model = s.openai_chat_model
        else:
            if not s.groq_api_key:
                raise RuntimeError("GROQ_API_KEY is not set")
            client = OpenAI(api_key=s.groq_api_key, base_url="https://api.groq.com/openai/v1")
            model = s.groq_chat_model

        # retry on 429 with longer backoff + jitter
        last_exc: Exception | None = None
        for attempt in range(7):
            try:
                _throttle_llm_calls()
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PRD},
                        {"role": "user", "content": f"Product name: {name}\n\nGoal:\n{goal}\n{ref_block}"},
                    ],
                    response_format={"type": "json_object"},
                )
                last_exc = None
                break
            except Exception as exc:  # pragma: no cover
                last_exc = exc
                if not _is_rate_limited(exc) or attempt >= 6:
                    raise
                # 2s,4s,8s,16s... capped; add small deterministic jitter
                base = min(20.0, 2.0 * (2**attempt))
                jitter = (attempt % 3) * 0.35
                time.sleep(base + jitter)

        if last_exc is not None:  # pragma: no cover
            raise last_exc

        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        out = {
            "spoken": str(data.get("spoken") or "OK."),
            "prd_markdown": str(data.get("prd_markdown") or ""),
            "log": f"provider={prov} model={model}",
        }
        _PRD_CACHE[cache_key] = (time.time(), out)
        return out

    if prov == "gemini":
        if not s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        data = _gemini_generate_json(model=s.gemini_chat_model, api_key=s.gemini_api_key, prompt=prompt)
        out = {
            "spoken": str(data.get("spoken") or "OK."),
            "prd_markdown": str(data.get("prd_markdown") or ""),
            "log": f"provider=gemini model={s.gemini_chat_model}",
        }
        _PRD_CACHE[cache_key] = (time.time(), out)
        return out

    raise RuntimeError(f"LLM_PROVIDER '{s.llm_provider}' not implemented yet")


def suggest(*, instruction: str, path: str, content: str, file_tree: list[str] = None, relevant_files: dict[str, str] = None) -> AgentSuggestion:
    if not instruction.strip():
        return AgentSuggestion(
            spoken="Sepertinya kamu belum memberikan instruksi. Apa yang ingin kamu ubah?",
            log="Instruction was empty.",
            changes=[]
        )

    # Format context
    context = ""
    if file_tree:
        context += f"\n\nProject file tree:\n{json.dumps(file_tree, indent=2)}\n"
    if relevant_files:
        context += "\n\nKey project files content:\n"
        for fpath, fcontent in relevant_files.items():
            context += f"--- {fpath} ---\n{fcontent}\n\n"

    prov = (settings_mod.settings.llm_provider or "").lower()
    if prov == "openai":
        return _openai_suggest(instruction=instruction, path=path, content=content, context=context)
    if prov == "groq":
        return _groq_suggest(instruction=instruction, path=path, content=content, context=context)
    if prov == "gemini":
        return _gemini_suggest(instruction=instruction, path=path, content=content, context=context)

    raise RuntimeError(f"LLM_PROVIDER '{settings_mod.settings.llm_provider}' not implemented yet")
