#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Stats schemas."""

from pydantic import BaseModel
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
