#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Common schemas."""

from pydantic import BaseModel
from typing import Generic, TypeVar, List
from datetime import datetime

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: List[T]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    """Standard error response."""
    code: str
    message: str
    detail: str | None = None


class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool = True
    message: str = "OK"
