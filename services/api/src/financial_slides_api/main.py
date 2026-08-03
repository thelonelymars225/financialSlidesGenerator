import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from financial_slides_api.generation import router as generation_router
from financial_slides_api.jobs import router as jobs_router
from financial_slides_api.operations import health
from financial_slides_api.privacy import router as privacy_router

LOCAL_WEB_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def cors_origins_from_environment(environment: Mapping[str, str] = os.environ) -> list[str]:
    raw = environment.get("CORS_ALLOWED_ORIGINS")
    if raw is None:
        return list(LOCAL_WEB_ORIGINS)

    origins: list[str] = []
    for candidate in raw.split(","):
        origin = candidate.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(f"invalid CORS origin: {origin}")
        if origin not in origins:
            origins.append(origin)
    return origins


def create_app(environment: Mapping[str, str] = os.environ) -> FastAPI:
    application = FastAPI(title="financialSlidesGenerator API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins_from_environment(environment),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.get("/health", tags=["operations"])(health)
    application.include_router(jobs_router, prefix="/api")
    application.include_router(generation_router, prefix="/api")
    application.include_router(privacy_router, prefix="/api")
    return application


app = create_app()
