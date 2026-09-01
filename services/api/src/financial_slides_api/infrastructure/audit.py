"""Metadata-only security audit logging."""

import logging
import os
from hashlib import sha256
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger("financial_slides.audit")


class MetadataAuditLogger:
    def record(
        self,
        action: str,
        resource_id: str,
        owner_id: str | None,
        *,
        deleted_count: int = 0,
    ) -> None:
        actor_hash = sha256((owner_id or "system").encode()).hexdigest()[:16]
        logger.info(
            "privacy_event action=%s resource_id=%s actor_hash=%s deleted_count=%d",
            action,
            resource_id,
            actor_hash,
            deleted_count,
        )


class NullAuditSink:
    def record(
        self,
        action: str,
        resource_id: str,
        owner_id: str | None,
        *,
        deleted_count: int = 0,
    ) -> None:
        del action, resource_id, owner_id, deleted_count


class PostgresAuditSink:
    """Append-only metadata audit events; source content is never accepted."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def record(
        self,
        action: str,
        resource_id: str,
        owner_id: str | None,
        *,
        deleted_count: int = 0,
    ) -> None:
        def uuid_or_none(value: str | None) -> str | None:
            try:
                return str(UUID(value or ""))
            except ValueError:
                return None

        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                insert into financial_slides.audit_events (
                    organization_id, actor_id, action, resource_type,
                    resource_id, outcome, metadata
                ) values (%s, null, %s, 'extraction_job', %s, 'allowed', %s)
                """,
                (
                    uuid_or_none(owner_id),
                    action,
                    uuid_or_none(resource_id),
                    Jsonb({"deleted_count": deleted_count}),
                ),
            )


def configured_audit_sink():
    database_url = os.getenv("DATABASE_URL", "")
    if os.getenv("FINANCIAL_SLIDES_STORE") == "postgres" and database_url:
        return PostgresAuditSink(database_url)
    return MetadataAuditLogger()
