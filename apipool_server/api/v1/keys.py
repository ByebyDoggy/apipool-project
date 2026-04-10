#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""API Key management routes."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...schemas.api_key import (
    ApiKeyCreateRequest, ApiKeyUpdateRequest, ApiKeyRotateRequest,
    ApiKeyResponse, ApiKeyVerifyResponse, BatchImportRequest, BatchImportResponse,
    RawKeyListResponse,
)
from ...schemas.common import PageResponse
from ...services.key_service import KeyService
from .auth import get_current_user

router = APIRouter(prefix="/keys", tags=["API Keys"])


@router.post("", response_model=ApiKeyResponse, status_code=201)
def create_key(req: ApiKeyCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new API Key entry."""
    service = KeyService(db)
    return service.create(user, req)


@router.get("", response_model=PageResponse[ApiKeyResponse])
def list_keys(
    client_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all API Keys for the current user."""
    service = KeyService(db)
    items, total = service.list_keys(user, client_type, is_active, tag, page, page_size)
    return PageResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/raw", response_model=RawKeyListResponse)
def get_raw_keys(
    client_type: str = Query(..., min_length=1, description="Client type to filter keys by"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get decrypted raw keys for a given client_type.

    Designed for SDK usage: retrieve raw keys to construct local
    SDK clients (e.g. CoinGeckoClient) with key rotation.
    """
    service = KeyService(db)
    return service.get_raw_keys(user, client_type)


@router.get("/{identifier}", response_model=ApiKeyResponse)
def get_key(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get details of a specific API Key."""
    service = KeyService(db)
    return service.get(user, identifier)


@router.put("/{identifier}", response_model=ApiKeyResponse)
def update_key(identifier: str, req: ApiKeyUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update API Key metadata."""
    service = KeyService(db)
    return service.update(user, identifier, req)


@router.patch("/{identifier}/rotate", response_model=ApiKeyResponse)
def rotate_key(identifier: str, req: ApiKeyRotateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rotate (replace) the API Key secret."""
    service = KeyService(db)
    return service.rotate(user, identifier, req)


@router.delete("/{identifier}")
def delete_key(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Soft-delete (archive) an API Key."""
    service = KeyService(db)
    service.delete(user, identifier)
    return {"message": "ok"}


@router.post("/{identifier}/verify", response_model=ApiKeyVerifyResponse)
def verify_key(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Trigger usability verification for an API Key."""
    service = KeyService(db)
    return service.verify(user, identifier)


@router.post("/batch-import", response_model=BatchImportResponse)
def batch_import(req: BatchImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Batch import API Keys."""
    service = KeyService(db)
    return service.batch_import(user, req)
