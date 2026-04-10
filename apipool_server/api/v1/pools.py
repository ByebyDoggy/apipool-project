#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pool management routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from ...database import get_db
from ...models.user import User
from ...schemas.pool import (
    PoolCreateRequest, PoolUpdateRequest, PoolAddMembersRequest,
    PoolResponse, PoolMemberResponse, PoolStatusResponse,
)
from ...schemas.common import PageResponse
from ...services.pool_service import PoolService
from .auth import get_current_user

router = APIRouter(prefix="/pools", tags=["Key Pools"])


@router.post("", response_model=PoolResponse, status_code=201)
def create_pool(req: PoolCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new key pool."""
    service = PoolService(db)
    return service.create(user, req)


@router.get("", response_model=PageResponse[PoolResponse])
def list_pools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all key pools for the current user."""
    service = PoolService(db)
    items, total = service.list_pools(user, page, page_size)
    return PageResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{identifier}", response_model=PoolResponse)
def get_pool(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get details of a key pool including its members."""
    service = PoolService(db)
    return service.get(user, identifier, include_members=True)


@router.put("/{identifier}", response_model=PoolResponse)
def update_pool(identifier: str, req: PoolUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update pool configuration."""
    service = PoolService(db)
    return service.update(user, identifier, req)


@router.delete("/{identifier}")
def delete_pool(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deactivate a key pool."""
    service = PoolService(db)
    service.delete(user, identifier)
    return {"message": "ok"}


@router.post("/{identifier}/members", response_model=PoolResponse)
def add_members(identifier: str, req: PoolAddMembersRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add API Keys to a pool."""
    service = PoolService(db)
    return service.add_members(user, identifier, req)


@router.delete("/{identifier}/members/{key_identifier}")
def remove_member(identifier: str, key_identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove an API Key from a pool."""
    service = PoolService(db)
    service.remove_member(user, identifier, key_identifier)
    return {"message": "ok"}


@router.get("/{identifier}/status", response_model=PoolStatusResponse)
def pool_status(identifier: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get pool status (available/archived/total keys)."""
    service = PoolService(db)
    return service.get_status(user, identifier)
