#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Proxy call Pydantic schemas."""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ProxyCallRequest(BaseModel):
    """Legacy method_chain format."""
    method_chain: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ProxyInvokeRequest(BaseModel):
    """SDK-friendly attr_path format."""
    attr_path: list[str] = Field(..., min_length=1)
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ProxyCallResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    key_identifier: Optional[str] = None
    stats: Optional[dict[str, int]] = None


class ProxyStatusResponse(BaseModel):
    pool_identifier: str
    available_keys: int
    archived_keys: int
    total_keys: int
    recent_stats: Optional[dict[str, int]] = None
