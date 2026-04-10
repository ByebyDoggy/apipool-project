#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""API Key management service."""

from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, status
from datetime import datetime, timezone
from typing import Optional

from ..models.api_key_entry import ApiKeyEntry
from ..models.user import User
from ..security import KeyEncryption
from ..schemas.api_key import (
    ApiKeyCreateRequest, ApiKeyUpdateRequest, ApiKeyRotateRequest,
    ApiKeyResponse, ApiKeyVerifyResponse, BatchImportRequest, BatchImportResponse,
    RawKeyItem, RawKeyListResponse,
)


class KeyService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user: User, req: ApiKeyCreateRequest) -> ApiKeyResponse:
        # Check identifier uniqueness
        if self.db.query(ApiKeyEntry).filter(ApiKeyEntry.identifier == req.identifier).first():
            raise HTTPException(
                status_code=409,
                detail=f"Identifier '{req.identifier}' already exists",
            )

        # Encrypt the raw key
        encrypted_key = KeyEncryption.encrypt(req.raw_key)

        entry = ApiKeyEntry(
            user_id=user.id,
            identifier=req.identifier,
            alias=req.alias,
            encrypted_key=encrypted_key,
            client_type=req.client_type,
            client_config=req.client_config,
            tags=req.tags,
            description=req.description,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)

        return ApiKeyResponse.model_validate(entry)

    def list_keys(
        self, user: User, client_type: Optional[str] = None,
        is_active: Optional[bool] = None, tag: Optional[str] = None,
        page: int = 1, page_size: int = 20,
    ) -> tuple[list[ApiKeyResponse], int]:
        query = self.db.query(ApiKeyEntry).filter(
            and_(ApiKeyEntry.user_id == user.id, ApiKeyEntry.is_archived == False)
        )

        if client_type:
            query = query.filter(ApiKeyEntry.client_type == client_type)
        if is_active is not None:
            query = query.filter(ApiKeyEntry.is_active == is_active)
        if tag:
            # JSON contains check (SQLite/PostgreSQL compatible)
            query = query.filter(ApiKeyEntry.tags.contains([tag]))

        total = query.count()
        items = query.order_by(ApiKeyEntry.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return [ApiKeyResponse.model_validate(item) for item in items], total

    def get_raw_keys(self, user: User, client_type: str) -> RawKeyListResponse:
        """Get decrypted raw keys for a given client_type.

        This endpoint is designed for SDK usage: users can retrieve
        their raw keys to construct local SDK clients with key rotation.
        """
        query = self.db.query(ApiKeyEntry).filter(
            and_(
                ApiKeyEntry.user_id == user.id,
                ApiKeyEntry.client_type == client_type,
                ApiKeyEntry.is_active == True,
                ApiKeyEntry.is_archived == False,
            )
        )

        entries = query.order_by(ApiKeyEntry.created_at.desc()).all()

        keys = []
        for entry in entries:
            raw_key = KeyEncryption.decrypt(entry.encrypted_key)
            keys.append(RawKeyItem(
                identifier=entry.identifier,
                raw_key=raw_key,
                client_type=entry.client_type,
                alias=entry.alias,
                tags=entry.tags,
            ))

        return RawKeyListResponse(
            client_type=client_type,
            keys=keys,
            total=len(keys),
        )

    def get(self, user: User, identifier: str) -> ApiKeyResponse:
        entry = self._get_entry(user, identifier)
        return ApiKeyResponse.model_validate(entry)

    def update(self, user: User, identifier: str, req: ApiKeyUpdateRequest) -> ApiKeyResponse:
        entry = self._get_entry(user, identifier)

        if req.alias is not None:
            entry.alias = req.alias
        if req.tags is not None:
            entry.tags = req.tags
        if req.description is not None:
            entry.description = req.description
        if req.client_config is not None:
            entry.client_config = req.client_config

        self.db.commit()
        self.db.refresh(entry)
        return ApiKeyResponse.model_validate(entry)

    def rotate(self, user: User, identifier: str, req: ApiKeyRotateRequest) -> ApiKeyResponse:
        entry = self._get_entry(user, identifier)

        # Encrypt new key
        entry.encrypted_key = KeyEncryption.encrypt(req.new_raw_key)
        entry.verification_status = "unknown"
        entry.last_verified_at = None

        self.db.commit()
        self.db.refresh(entry)
        return ApiKeyResponse.model_validate(entry)

    def delete(self, user: User, identifier: str) -> None:
        entry = self._get_entry(user, identifier)
        self.db.delete(entry)
        self.db.commit()

    def verify(self, user: User, identifier: str) -> ApiKeyVerifyResponse:
        entry = self._get_entry(user, identifier)

        try:
            # Decrypt and instantiate the ApiKey
            raw_key = KeyEncryption.decrypt(entry.encrypted_key)
            key_class = ClientRegistry.get(entry.client_type)
            apikey = key_class(raw_key=raw_key, client_config=entry.client_config)

            is_usable = apikey.is_usable()
            entry.verification_status = "valid" if is_usable else "invalid"
        except Exception:
            entry.verification_status = "invalid"
            is_usable = False

        entry.last_verified_at = datetime.now(timezone.utc)
        self.db.commit()

        return ApiKeyVerifyResponse(
            identifier=entry.identifier,
            verification_status=entry.verification_status,
            verified_at=entry.last_verified_at,
        )

    def batch_import(self, user: User, req: BatchImportRequest) -> BatchImportResponse:
        if not ClientRegistry.has(req.client_type):
            raise HTTPException(status_code=400, detail=f"Unknown client_type: '{req.client_type}'")

        imported = 0
        for i, key_data in enumerate(req.keys):
            raw_key = key_data.get("raw_key", "")
            alias = key_data.get("alias", f"imported-{i+1}")
            identifier = f"{req.client_type}-imported-{int(datetime.now().timestamp())}-{i+1}"

            if not raw_key:
                continue

            # Check if identifier already exists
            if self.db.query(ApiKeyEntry).filter(ApiKeyEntry.identifier == identifier).first():
                continue

            encrypted_key = KeyEncryption.encrypt(raw_key)
            entry = ApiKeyEntry(
                user_id=user.id,
                identifier=identifier,
                alias=alias,
                encrypted_key=encrypted_key,
                client_type=req.client_type,
            )
            self.db.add(entry)
            imported += 1

        self.db.commit()

        return BatchImportResponse(
            task_id=f"batch-import-{int(datetime.now().timestamp())}",
            status="completed",
            total=imported,
        )

    def _get_entry(self, user: User, identifier: str) -> ApiKeyEntry:
        entry = self.db.query(ApiKeyEntry).filter(
            and_(
                ApiKeyEntry.identifier == identifier,
                ApiKeyEntry.user_id == user.id,
            )
        ).first()
        if not entry:
            raise HTTPException(status_code=404, detail=f"API Key '{identifier}' not found")
        return entry
