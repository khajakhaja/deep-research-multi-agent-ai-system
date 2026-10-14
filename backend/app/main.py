"""Backend FastAPI application."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import apply_langsmith_env, get_settings, validate_startup_settings
from app.database.session import init_db
from app.logging_config import configure_logging, get_logger

logger = get_logger("app.main")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    apply_langsmith_env(settings)

    problems = validate_startup_settings(settings)
    for message in problems:
        logger.warning("Startup configuration issue: %s", message)

    app = FastAPI(
        title="Deep Research AI - Multi-Agent Research Assistant",
        description="Collaborative multi-agent research workflow with verifiable citations.",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Starting backend")
        init_db()

    return app


app = create_app()
