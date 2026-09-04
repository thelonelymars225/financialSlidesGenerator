import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import psycopg
from fastapi.responses import JSONResponse

from financial_slides_api.services.generation import _analysis_provider_for_generation


def live() -> JSONResponse:
    """Report process liveness without checking external dependencies."""

    return JSONResponse({"status": "ok", "service": "api"})


def _sqlite_path_is_ready(database_path: str) -> bool:
    path = Path(database_path)
    if not path.exists():
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return parent.is_dir() and os.access(parent, os.W_OK)

    try:
        with sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=1) as connection:
            connection.execute("SELECT 1").fetchone()
    except (OSError, sqlite3.Error):
        return False
    return True


def _storage_readiness(environment: Mapping[str, str]) -> tuple[str, bool]:
    adapter = environment.get("FINANCIAL_SLIDES_STORE", "memory").strip().lower()
    if adapter == "memory":
        return adapter, True
    if adapter == "sqlite":
        database_path = environment.get(
            "FINANCIAL_SLIDES_JOB_DB", ".data/extraction-jobs.sqlite3"
        ).strip()
        return adapter, bool(database_path) and _sqlite_path_is_ready(database_path)
    if adapter == "postgres":
        database_url = environment.get("DATABASE_URL", "").strip()
        if not database_url:
            return adapter, False
        try:
            with psycopg.connect(database_url, connect_timeout=2) as connection:
                connection.execute("SELECT 1").fetchone()
        except (OSError, psycopg.Error):
            return adapter, False
        return adapter, True
    return adapter or "unconfigured", False


def ready(environment: Mapping[str, str] = os.environ) -> JSONResponse:
    """Check required provider configuration and configured job storage."""

    configured_provider = environment.get("MODEL_PROVIDER", "deterministic").strip().lower()
    provider_name = configured_provider or "deterministic"
    model_name = environment.get("MODEL_NAME", "").strip()
    if provider_name == "deepseek" and not model_name:
        model_name = "deepseek-v4-flash"
    elif provider_name == "deterministic":
        model_name = "fixture-v1"

    try:
        provider = _analysis_provider_for_generation(environment)
        provider_name = getattr(provider, "name", provider_name)
        model_name = getattr(provider, "model", model_name)
        analysis_ready = True
    except (OSError, RuntimeError, ValueError):
        analysis_ready = False

    storage_adapter, storage_ready = _storage_readiness(environment)
    is_ready = analysis_ready and storage_ready

    return JSONResponse(
        {
            "status": "ok" if is_ready else "not_ready",
            "service": "api",
            "analysis_provider": provider_name,
            "analysis_model": model_name or "unconfigured",
            "analysis_ready": analysis_ready,
            "storage_adapter": storage_adapter,
            "storage_ready": storage_ready,
        },
        status_code=200 if is_ready else 503,
    )


def health(environment: Mapping[str, str] = os.environ) -> JSONResponse:
    """Backward-compatible readiness entry point."""

    return ready(environment)
