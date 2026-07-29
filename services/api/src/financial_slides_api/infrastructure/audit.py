"""Metadata-only security audit logging."""

import logging
from hashlib import sha256

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
