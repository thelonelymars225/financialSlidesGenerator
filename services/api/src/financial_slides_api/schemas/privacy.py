"""Public privacy and retention response shapes."""

from pydantic import BaseModel

from financial_slides_api.services.privacy import RetentionPolicy


class RetentionPolicyResponse(BaseModel):
    source_retention_hours: int
    artifact_retention_hours: int

    @classmethod
    def from_policy(cls, policy: RetentionPolicy) -> "RetentionPolicyResponse":
        return cls(
            source_retention_hours=policy.source_hours,
            artifact_retention_hours=policy.artifact_hours,
        )
