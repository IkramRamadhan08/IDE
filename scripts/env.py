#!/usr/bin/env python3
"""Simple .env manager for ~/voice-ide

Goal: stop manually editing ~/voice-ide/.env.

Commands:
  env.py init
  env.py get KEY
  env.py set KEY VALUE
  env.py unset KEY
  env.py wizard

Notes:
- Preserves comments and ordering as much as possible.
- Only touches the root .env: ~/voice-ide/.env
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LINE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def ensure_env_exists() -> None:
    if ENV_PATH.exists():
        return
    if not EXAMPLE_PATH.exists():
        die(f"Missing {EXAMPLE_PATH}. Can't init.")
    shutil.copyfile(EXAMPLE_PATH, ENV_PATH)
    print(f"Created {ENV_PATH} from .env.example")


def read_lines() -> list[str]:
    if not ENV_PATH.exists():
        return []
    return ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)


def write_lines(lines: list[str]) -> None:
    ENV_PATH.write_text("".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def find_key_index(lines: list[str], key: str) -> int | None:
    for i, line in enumerate(lines):
        m = LINE_RE.match(line.rstrip("\n"))
        if m and m.group("key") == key:
            return i
    return None


def set_key(key: str, value: str) -> None:
    if not KEY_RE.match(key):
        die(f"Invalid key: {key}")

    # Quote if it contains spaces or # or starts/ends with whitespace
    needs_quotes = (
        value != value.strip()
        or any(ch in value for ch in [" ", "#"])
        or "\t" in value
        or "\n" in value
        or '"' in value
    )
    if needs_quotes:
        # minimal escaping
        v = value.replace("\\", "\\\\").replace('"', '\\"')
        value_out = f'"{v}"'
    else:
        value_out = value

    ensure_env_exists()
    lines = read_lines()
    idx = find_key_index(lines, key)
    new_line = f"{key}={value_out}\n"

    if idx is None:
        # Append with a newline separation if file doesn't end with one
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        lines.append(new_line)
    else:
        lines[idx] = new_line

    write_lines(lines)
    print(f"Set {key} in {ENV_PATH}")


def unset_key(key: str) -> None:
    if not ENV_PATH.exists():
        die(f"{ENV_PATH} does not exist")
    lines = read_lines()
    idx = find_key_index(lines, key)
    if idx is None:
        print(f"Key not found: {key}")
        return
    lines.pop(idx)
    write_lines(lines)
    print(f"Removed {key} from {ENV_PATH}")


def get_key(key: str) -> None:
    if not ENV_PATH.exists():
        die(f"{ENV_PATH} does not exist")
    for line in read_lines():
        m = LINE_RE.match(line.rstrip("\n"))
        if m and m.group("key") == key:
            print(m.group("value"))
            return
    raise SystemExit(1)


def prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    if default:
        suffix = f" [{default}]"
    else:
        suffix = ""

    if secret:
        import getpass

        v = getpass.getpass(f"{label}{suffix}: ")
    else:
        v = input(f"{label}{suffix}: ")

    if v == "" and default is not None:
        return default
    return v


def wizard() -> None:
    print("Voice IDE .env wizard (writes to ~/voice-ide/.env)")
    ensure_env_exists()

    # Common knobs
    default_workspace = prompt("DEFAULT_WORKSPACE (empty = dialog)", default="")
    stt = prompt("STT_PROVIDER", default="groq")
    llm = prompt("LLM_PROVIDER", default="openai")
    tts = prompt("TTS_PROVIDER", default="pyttsx3")

    # Keys
    groq_key = prompt("GROQ_API_KEY", default="", secret=True)
    openai_key = prompt("OPENAI_API_KEY", default="", secret=True)
    gemini_key = prompt("GEMINI_API_KEY", default="", secret=True)
    eleven_key = prompt("ELEVENLABS_API_KEY", default="", secret=True)

    # Models
    groq_whisper = prompt("GROQ_WHISPER_MODEL", default="whisper-large-v3-turbo")
    openai_model = prompt("OPENAI_CHAT_MODEL", default="gpt-4o-mini")
    gemini_model = prompt("GEMINI_CHAT_MODEL", default="gemini-1.5-flash")

    # Wakeword
    wake_word = prompt('WAKE_WORD', default='Halo Raka')

    set_key("DEFAULT_WORKSPACE", default_workspace)
    set_key("STT_PROVIDER", stt)
    set_key("LLM_PROVIDER", llm)
    set_key("TTS_PROVIDER", tts)

    set_key("GROQ_API_KEY", groq_key)
    set_key("OPENAI_API_KEY", openai_key)
    set_key("GEMINI_API_KEY", gemini_key)
    set_key("ELEVENLABS_API_KEY", eleven_key)

    set_key("GROQ_WHISPER_MODEL", groq_whisper)
    set_key("OPENAI_CHAT_MODEL", openai_model)
    set_key("GEMINI_CHAT_MODEL", gemini_model)

    set_key("WAKE_WORD", wake_word)

    print("Done.")


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        die("Usage: env.py <init|get|set|unset|wizard> [...]")

    cmd = argv[1]
    if cmd == "init":
        ensure_env_exists()
        return
    if cmd == "wizard":
        wizard()
        return
    if cmd == "get":
        if len(argv) != 3:
            die("Usage: env.py get KEY")
        get_key(argv[2])
        return
    if cmd == "set":
        if len(argv) < 4:
            die("Usage: env.py set KEY VALUE")
        key = argv[2]
        value = " ".join(argv[3:])
        set_key(key, value)
        return
    if cmd == "unset":
        if len(argv) != 3:
            die("Usage: env.py unset KEY")
        unset_key(argv[2])
        return

    die(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main(sys.argv)
