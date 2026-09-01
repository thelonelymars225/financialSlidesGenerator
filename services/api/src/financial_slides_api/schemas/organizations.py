from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    role: str
    hosted_ai_enabled: bool
    created_at: datetime
