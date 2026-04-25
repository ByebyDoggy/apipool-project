#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Stats service — success rate and call log queries with primary_key → identifier mapping."""

import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import Optional

from ..models.key_pool import KeyPool, PoolMember
from ..models.api_key_entry import ApiKeyEntry
from ..models.user import User
from ..schemas.stats import (
    StatsUsageResponse,
    StatsTimelineResponse,
    SuccessRateResponse,
    KeySuccessRateItem,
    CallLogItem,
    CallLogResponse,
    KeyStatsResponse,
    StatsReportRequest,
    StatsReportResponse,
)
from ..database import get_stats_engine
from ..security import KeyEncryption
from apipool import StatusCollection
from apipool.stats import StatsCollector, Event

logger = logging.getLogger(__name__)


class StatsService:
    def __init__(self, db: Session):
        self.db = db

    # ── Primary key → identifier mapping ─────────────────────────────────

    def _build_key_mapping(self, user: User, pool_identifier: str) -> dict[str, tuple[str, str | None]]:
        """Build mapping from raw_key (primary_key) to (identifier, alias).

        Returns dict[str, tuple[str, str | None]] where key is the raw_key
        and value is (identifier, alias).
        """
        pool = self._get_pool(user, pool_identifier)
        members = self._get_active_members(pool)

        mapping: dict[str, tuple[str, str | None]] = {}
        for entry in members:
            try:
                raw_key = KeyEncryption.decrypt(entry.encrypted_key)
                mapping[raw_key] = (entry.identifier, entry.alias)
            except Exception:
                logger.warning("Failed to decrypt key '%s' for stats mapping", entry.identifier)
        return mapping

    def _get_collector(self, user: User, pool_identifier: str) -> StatsCollector:
        """Get a StatsCollector for the given pool's persistent stats DB."""
        engine = get_stats_engine(user.id, pool_identifier)
        return StatsCollector(engine=engine)

    # ── Legacy methods (kept for backward compat) ────────────────────────

    def get_usage(
        self, user: User, pool_identifier: str,
        seconds: int = 3600, group_by: Optional[str] = None,
        status: Optional[str] = None,
    ) -> StatsUsageResponse:
        collector = self._get_collector(user, pool_identifier)

        status_filter = None
        if status == "success":
            status_filter = StatusCollection.c1_Success.id
        elif status == "failed":
            status_filter = StatusCollection.c5_Failed.id
        elif status == "reach_limit":
            status_filter = StatusCollection.c9_ReachLimit.id

        success_count = collector.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c1_Success.id)
        failed_count = collector.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c5_Failed.id)
        reach_limit_count = collector.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c9_ReachLimit.id)

        summary = {
            "total_calls": success_count + failed_count + reach_limit_count,
            "success": success_count,
            "failed": failed_count,
            "reach_limit": reach_limit_count,
        }

        by_key = None
        if group_by == "key":
            by_key = {}
            raw_stats = collector.usage_count_stats_in_recent_n_seconds(seconds)
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
        usage = self.get_usage(user, pool_identifier, seconds)
        return StatsTimelineResponse(
            pool_identifier=pool_identifier,
            period_seconds=seconds,
            interval=interval,
            data=[{"summary": usage.summary}],
        )

    # ── New: Success rate ────────────────────────────────────────────────

    def get_success_rate(
        self, user: User, pool_identifier: str,
        seconds: int = 3600,
    ) -> SuccessRateResponse:
        """Get success rate statistics for a pool with per-key breakdown."""
        collector = self._get_collector(user, pool_identifier)
        mapping = self._build_key_mapping(user, pool_identifier)

        # Pool-level aggregate
        total_success = collector.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c1_Success.id)
        total_failed = collector.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c5_Failed.id)
        total_reach_limit = collector.usage_count_in_recent_n_seconds(seconds, status_id=StatusCollection.c9_ReachLimit.id)
        total_calls = total_success + total_failed + total_reach_limit

        summary = KeySuccessRateItem(
            key_identifier="__pool__",
            total_calls=total_calls,
            success_count=total_success,
            failed_count=total_failed,
            reach_limit_count=total_reach_limit,
            success_rate=round(total_success / total_calls * 100, 2) if total_calls > 0 else 0.0,
        )

        # Per-key breakdown using raw stats query
        by_key: list[KeySuccessRateItem] = []
        raw_stats = collector.usage_count_stats_in_recent_n_seconds(seconds)

        for primary_key, total in raw_stats.items():
            ident_alias = mapping.get(primary_key)
            if ident_alias is None:
                # Key may have been removed from pool — use raw primary_key hash as fallback
                identifier = f"unknown-{hash(primary_key) % 10000}"
                alias = None
            else:
                identifier, alias = ident_alias

            s = collector.usage_count_in_recent_n_seconds(seconds, primary_key=primary_key, status_id=StatusCollection.c1_Success.id)
            f = collector.usage_count_in_recent_n_seconds(seconds, primary_key=primary_key, status_id=StatusCollection.c5_Failed.id)
            r = collector.usage_count_in_recent_n_seconds(seconds, primary_key=primary_key, status_id=StatusCollection.c9_ReachLimit.id)

            by_key.append(KeySuccessRateItem(
                key_identifier=identifier,
                alias=alias,
                total_calls=total,
                success_count=s,
                failed_count=f,
                reach_limit_count=r,
                success_rate=round(s / total * 100, 2) if total > 0 else 0.0,
            ))

        # Sort by total_calls descending
        by_key.sort(key=lambda x: x.total_calls, reverse=True)

        return SuccessRateResponse(
            pool_identifier=pool_identifier,
            period_seconds=seconds,
            summary=summary,
            by_key=by_key,
        )

    # ── New: Call logs ───────────────────────────────────────────────────

    def get_call_logs(
        self, user: User, pool_identifier: str,
        seconds: int = 3600,
        key_identifier: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> CallLogResponse:
        """Get paginated call log entries for a pool."""
        collector = self._get_collector(user, pool_identifier)
        mapping = self._build_key_mapping(user, pool_identifier)

        # Build reverse mapping: identifier → primary_key
        ident_to_pk: dict[str, str] = {}
        for pk, (ident, _alias) in mapping.items():
            ident_to_pk[ident] = pk

        # Resolve filters
        primary_key_filter = ident_to_pk.get(key_identifier) if key_identifier else None
        status_id_filter = None
        if status == "success":
            status_id_filter = StatusCollection.c1_Success.id
        elif status == "failed":
            status_id_filter = StatusCollection.c5_Failed.id
        elif status == "reach_limit":
            status_id_filter = StatusCollection.c9_ReachLimit.id

        # Query events
        query = collector.query_event_in_recent_n_seconds(
            seconds,
            primary_key=primary_key_filter,
            status_id=status_id_filter,
        )

        total = query.count()
        events = query.order_by(Event.finished_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        # Build id→description status map
        status_map = StatusCollection.get_mapper_id_to_description()

        # Build reverse mapping from apikey_id to primary_key
        apikey_id_to_pk: dict[int, str] = {v: k for k, v in collector._cache_apikey.items()}

        items: list[CallLogItem] = []
        for i, evt in enumerate(events):
            pk = apikey_id_to_pk.get(evt.apikey_id, "")
            ident_alias = mapping.get(pk)
            identifier = ident_alias[0] if ident_alias else f"unknown-{hash(pk) % 10000}"
            alias = ident_alias[1] if ident_alias else None

            items.append(CallLogItem(
                id=i + (page - 1) * page_size + 1,
                key_identifier=identifier,
                alias=alias,
                status=status_map.get(evt.status_id, "unknown"),
                finished_at=evt.finished_at,
            ))

        return CallLogResponse(
            pool_identifier=pool_identifier,
            period_seconds=seconds,
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    # ── New: Single key stats ────────────────────────────────────────────

    def get_key_stats(
        self, user: User, key_identifier: str,
        seconds: int = 86400,
    ) -> KeyStatsResponse:
        """Get statistics for a single key across all pools it belongs to.

        Aggregates stats from every pool this key is a member of.
        """
        # Find the key entry
        key_entry = self.db.query(ApiKeyEntry).filter(
            ApiKeyEntry.identifier == key_identifier,
            ApiKeyEntry.user_id == user.id,
        ).first()
        if not key_entry:
            raise HTTPException(status_code=404, detail=f"API Key '{key_identifier}' not found")

        # Find all pools this key belongs to
        pool_rows = (
            self.db.query(KeyPool)
            .join(PoolMember)
            .filter(
                PoolMember.key_id == key_entry.id,
                KeyPool.user_id == user.id,
                KeyPool.is_active == True,
            )
            .all()
        )

        total_calls = 0
        total_success = 0
        total_failed = 0
        total_reach_limit = 0

        try:
            raw_key = KeyEncryption.decrypt(key_entry.encrypted_key)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to decrypt key for stats lookup")

        for pool in pool_rows:
            try:
                collector = self._get_collector(user, pool.identifier)
                # Ensure this key is registered in the stats DB
                if raw_key not in collector._cache_apikey:
                    continue

                total_calls += collector.usage_count_in_recent_n_seconds(seconds, primary_key=raw_key)
                total_success += collector.usage_count_in_recent_n_seconds(seconds, primary_key=raw_key, status_id=StatusCollection.c1_Success.id)
                total_failed += collector.usage_count_in_recent_n_seconds(seconds, primary_key=raw_key, status_id=StatusCollection.c5_Failed.id)
                total_reach_limit += collector.usage_count_in_recent_n_seconds(seconds, primary_key=raw_key, status_id=StatusCollection.c9_ReachLimit.id)
            except Exception:
                logger.warning("Failed to query stats for key '%s' in pool '%s'", key_identifier, pool.identifier)

        return KeyStatsResponse(
            key_identifier=key_identifier,
            alias=key_entry.alias,
            period_seconds=seconds,
            total_calls=total_calls,
            success_count=total_success,
            failed_count=total_failed,
            reach_limit_count=total_reach_limit,
            success_rate=round(total_success / total_calls * 100, 2) if total_calls > 0 else 0.0,
        )

    # ── Client stats reporting ──────────────────────────────────────────

    def receive_report(self, user: User, req: StatsReportRequest) -> StatsReportResponse:
        """Receive and store API call statistics reported by an SDK client."""
        from ..models.client_call_log import ClientCallLog

        accepted = 0
        for event in req.events:
            log = ClientCallLog(
                user_id=user.id,
                pool_identifier=req.pool_identifier,
                key_identifier=event.key_identifier,
                status=event.status,
                latency=event.latency,
                method=event.method,
                finished_at=event.finished_at,
                client_id=req.client_id,
            )
            self.db.add(log)
            accepted += 1

        self.db.commit()
        logger.info(
            "StatsService: accepted %d events from client %s for pool %s",
            accepted, req.client_id, req.pool_identifier,
        )
        return StatsReportResponse(accepted=accepted)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_pool(self, user: User, identifier: str) -> KeyPool:
        pool = self.db.query(KeyPool).filter(
            KeyPool.identifier == identifier,
            KeyPool.user_id == user.id,
        ).first()
        if not pool:
            raise HTTPException(status_code=404, detail=f"Pool '{identifier}' not found")
        return pool

    def _get_active_members(self, pool: KeyPool) -> list[ApiKeyEntry]:
        return (
            self.db.query(ApiKeyEntry)
            .join(PoolMember)
            .filter(
                PoolMember.pool_id == pool.id,
                ApiKeyEntry.is_active == True,
                ApiKeyEntry.is_archived == False,
            )
            .all()
        )
