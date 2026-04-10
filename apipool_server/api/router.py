#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""API router aggregation."""

from fastapi import APIRouter

from .v1.auth import router as auth_router
from .v1.keys import router as keys_router
from .v1.pools import router as pools_router
from .v1.proxy import router as proxy_router
from .v1.stats import router as stats_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(keys_router)
api_router.include_router(pools_router)
api_router.include_router(proxy_router)
api_router.include_router(stats_router)
