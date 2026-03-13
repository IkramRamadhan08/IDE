from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


# Load ~/voice-ide/.env (repo root; two levels above this file)
ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


def load_env() -> None:
    # override=True so updates to .env take effect without restarting
    load_dotenv(ENV_PATH, override=True)


class Settings(BaseModel):
    default_workspace: str | None = None

    stt_provider: str = "groq"
    llm_provider: str = "openai"
    tts_provider: str = "pyttsx3"

    groq_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    elevenlabs_api_key: str | None = None

    groq_whisper_model: str = "whisper-large-v3-turbo"
    groq_chat_model: str = "llama-3.1-8b-instant"

    openai_chat_model: str = "gpt-4o-mini"
    gemini_chat_model: str = "gemini-1.5-flash"


def load_settings() -> Settings:
    # IMPORTANT: read env vars at load time (not at class definition time)
    load_env()

    def g(key: str, default: str | None = None) -> str | None:
        v = os.getenv(key)
        if v is None:
            return default
        return v

    return Settings(
        default_workspace=(g("DEFAULT_WORKSPACE", "") or "").strip() or None,
        stt_provider=str(g("STT_PROVIDER", "groq")),
        llm_provider=str(g("LLM_PROVIDER", "openai")),
        tts_provider=str(g("TTS_PROVIDER", "pyttsx3")),
        groq_api_key=g("GROQ_API_KEY"),
        openai_api_key=g("OPENAI_API_KEY"),
        gemini_api_key=g("GEMINI_API_KEY"),
        elevenlabs_api_key=g("ELEVENLABS_API_KEY"),
        groq_whisper_model=str(g("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")),
        groq_chat_model=str(g("GROQ_CHAT_MODEL", "llama-3.1-8b-instant")),
        openai_chat_model=str(g("OPENAI_CHAT_MODEL", "gpt-4o-mini")),
        gemini_chat_model=str(g("GEMINI_CHAT_MODEL", "gemini-1.5-flash")),
    )


# mutable singleton (reloadable)
settings: Settings = load_settings()
