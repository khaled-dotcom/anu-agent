from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _list(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


@dataclass
class Settings:
    # Groq — see GUIDE-TOKENS.md
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # Facebook Messenger
    fb_verify_token: str = os.getenv("FB_VERIFY_TOKEN", "")
    fb_page_token: str = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
    fb_app_secret: str = os.getenv("FB_APP_SECRET", "")
    fb_api_version: str = os.getenv("FB_API_VERSION", "v21.0")

    # Ops
    allowed_origins: list[str] = field(default_factory=lambda: _list("ALLOWED_ORIGINS"))
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "12"))
    port: int = int(os.getenv("PORT", "8000"))

    @property
    def facebook_enabled(self) -> bool:
        return bool(self.fb_verify_token and self.fb_page_token)


settings = Settings()
