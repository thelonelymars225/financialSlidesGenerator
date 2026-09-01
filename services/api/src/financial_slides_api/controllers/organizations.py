"""Organization bootstrap and membership discovery."""

import os
from typing import Annotated
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from financial_slides_api.schemas.organizations import (
    CreateOrganizationRequest,
    OrganizationResponse,
)
from financial_slides_api.security import Authenticated

router = APIRouter(prefix="/organizations", tags=["organizations"])


class OrganizationService:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create(self, user_id: str, name: str) -> dict:
        organization_id = str(uuid4())
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                insert into financial_slides.organizations (id, name, created_by)
                values (%s, %s, %s)
                returning id, name, hosted_ai_enabled, created_at
                """,
                (organization_id, name.strip(), user_id),
            ).fetchone()
            connection.execute(
                """
                insert into financial_slides.organization_memberships (
                    organization_id, user_id, role
                ) values (%s, %s, 'owner')
                """,
                (organization_id, user_id),
            )
        return {**dict(row), "role": "owner"}

    def list_for(self, user_id: str) -> list[dict]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                select organization.id, organization.name, membership.role,
                    organization.hosted_ai_enabled, organization.created_at
                from financial_slides.organization_memberships membership
                join financial_slides.organizations organization
                    on organization.id = membership.organization_id
                where membership.user_id=%s
                order by organization.created_at, organization.id
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def organization_service_dependency() -> OrganizationService:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for organizations")
    return OrganizationService(database_url)


Organizations = Annotated[OrganizationService, Depends(organization_service_dependency)]


@router.get("", response_model=list[OrganizationResponse])
def list_organizations(
    user: Authenticated,
    organizations: Organizations,
) -> list[OrganizationResponse]:
    return [OrganizationResponse(**row) for row in organizations.list_for(user.user_id)]


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    request: CreateOrganizationRequest,
    user: Authenticated,
    organizations: Organizations,
) -> OrganizationResponse:
    if user.aal not in {"aal1", "aal2"}:
        raise HTTPException(status_code=403, detail="authenticated assurance is required")
    return OrganizationResponse(**organizations.create(user.user_id, request.name))
