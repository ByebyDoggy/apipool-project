#!/usr/bin/env python
# -*- coding: utf-8 -*-

__version__ = "1.0.9"
__short_description__ = "Multiple API Key Manager (Next Generation, sqlalchemy_mate free)"
__license__ = "MIT"
__author__ = "apipool-ng Contributors"
__author_email__ = ""
__maintainer__ = "apipool-ng Contributors"
__maintainer_email__ = ""
__github_username__ = ""

try:
    from .apikey import ApiKey
    from .manager import (
        ApiKeyManager, PoolExhaustedError, BatchResult,
        AsyncApiCaller, AsyncChainProxy, AsyncDummyClient,
        DynamicKeyManager, AsyncDynamicKeyManager,
    )
    from .stats import StatusCollection, StatsCollector
except Exception as e:  # pragma: no cover
    pass

try:
    from .client import connect, login, get_keys, async_connect, alogin, aget_keys, get_config, aget_config, PoolConfig, connect_with_stats, async_connect_with_stats
except Exception:  # pragma: no cover
    pass
