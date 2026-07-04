"""Environment-driven configuration for the sokol bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_user_ids: frozenset[int]
    ollama_host: str = "http://localhost:11434"
    chat_model: str = "qwen3:30b"
    embed_model: str = "nomic-embed-text"
    private_dir: Path = field(default_factory=lambda: REPO_ROOT / ".private")
    output_dir: Path = field(default_factory=lambda: REPO_ROOT / "output")
    # Fetched JD text shorter than this is treated as a failed extraction
    # (login walls and bot blocks usually yield a short stub page).
    min_jd_chars: int = 400


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    raw_ids = os.environ.get("ALLOWED_USER_IDS", "").strip()
    if not raw_ids:
        raise SystemExit(
            "ALLOWED_USER_IDS is not set. Add your Telegram user id to .env "
            "(message @userinfobot on Telegram to find it)."
        )
    allowed = frozenset(int(part) for part in raw_ids.replace(",", " ").split())

    return Config(
        telegram_token=token,
        allowed_user_ids=allowed,
        ollama_host=os.environ.get("OLLAMA_HOST", Config.ollama_host),
        chat_model=os.environ.get("SOKOL_CHAT_MODEL", Config.chat_model),
        embed_model=os.environ.get("SOKOL_EMBED_MODEL", Config.embed_model),
    )
