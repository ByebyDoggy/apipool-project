#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Stats query routes."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...schemas.stats import (
    StatsUsageResponse, StatsTimelineResponse,
    SuccessRateResponse, CallLogResponse,
    StatsReportRequest, StatsReportResponse,
)
from ...services.stats_service import StatsService
from .auth import get_current_user

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.post("/report", response_model=StatsReportResponse)
def report_stats(
    req: StatsReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Receive API call statistics reported by SDK clients.

    Clients using DynamicKeyManager periodically POST their local
    call events here so the server has visibility into SDK-mode usage.
    """
    service = StatsService(db)
    return service.receive_report(user, req)


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


@router.get("/{pool_identifier}/success-rate", response_model=SuccessRateResponse)
def get_success_rate(
    pool_identifier: str,
    seconds: int = Query(3600, ge=1, description="Time window in seconds"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get success rate statistics for a pool with per-key breakdown."""
    service = StatsService(db)
    return service.get_success_rate(user, pool_identifier, seconds)


@router.get("/{pool_identifier}/logs", response_model=CallLogResponse)
def get_call_logs(
    pool_identifier: str,
    seconds: int = Query(3600, ge=1, description="Time window in seconds"),
    key_identifier: Optional[str] = Query(None, description="Filter by key identifier"),
    status: Optional[str] = Query(None, pattern="^(success|failed|reach_limit)$", description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get paginated call log entries for a pool."""
    service = StatsService(db)
    return service.get_call_logs(user, pool_identifier, seconds, key_identifier, status, page, page_size)
