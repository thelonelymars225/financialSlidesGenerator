"""Authentication, organization authorization, and HTTP security boundaries."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import jwt
import psycopg
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

ALLOWED_JWT_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})
ORGANIZATION_ROLES = frozenset({"owner", "admin", "member"})
MANAGER_ROLES = frozenset({"owner", "admin"})


@dataclass(frozen=True)
class SecuritySettings:
    environment: str
    auth_required: bool
    supabase_url: str | None
    jwt_issuer: str | None
    jwt_audience: str
    database_url: str | None


@dataclass(frozen=True)
class RequestIdentity:
    user_id: str
    organization_id: str
    role: str
    aal: str
    authenticated: bool

    @property
    def can_manage(self) -> bool:
        return self.role in MANAGER_ROLES


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    aal: str


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def security_settings(
    environment: Mapping[str, str] = os.environ,
) -> SecuritySettings:
    app_environment = environment.get("APP_ENV", "development").strip().lower()
    auth_required = _truthy(environment.get("AUTH_REQUIRED")) or app_environment == "production"
    supabase_url = environment.get("SUPABASE_URL", "").strip().rstrip("/") or None
    jwt_issuer = f"{supabase_url}/auth/v1" if supabase_url else None
    return SecuritySettings(
        environment=app_environment,
        auth_required=auth_required,
        supabase_url=supabase_url,
        jwt_issuer=jwt_issuer,
        jwt_audience=environment.get("SUPABASE_JWT_AUDIENCE", "authenticated").strip(),
        database_url=environment.get("DATABASE_URL", "").strip() or None,
    )


def validate_security_configuration(environment: Mapping[str, str] = os.environ) -> None:
    settings = security_settings(environment)
    if not settings.auth_required:
        return
    missing = []
    if not settings.supabase_url:
        missing.append("SUPABASE_URL")
    if not settings.database_url:
        missing.append("DATABASE_URL")
    if not environment.get("SUPABASE_SECRET_KEY", "").strip():
        missing.append("SUPABASE_SECRET_KEY")
    if not environment.get("CORS_ALLOWED_ORIGINS", "").strip():
        missing.append("CORS_ALLOWED_ORIGINS")
    if missing:
        raise RuntimeError(
            "production authentication requires: " + ", ".join(missing)
        )
    parsed = urlsplit(settings.supabase_url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("SUPABASE_URL must be an absolute HTTPS URL in production")
    database = urlsplit(settings.database_url or "")
    if database.scheme not in {"postgres", "postgresql"} or not database.hostname:
        raise RuntimeError("DATABASE_URL must be an absolute PostgreSQL URL")
    if parse_qs(database.query).get("sslmode") not in [["require"], ["verify-ca"], ["verify-full"]]:
        raise RuntimeError("DATABASE_URL must require TLS with sslmode")
    cors_origins = [
        origin.strip().rstrip("/")
        for origin in environment.get("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if any(urlsplit(origin).scheme != "https" for origin in cors_origins):
        raise RuntimeError("production CORS origins must use HTTPS")
    workflow_backend = environment.get("WORKFLOW_BACKEND", "local").strip().lower()
    if workflow_backend not in {"local", "temporal"}:
        raise RuntimeError("WORKFLOW_BACKEND must be local or temporal")
    if workflow_backend == "temporal":
        if environment.get("FINANCIAL_SLIDES_STORE") != "postgres":
            raise RuntimeError("Temporal workflows require FINANCIAL_SLIDES_STORE=postgres")
        temporal_missing = [
            name
            for name in ("TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE", "TEMPORAL_API_KEY")
            if not environment.get(name, "").strip()
        ]
        if temporal_missing:
            raise RuntimeError(
                "Temporal Cloud requires: " + ", ".join(temporal_missing)
            )


class MembershipAuthorizer(Protocol):
    def role_for(self, user_id: str, organization_id: str) -> str | None: ...


class PostgresMembershipAuthorizer:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def role_for(self, user_id: str, organization_id: str) -> str | None:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                select role
                from financial_slides.organization_memberships
                where organization_id = %s and user_id = %s
                """,
                (organization_id, user_id),
            ).fetchone()
        return str(row[0]) if row else None


class JwtVerifier:
    def __init__(self, settings: SecuritySettings) -> None:
        if not settings.jwt_issuer:
            raise RuntimeError("SUPABASE_URL is required for JWT verification")
        self._settings = settings
        self._jwks = PyJWKClient(
            f"{settings.jwt_issuer}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=600,
        )

    def verify(self, token: str) -> dict:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise InvalidTokenError("unsupported JWT signing algorithm")
        signing_key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience=self._settings.jwt_audience,
            issuer=self._settings.jwt_issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )


@lru_cache(maxsize=1)
def get_security_settings() -> SecuritySettings:
    return security_settings()


@lru_cache(maxsize=1)
def get_jwt_verifier() -> JwtVerifier:
    return JwtVerifier(get_security_settings())


@lru_cache(maxsize=1)
def get_membership_authorizer() -> MembershipAuthorizer:
    settings = get_security_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for organization authorization")
    return PostgresMembershipAuthorizer(settings.database_url)


def _valid_uuid(value: str, label: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be a UUID",
        ) from error


def request_identity(
    authorization: Annotated[str | None, Header()] = None,
    organization_id: Annotated[
        str | None,
        Header(alias="X-Organization-ID", min_length=1, max_length=64),
    ] = None,
    legacy_owner_id: Annotated[
        str | None,
        Header(alias="X-Owner-ID", min_length=1, max_length=128),
    ] = None,
    settings: SecuritySettings = Depends(get_security_settings),
) -> RequestIdentity:
    if not settings.auth_required:
        owner = organization_id or legacy_owner_id or "local-development"
        return RequestIdentity(
            user_id=legacy_owner_id or "local-development",
            organization_id=owner,
            role="owner",
            aal="aal2",
            authenticated=False,
        )

    if legacy_owner_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Owner-ID is not accepted in production",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="a bearer access token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Organization-ID is required",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = get_jwt_verifier().verify(token)
        user_id = str(UUID(str(claims["sub"])))
    except (InvalidTokenError, PyJWKClientError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="the access token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    resolved_organization = _valid_uuid(organization_id, "X-Organization-ID")
    role = get_membership_authorizer().role_for(user_id, resolved_organization)
    if role not in ORGANIZATION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization membership is required",
        )
    return RequestIdentity(
        user_id=user_id,
        organization_id=resolved_organization,
        role=role,
        aal=str(claims.get("aal", "aal1")),
        authenticated=True,
    )


Identity = Annotated[RequestIdentity, Depends(request_identity)]


def authenticated_user(
    authorization: Annotated[str | None, Header()] = None,
    settings: SecuritySettings = Depends(get_security_settings),
) -> AuthenticatedUser:
    if not settings.auth_required:
        return AuthenticatedUser("local-development", "aal2")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="a bearer access token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = get_jwt_verifier().verify(authorization.removeprefix("Bearer ").strip())
        user_id = str(UUID(str(claims["sub"])))
    except (InvalidTokenError, PyJWKClientError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="the access token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return AuthenticatedUser(user_id, str(claims.get("aal", "aal1")))


Authenticated = Annotated[AuthenticatedUser, Depends(authenticated_user)]


def require_manager(identity: Identity) -> RequestIdentity:
    if not identity.can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="organization administrator access is required",
        )
    return identity


def require_aal2(identity: Identity) -> RequestIdentity:
    if identity.aal != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="multi-factor authentication is required",
        )
    return identity
