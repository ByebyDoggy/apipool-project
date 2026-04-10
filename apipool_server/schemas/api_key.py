#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""API Key schemas."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class ApiKeyCreateRequest(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    alias: str | None = None
    raw_key: str = Field(..., min_length=1, max_length=4096)
    client_type: str = Field(..., min_length=1, max_length=128)
    client_config: dict[str, Any] | None = None
    tags: list[str] | None = None
    description: str | None = None


class ApiKeyUpdateRequest(BaseModel):
    alias: str | None = None
    tags: list[str] | None = None
    description: str | None = None
    client_config: dict[str, Any] | None = None


class ApiKeyRotateRequest(BaseModel):
    new_raw_key: str = Field(..., min_length=1, max_length=4096)


class ApiKeyResponse(BaseModel):
    id: int
    identifier: str
    alias: str | None = None
    client_type: str
    client_config: dict[str, Any] | None = None
    is_active: bool
    is_archived: bool
    verification_status: str
    last_verified_at: datetime | None = None
    tags: list[str] | None = None
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyVerifyResponse(BaseModel):
    identifier: str
    verification_status: str
    verified_at: datetime


class BatchImportRequest(BaseModel):
    client_type: str = Field(..., min_length=1, max_length=128)
    keys: list[dict[str, str]] = Field(..., min_length=1, max_length=100)


class BatchImportResponse(BaseModel):
    task_id: str
    status: str
    total: int


class RawKeyItem(BaseModel):
    """A single raw (decrypted) key with its metadata."""
    identifier: str
    raw_key: str
    client_type: str
    alias: str | None = None
    tags: list[str] | None = None


class RawKeyListResponse(BaseModel):
    """Response containing decrypted raw keys for a given client_type."""
    client_type: str
    keys: list[RawKeyItem]
    total: int
