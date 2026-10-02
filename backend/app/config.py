"""Settings, read from environment variables or a .env file at the repo root.

Every setting can be given as RENOVAI_<NAME> (e.g. RENOVAI_AI_MODE=live). The two API
keys are also read under their usual names, FAL_KEY and ANTHROPIC_API_KEY. A real
environment variable wins over the same line in .env.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

REPO = Path(__file__).resolve().parents[2]
ALIASES = {"fal_key": ("FAL_KEY",), "anthropic_api_key": ("ANTHROPIC_API_KEY",)}


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_dir: Path = REPO / "data"
    # "mock" runs the whole flow offline with canned detections and suggestions;
    # "live" calls the hosted models below.
    ai_mode: Literal["mock", "live"] = "mock"

    fal_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    # How much Claude thinks before answering: low | medium | high. Empty = the model default.
    anthropic_effort: str = "low"
    anthropic_base_url: str = "https://api.anthropic.com"
    fal_base_url: str = "https://fal.run"
    sam3_endpoint: str = "fal-ai/sam-3/image"
    sam3_min_score: float = 0.35

    staff_token: str = "change-me"
    max_upload_mb: int = 25
    render_max_side: int = 2048
    # Price list in catalog/kober/data/. Empty = prices.json if the team's sheet has been
    # imported (make prices), otherwise the placeholder list.
    price_file: str = ""
    # The team's Google Sheet (shared "anyone with the link can view"); staff can import it from /#/staff.
    price_sheet_url: str = ""
    # Public address of the app, used in WhatsApp share links. Empty = the address the request came in on.
    public_url: str = ""

    @classmethod
    def from_env(cls, env_file: Path | None = REPO / ".env") -> "Settings":
        values: dict[str, str] = {}
        if env_file is not None and env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
        values.update(os.environ)
        data: dict[str, str] = {}
        for name in cls.model_fields:
            for key in (f"RENOVAI_{name.upper()}", *ALIASES.get(name, ())):
                if values.get(key):
                    data[name] = values[key]
                    break
        return cls(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
