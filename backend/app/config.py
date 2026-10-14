"""Application configuration.

All configuration is read from environment variables (and an optional ``.env``
file) via :class:`pydantic_settings.BaseSettings`. Secrets are never hardcoded
and are never written back to disk by the application.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ LLM
    openai_api_key: Optional[str] = Field(default=None)
    openai_model: str = Field(default="gpt-4o-mini")
    openai_base_url: Optional[str] = Field(default=None)
    openai_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    # --------------------------------------------------------------- Search
    tavily_api_key: Optional[str] = Field(default=None)
    search_max_results: int = Field(default=5, ge=1, le=20)

    # ------------------------------------------------------------- Database
    database_url: str = Field(default="sqlite:///./data/research.db")

    # ----------------------------------------------------- Workflow limits
    max_research_tasks: int = Field(default=5, ge=1, le=12)
    max_search_requests_per_run: int = Field(default=25, ge=1, le=100)
    max_page_fetches_per_run: int = Field(default=30, ge=1, le=150)
    max_research_retries: int = Field(default=1, ge=0, le=5)
    max_review_retries: int = Field(default=1, ge=0, le=5)
    request_timeout_seconds: int = Field(default=30, ge=5, le=180)
    run_timeout_seconds: int = Field(default=600, ge=30, le=3600)

    # ------------------------------------------------------- Input guard rails
    max_question_length: int = Field(default=1000, ge=20, le=5000)
    min_question_length: int = Field(default=10, ge=3, le=100)

    # ------------------------------------------------------------- Backend
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000, ge=1, le=65535)
    cors_allow_origins: str = Field(
        default="http://localhost:8501,http://127.0.0.1:8501"
    )
    backend_base_url: str = Field(default="http://localhost:8000")

    # ------------------------------------------------------------- Logging
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    # ------------------------------------------------------------ LangSmith
    langsmith_tracing: bool = Field(default=False)
    langsmith_api_key: Optional[str] = Field(default=None)
    langsmith_project: str = Field(default="deep-research-ai")
    langchain_tracing_v2: bool = Field(default=False)
    langchain_api_key: Optional[str] = Field(default=None)
    langchain_project: str = Field(default="deep-research-ai")

    # ------------------------------------------------------------ Validators
    @field_validator("openai_base_url", "tavily_api_key", "openai_api_key", mode="before")
    @classmethod
    def _blank_to_none(cls, value):  # noqa: ANN001
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _default_database_url(cls, value):  # noqa: ANN001
        if isinstance(value, str) and not value.strip():
            return "sqlite:///./data/research.db"
        return value

    # ------------------------------------------------------------ Properties
    @property
    def cors_origins_list(self) -> List[str]:
        """Return CORS origins as a clean list."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def search_configured(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()


def validate_startup_settings(settings: Settings) -> List[str]:
    """Return a list of human-readable configuration problems.

    An empty list means the application is fully configured. Missing optional
    integrations are reported as warnings rather than fatal errors so the API
    can still start and serve health checks.
    """
    problems: List[str] = []

    if not settings.llm_configured:
        problems.append(
            "OPENAI_API_KEY is not set. Research runs will fail until an "
            "OpenAI-compatible API key is configured."
        )
    if not settings.search_configured:
        problems.append(
            "TAVILY_API_KEY is not set. Web research will fail until a Tavily "
            "API key is configured."
        )
    if settings.langsmith_tracing and not settings.langsmith_api_key:
        problems.append(
            "LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty. Tracing "
            "will be disabled."
        )
    return problems


def apply_langsmith_env(settings: Settings) -> None:
    """Export LangSmith/LangChain environment variables when enabled.

    Only applied when tracing is explicitly enabled and a key is present.
    """
    import os

    tracing_enabled = settings.langsmith_tracing or settings.langchain_tracing_v2
    api_key = settings.langsmith_api_key or settings.langchain_api_key
    if not tracing_enabled or not api_key:
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_API_KEY"] = api_key
    project = settings.langsmith_project or settings.langchain_project
    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGCHAIN_PROJECT"] = project
