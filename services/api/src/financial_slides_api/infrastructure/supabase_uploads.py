"""Private Supabase Storage signed uploads with server-side integrity verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import quote
from uuid import uuid4

import httpx2
import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class SignedUpload:
    id: str
    object_key: str
    signed_url: str
    expires_at: datetime


@dataclass(frozen=True)
class VerifiedUpload:
    file_name: str
    media_type: str
    content: bytes


class UploadNotFoundError(Exception):
    pass


class UploadIntegrityError(Exception):
    pass


class SupabaseUploadService:
    def __init__(
        self,
        database_url: str,
        supabase_url: str,
        secret_key: str,
        *,
        bucket: str = "source-documents",
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._database_url = database_url
        self._supabase_url = supabase_url.rstrip("/")
        self._secret_key = secret_key
        self._bucket = bucket
        self._transport = transport

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
        }

    def create(
        self,
        organization_id: str,
        user_id: str,
        *,
        file_name: str,
        media_type: str,
        size_bytes: int,
        digest: str,
    ) -> SignedUpload:
        upload_id = str(uuid4())
        safe_name = "".join(
            character if character.isalnum() or character in {".", "-", "_"} else "_"
            for character in file_name
        )
        object_key = f"{organization_id}/{upload_id}/{safe_name}"
        expires_at = datetime.now(UTC) + timedelta(hours=2)
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                insert into financial_slides.uploads (
                    id, organization_id, created_by, object_key, file_name,
                    media_type, size_bytes, sha256, status, expires_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                """,
                (
                    upload_id,
                    organization_id,
                    user_id,
                    object_key,
                    file_name,
                    media_type,
                    size_bytes,
                    digest,
                    expires_at,
                ),
            )
        encoded_key = quote(object_key, safe="/")
        with httpx2.Client(timeout=10, transport=self._transport) as client:
            response = client.post(
                f"{self._supabase_url}/storage/v1/object/upload/sign/"
                f"{quote(self._bucket, safe='')}/{encoded_key}",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"allowOverwrite": False},
            )
            response.raise_for_status()
            payload = response.json()
        signed_url = payload.get("url") or payload.get("signedURL") or payload.get("signedUrl")
        if not isinstance(signed_url, str) or not signed_url:
            raise RuntimeError("Supabase Storage did not return a signed upload URL")
        if signed_url.startswith("/"):
            signed_url = f"{self._supabase_url}/storage/v1{signed_url}"
        return SignedUpload(upload_id, object_key, signed_url, expires_at)

    def verify(self, upload_id: str, organization_id: str) -> VerifiedUpload:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                select file_name, media_type, size_bytes, sha256, object_key, status, expires_at
                from financial_slides.uploads
                where id=%s and organization_id=%s
                """,
                (upload_id, organization_id),
            ).fetchone()
        if row is None:
            raise UploadNotFoundError("upload was not found")
        if row["status"] not in {"pending", "uploaded", "ready"}:
            raise UploadIntegrityError("upload cannot be used")
        if row["expires_at"] < datetime.now(UTC):
            raise UploadIntegrityError("upload has expired")
        encoded_key = quote(str(row["object_key"]), safe="/")
        with httpx2.Client(timeout=30, transport=self._transport) as client:
            response = client.get(
                f"{self._supabase_url}/storage/v1/object/authenticated/"
                f"{quote(self._bucket, safe='')}/{encoded_key}",
                headers=self._headers,
            )
            if response.status_code == 404:
                raise UploadIntegrityError("upload is not complete")
            response.raise_for_status()
            content = response.content
        actual_digest = f"sha256:{sha256(content).hexdigest()}"
        if len(content) != row["size_bytes"] or actual_digest != row["sha256"]:
            self._set_status(upload_id, "rejected")
            raise UploadIntegrityError("uploaded file failed integrity verification")
        if not content.startswith(b"%PDF-"):
            self._set_status(upload_id, "rejected")
            raise UploadIntegrityError("uploaded content is not a PDF")
        self._set_status(upload_id, "ready")
        return VerifiedUpload(str(row["file_name"]), str(row["media_type"]), content)

    def _set_status(self, upload_id: str, status: str) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                update financial_slides.uploads
                set status=%s, completed_at=case when %s='ready' then now() else completed_at end
                where id=%s
                """,
                (status, status, upload_id),
            )
