#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Stats schemas."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class StatsUsageResponse(BaseModel):
    pool_identifier: str
    period_seconds: int
    summary: dict[str, int]
    by_key: dict[str, dict[str, int]] | None = None


class StatsTimelineResponse(BaseModel):
    pool_identifier: str
    period_seconds: int
    interval: str
    data: list[dict[str, Any]]


# ── New schemas for success rate and call logs ──────────────────────────────


class KeySuccessRateItem(BaseModel):
    """Per-key success rate statistics."""
    key_identifier: str
    alias: str | None = None
    total_calls: int = 0
    success_count: int = 0
    failed_count: int = 0
    reach_limit_count: int = 0
    success_rate: float = Field(0.0, description="Success rate as a percentage (0-100)")


class SuccessRateResponse(BaseModel):
    """Pool-level success rate statistics with per-key breakdown."""
    pool_identifier: str
    period_seconds: int
    summary: KeySuccessRateItem
    by_key: list[KeySuccessRateItem] = []


class CallLogItem(BaseModel):
    """A single call log entry."""
    id: int
    key_identifier: str
    alias: str | None = None
    status: str
    finished_at: datetime


class CallLogResponse(BaseModel):
    """Paginated call log response."""
    pool_identifier: str
    period_seconds: int
    items: list[CallLogItem]
    total: int
    page: int
    page_size: int


class KeyStatsResponse(BaseModel):
    """Single key statistics across all pools it belongs to."""
    key_identifier: str
    alias: str | None = None
    period_seconds: int
    total_calls: int = 0
    success_count: int = 0
    failed_count: int = 0
    reach_limit_count: int = 0
    success_rate: float = Field(0.0, description="Success rate as a percentage (0-100)")


# ── Client stats reporting schemas ──────────────────────────────────────


class ClientCallEvent(BaseModel):
    """A single API call event reported by an SDK client."""
    key_identifier: str
    status: str
    latency: float | None = None
    method: str | None = None
    finished_at: datetime


class StatsReportRequest(BaseModel):
    """Request body for client stats reporting."""
    pool_identifier: str
    client_id: str | None = None
    events: list[ClientCallEvent]


class StatsReportResponse(BaseModel):
    """Response for client stats reporting."""
    accepted: int
    duplicates: int = 0
