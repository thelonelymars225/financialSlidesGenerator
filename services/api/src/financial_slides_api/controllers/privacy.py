"""HTTP views for explicit privacy and retention defaults."""

from typing import Annotated

from fastapi import APIRouter, Depends

from financial_slides_api.schemas.privacy import RetentionPolicyResponse
from financial_slides_api.services.privacy import RetentionPolicy, get_retention_policy

router = APIRouter(prefix="/privacy", tags=["privacy"])


def retention_policy_dependency() -> RetentionPolicy:
    return get_retention_policy()


Policy = Annotated[RetentionPolicy, Depends(retention_policy_dependency)]


@router.get("/retention", response_model=RetentionPolicyResponse)
def get_retention(policy: Policy) -> RetentionPolicyResponse:
    return RetentionPolicyResponse.from_policy(policy)
