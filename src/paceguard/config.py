"""Configuration via environment variables (12-factor)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "PaceGuard"
    version: str = "1.0.0"
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./paceguard.db")
    )
    #: Demo mode lets the bundled dashboard pick a tenant with `X-Account-Id`
    #: instead of a real API key. Never enable this on the public internet.
    demo_mode: bool = field(default_factory=lambda: _bool("PACEGUARD_DEMO", True))
    seed_demo_data: bool = field(default_factory=lambda: _bool("PACEGUARD_SEED", True))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    #: Campaigns are evaluated in this timezone's calendar day. UTC keeps the
    #: demo deterministic; DeltaX accounts would store their own tz.
    accounting_timezone: str = field(
        default_factory=lambda: os.getenv("ACCOUNTING_TZ", "UTC")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
