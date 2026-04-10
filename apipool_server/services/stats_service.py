#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Stats service."""

from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import Optional

from ..models.key_pool import KeyPool, PoolMember
from ..models.api_key_entry import ApiKeyEntry
from ..models.user import User
from ..schemas.stats import StatsUsageResponse, StatsTimelineResponse
from ..services.pool_service import PoolService
from apipool import StatusCollection


class StatsService:
    def __init__(self, db: Session):
        self.db = db
        self.pool_service = PoolService(db)

    def get_usage(
        self, user: User, pool_identifier: str,
        seconds: int = 3600, group_by: Optional[str] = None,
        status: Optional[str] = None,
    ) -> StatsUsageResponse:
        pool = self.pool_service._get_pool(user, pool_identifier)
        try:
            manager = self.pool_service.build_manager(pool_identifier, user.id)
        except Exception:
            raise HTTPException(status_code=503, detail="Pool has no available keys")

        stats = manager.stats

        # Build summary
        status_filter = None
        if status == "success":
            status_filter = StatusCollection.c1_Success.id
        elif status == "failed":
            status_filter = StatusCollection.c5_Failed.id
        elif status == "reach_limit":
            status_filter = StatusCollection.c9_ReachLimit.id

        success_count = stats.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c1_Success.id)
        failed_count = stats.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c5_Failed.id)
        reach_limit_count = stats.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c9_ReachLimit.id)

        summary = {
            "total_calls": success_count + failed_count + reach_limit_count,
            "success": success_count,
            "failed": failed_count,
            "reach_limit": reach_limit_count,
        }

        by_key = None
        if group_by == "key":
            by_key = {}
            raw_stats = stats.usage_count_stats_in_recent_n_seconds(seconds)
            for key, count in raw_stats.items():
                by_key[key] = {"total": count}

        return StatsUsageResponse(
            pool_identifier=pool_identifier,
            period_seconds=seconds,
            summary=summary,
            by_key=by_key,
        )

    def get_timeline(
        self, user: User, pool_identifier: str,
        seconds: int = 3600, interval: str = "hour",
    ) -> StatsTimelineResponse:
        # Simplified timeline — returns aggregate counts
        # Full implementation would query time-bucketed data
        usage = self.get_usage(user, pool_identifier, seconds)

        return StatsTimelineResponse(
            pool_identifier=pool_identifier,
            period_seconds=seconds,
            interval=interval,
            data=[{
                "summary": usage.summary,
            }],
        )
