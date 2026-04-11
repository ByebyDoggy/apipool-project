#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pool schemas."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class PoolCreateRequest(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    client_type: str = "generic"
    reach_limit_exception: str | None = None
    rotation_strategy: str = "random"
    pool_config: dict | None = None
    key_identifiers: list[str] | None = None


class PoolUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    reach_limit_exception: str | None = None
    rotation_strategy: str | None = None
    pool_config: dict | None = None


class PoolAddMembersRequest(BaseModel):
    key_identifiers: list[str] = Field(..., min_length=1)
    priority: int = 0
    weight: int = 1


class PoolMemberResponse(BaseModel):
    key_identifier: str
    alias: str | None = None
    priority: int
    weight: int
    verification_status: str

    model_config = {"from_attributes": True}


class PoolResponse(BaseModel):
    id: int
    identifier: str
    name: str
    description: str | None = None
    client_type: str
    reach_limit_exception: str | None = None
    rotation_strategy: str
    pool_config: dict | None = None
    is_active: bool
    member_count: int = 0
    members: list[PoolMemberResponse] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PoolConfigResponse(BaseModel):
    """Dedicated response for pool configuration sync."""
    pool_identifier: str
    client_type: str
    reach_limit_exception: str | None = None
    rotation_strategy: str
    pool_config: dict | None = None


class ProxyInvokeRequest(BaseModel):
    attr_path: list[str] = Field(..., min_length=1)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}


class ProxyCallRequest(BaseModel):
    method_chain: str = Field(..., min_length=1)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}


class ProxyResponse(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
    key_identifier: str | None = None
    pool_available: int | None = None
    pool_total: int | None = None


class PoolStatusResponse(BaseModel):
    pool_identifier: str
    available_keys: int
    archived_keys: int
    total_keys: int
    recent_stats: dict[str, int] | None = None
