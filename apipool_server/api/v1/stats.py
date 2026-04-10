#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Stats query routes."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...schemas.stats import StatsUsageResponse, StatsTimelineResponse
from ...services.stats_service import StatsService
from .auth import get_current_user

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("/{pool_identifier}/usage", response_model=StatsUsageResponse)
def get_usage(
    pool_identifier: str,
    seconds: int = Query(3600, ge=1),
    group_by: Optional[str] = Query(None, pattern="^(key|status|hour)$"),
    status: Optional[str] = Query(None, pattern="^(success|failed|reach_limit)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get usage statistics for a pool."""
    service = StatsService(db)
    return service.get_usage(user, pool_identifier, seconds, group_by, status)


@router.get("/{pool_identifier}/timeline", response_model=StatsTimelineResponse)
def get_timeline(
    pool_identifier: str,
    seconds: int = Query(3600, ge=1),
    interval: str = Query("hour", pattern="^(minute|hour|day)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get usage timeline for a pool."""
    service = StatsService(db)
    return service.get_timeline(user, pool_identifier, seconds, interval)
