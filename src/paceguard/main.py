"""Application factory and wiring."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from paceguard.api import alerts, campaigns, pacing, spend, system
from paceguard.config import Settings, get_settings
from paceguard.db import SessionLocal, init_db
from paceguard.logging_setup import configure_logging, request_logging_middleware
from paceguard.metrics import METRICS
from paceguard.seed import ensure_seeded

logger = logging.getLogger("paceguard")
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        METRICS.inc("app_starts_total")
        if settings.seed_demo_data:
            with SessionLocal() as session:
                if ensure_seeded(session):
                    logger.info("demo_data_seeded", extra={"tenant_id": "-"})
        logger.info(
            "app_started",
            extra={"version": settings.version, "demo_mode": settings.demo_mode},
        )
        yield
        logger.info("app_stopped")

    app = FastAPI(
        title="PaceGuard",
        version=settings.version,
        description=(
            "Budget pacing and spend governance for multi-tenant ad operations. "
            "Every monetary value is integer minor units (paise/cents)."
        ),
        lifespan=lifespan,
    )

    # Routers depend on ``get_settings``; bind that dependency to *this* app's
    # settings so a test/prod instance can differ from the process defaults.
    app.dependency_overrides[get_settings] = lambda: settings

    app.middleware("http")(request_logging_middleware)

    app.include_router(system.router)
    app.include_router(campaigns.router, prefix="/api/v1")
    app.include_router(spend.router, prefix="/api/v1")
    app.include_router(pacing.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")

    if WEB_DIR.is_dir():
        # The Vue dashboard is same-origin with the API, so there is no CORS
        # policy to get wrong and no token in browser storage.
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    else:  # pragma: no cover - only when the repo is trimmed
        logger.warning("web_dir_missing", extra={"path": str(WEB_DIR)})

    return app


app = create_app()
