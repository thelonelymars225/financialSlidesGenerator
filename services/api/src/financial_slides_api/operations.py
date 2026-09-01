import os
from collections.abc import Mapping

from fastapi.responses import JSONResponse

from financial_slides_api.services.generation import _analysis_provider_for_generation


def health(environment: Mapping[str, str] = os.environ) -> JSONResponse:
    """Return liveness plus non-secret analysis-provider readiness."""

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
        ready = True
    except RuntimeError:
        ready = False

    return JSONResponse(
        {
            "status": "ok" if ready else "not_ready",
            "service": "api",
            "analysis_provider": provider_name,
            "analysis_model": model_name or "unconfigured",
            "analysis_ready": ready,
        },
        status_code=200 if ready else 503,
    )
