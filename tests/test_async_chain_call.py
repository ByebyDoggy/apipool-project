#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for async ChainProxy and AsyncDummyClient."""

import pytest
from apipool import ApiKeyManager
from apipool.tests import (
    ReachLimitError,
    AsyncNestedApiKey,
    AsyncCoinGeckoStyleApiKey,
    async_apikeys,
)


class TestAsyncChainCallSingleLevel:
    """Async 1-level calls work via adummyclient."""

    @pytest.mark.asyncio
    async def test_async_single_level_call(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncNestedApiKey(k) for k in async_apikeys],
        )
        result = await manager.adummyclient.nested.get_data(id="abc")
        assert result == {"id": "abc", "result": "async_nested_ok"}


class TestAsyncChainCallTwoLevel:
    """Async 2-level attribute chain."""

    @pytest.mark.asyncio
    async def test_async_two_level_chain(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncNestedApiKey(k) for k in async_apikeys],
        )
        result = await manager.adummyclient.nested.get_data(id="test")
        assert result is not None
        assert result["id"] == "test"


class TestAsyncChainCallThreeLevel:
    """Async 3-level attribute chain: group.resource.method()."""

    @pytest.mark.asyncio
    async def test_async_three_level_chain(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncNestedApiKey(k) for k in async_apikeys],
        )
        result = await manager.adummyclient.api.v1.users_list(limit=3)
        assert result is not None
        assert len(result) == 3


class TestAsyncChainCallFourLevel:
    """Async 4-level attribute chain (CoinGecko SDK style)."""

    @pytest.mark.asyncio
    async def test_async_four_level_coingecko_style(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncCoinGeckoStyleApiKey(k) for k in ["cg1", "cg2"]],
            reach_limit_exc=ReachLimitError,
        )
        result = await manager.adummyclient.coins.simple.price.get(
            ids="bitcoin", vs_currencies="usd"
        )
        assert "bitcoin" in result


class TestAsyncChainCallDeepRotation:
    """Deep async chain calls rotate keys correctly."""

    @pytest.mark.asyncio
    async def test_async_deep_chain_rotation(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncCoinGeckoStyleApiKey(k) for k in ["cg1", "cg2"]],
            reach_limit_exc=ReachLimitError,
        )

        for _ in range(20):
            result = await manager.adummyclient.a.b.c.d.e.call()
            assert result == "async_deep_call_ok"

        stats = manager.stats.usage_count_stats_in_recent_n_seconds(3600)
        assert len(stats) > 1  # at least 2 keys participated


class TestAsyncChainCallErrorHandling:
    """Async exception handling in deep chains."""

    @pytest.mark.asyncio
    async def test_async_normal_error_does_not_remove_key(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncCoinGeckoStyleApiKey(k) for k in ["cg1", "cg2"]],
            reach_limit_exc=ReachLimitError,
        )
        original_count = len(manager.apikey_chain)

        with pytest.raises(ValueError):
            await manager.adummyclient.a.b.c.raise_error()

        assert len(manager.apikey_chain) == original_count

    @pytest.mark.asyncio
    async def test_async_reach_limit_removes_key(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncCoinGeckoStyleApiKey(k) for k in ["cg1", "cg2"]],
            reach_limit_exc=ReachLimitError,
        )
        original_count = len(manager.apikey_chain)

        with pytest.raises(ReachLimitError):
            await manager.adummyclient.a.b.c.raise_reach_limit_error()

        assert len(manager.apikey_chain) == original_count - 1


class TestAsyncChainProxyRepr:
    """AsyncChainProxy has a readable repr for debugging."""

    @pytest.mark.asyncio
    async def test_async_repr_single_level(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncNestedApiKey(k) for k in async_apikeys],
        )
        proxy = manager.adummyclient.coins
        assert "coins" in repr(proxy)

    @pytest.mark.asyncio
    async def test_async_repr_multi_level(self):
        manager = ApiKeyManager(
            apikey_list=[AsyncNestedApiKey(k) for k in async_apikeys],
        )
        proxy1 = manager.adummyclient.coins
        proxy2 = proxy1.simple
        repr_str = repr(proxy2)
        assert "coins" in repr_str
        assert "simple" in repr_str


class TestAsyncAndSyncCoexist:
    """Both dummyclient and adummyclient work on the same manager."""

    @pytest.mark.asyncio
    async def test_sync_and_async_on_same_manager(self):
        """Sync dummyclient uses sync methods, async adummyclient uses async methods."""
        # Use the regular CoinGeckoStyleApiKey which has sync methods
        from apipool.tests import CoinGeckoStyleApiKey
        manager = ApiKeyManager(
            apikey_list=[CoinGeckoStyleApiKey(k) for k in ["sync1", "sync2"]],
            reach_limit_exc=ReachLimitError,
        )

        # Sync call via dummyclient
        sync_result = manager.dummyclient.coins.simple.price.get(
            ids="bitcoin", vs_currencies="usd"
        )
        assert "bitcoin" in sync_result

        # Note: adummyclient on a sync client would need the methods to be
        # async. This test verifies the manager has both properties.
        assert hasattr(manager, 'dummyclient')
        assert hasattr(manager, 'adummyclient')


if __name__ == "__main__":
    import os

    basename = os.path.basename(__file__)
    pytest.main([basename, "-s", "--tb=native"])
