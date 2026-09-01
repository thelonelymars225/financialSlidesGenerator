"""Atomic tenant quotas for expensive or write-heavy operations."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Protocol

import psycopg
from fastapi import Depends, HTTPException, status

from financial_slides_api.security import Identity, RequestIdentity, get_security_settings


class QuotaEnforcer(Protocol):
    def consume(self, organization_id: str, quota_name: str, limit: int) -> bool: ...


class UnlimitedDevelopmentQuota:
    def consume(self, organization_id: str, quota_name: str, limit: int) -> bool:
        del organization_id, quota_name, limit
        return True


class PostgresQuotaEnforcer:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def consume(self, organization_id: str, quota_name: str, limit: int) -> bool:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                "select financial_slides.consume_hourly_quota(%s, %s, %s)",
                (organization_id, quota_name, limit),
            ).fetchone()
        return bool(row and row[0])


@lru_cache(maxsize=1)
def get_quota_enforcer() -> QuotaEnforcer:
    settings = get_security_settings()
    if not settings.auth_required:
        return UnlimitedDevelopmentQuota()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for production quotas")
    return PostgresQuotaEnforcer(settings.database_url)


def require_job_submission_quota(
    identity: Identity,
    enforcer: QuotaEnforcer = Depends(get_quota_enforcer),
) -> RequestIdentity:
    raw_limit = os.getenv("JOB_SUBMISSIONS_PER_ORG_HOUR", "60")
    try:
        limit = int(raw_limit)
    except ValueError as error:
        raise RuntimeError("JOB_SUBMISSIONS_PER_ORG_HOUR must be an integer") from error
    if limit < 1:
        raise RuntimeError("JOB_SUBMISSIONS_PER_ORG_HOUR must be positive")
    if not enforcer.consume(identity.organization_id, "job_submissions", limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="organization job submission quota exceeded",
            headers={"Retry-After": "3600"},
        )
    return identity


SubmissionIdentity = Annotated[RequestIdentity, Depends(require_job_submission_quota)]
