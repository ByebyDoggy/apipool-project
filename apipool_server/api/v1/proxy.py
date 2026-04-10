#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Proxy call routes — transparent API invocation."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...schemas.pool import ProxyInvokeRequest, ProxyCallRequest, ProxyResponse
from ...services.proxy_service import ProxyService
from .auth import get_current_user

router = APIRouter(prefix="/proxy", tags=["Proxy"])


@router.post("/{pool_identifier}/invoke", response_model=ProxyResponse)
def proxy_invoke(
    pool_identifier: str,
    req: ProxyInvokeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute a proxied API call with explicit attribute path.
    
    Example request:
    ```json
    {
        "attr_path": ["coins", "simple", "price", "get"],
        "args": [],
        "kwargs": {"ids": "bitcoin"}
    }
    ```
    """
    service = ProxyService(db)
    return service.invoke(user, pool_identifier, req)


@router.post("/{pool_identifier}/call", response_model=ProxyResponse)
def proxy_call(
    pool_identifier: str,
    req: ProxyCallRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute a proxied API call with dot-separated method chain.
    
    Example request:
    ```json
    {
        "method_chain": "coins.simple.price.get",
        "args": [],
        "kwargs": {"ids": "bitcoin"}
    }
    ```
    """
    service = ProxyService(db)
    return service.call(user, pool_identifier, req)


@router.get("/{pool_identifier}/status", response_model=ProxyResponse)
def proxy_status(
    pool_identifier: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if a pool is ready for proxy calls."""
    from ...services.pool_service import PoolService
    service = PoolService(db)
    status = service.get_status(user, pool_identifier)
    return ProxyResponse(
        success=status.available_keys > 0,
        data={
            "available_keys": status.available_keys,
            "archived_keys": status.archived_keys,
            "total_keys": status.total_keys,
        },
        pool_available=status.available_keys,
        pool_total=status.total_keys,
    )
