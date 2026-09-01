"""Stable, data-only workflow contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionWorkflowInput:
    job_id: str
    organization_id: str
