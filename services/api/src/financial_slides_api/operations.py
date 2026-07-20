def health() -> dict[str, str]:
    """Return a dependency-free liveness response."""
    return {"status": "ok", "service": "api"}
