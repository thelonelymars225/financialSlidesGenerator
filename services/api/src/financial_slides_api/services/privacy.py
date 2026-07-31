"""Configurable secure defaults for source and generated-output retention."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

DEFAULT_SOURCE_RETENTION_HOURS = 24
DEFAULT_ARTIFACT_RETENTION_HOURS = 24
MAX_RETENTION_HOURS = 24 * 365


def _retention_hours(environment: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(environment.get(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not 1 <= value <= MAX_RETENTION_HOURS:
        raise RuntimeError(f"{name} must be between 1 and {MAX_RETENTION_HOURS}")
    return value


@dataclass(frozen=True)
class RetentionPolicy:
    source_hours: int = DEFAULT_SOURCE_RETENTION_HOURS
    artifact_hours: int = DEFAULT_ARTIFACT_RETENTION_HOURS

    def source_cutoff(self, now: datetime) -> datetime:
        return now - timedelta(hours=self.source_hours)

    def artifact_cutoff(self, now: datetime) -> datetime:
        return now - timedelta(hours=self.artifact_hours)


def retention_policy_from_environment(
    environment: Mapping[str, str] = os.environ,
) -> RetentionPolicy:
    return RetentionPolicy(
        source_hours=_retention_hours(
            environment,
            "FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS",
            DEFAULT_SOURCE_RETENTION_HOURS,
        ),
        artifact_hours=_retention_hours(
            environment,
            "FINANCIAL_SLIDES_ARTIFACT_RETENTION_HOURS",
            DEFAULT_ARTIFACT_RETENTION_HOURS,
        ),
    )


@lru_cache(maxsize=1)
def get_retention_policy() -> RetentionPolicy:
    return retention_policy_from_environment()
