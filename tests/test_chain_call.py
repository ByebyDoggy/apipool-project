#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pytest
from apipool import ApiKeyManager
from apipool.tests import (
    ReachLimitError,
    NestedApiKey,
    NestedApiClient,
    CoinGeckoStyleApiKey,
)


nested_apikeys = ["nested1@test.com", "nested2@test.com", "nested3@test.com"]
coingecko_apikeys = [
    "coingecko1@test.com",
    "coingecko2@test.com",
]


class TestChainCallSingleLevel:
    """Regression: 1-level calls still work (backward compatibility)."""

    def test_single_level_call(self):
        manager = ApiKeyManager(
            apikey_list=[NestedApiKey(k) for k in nested_apikeys],
        )
        manager.check_usable()

        res = manager.dummyclient.nested.get_data(id="abc")
        assert res == {"id": "abc", "result": "nested_ok"}


class TestChainCallTwoLevel:
    """2-level attribute chain: resource.method()."""

    def test_two_level_chain(self):
        manager = ApiKeyManager(
            apikey_list=[NestedApiKey(k) for k in nested_apikeys],
        )
        manager.check_usable()

        result = manager.dummyclient.nested.get_data(id="abc")
        assert result is not None
        assert result["id"] == "abc"


class TestChainCallThreeLevel:
    """3-level attribute chain: group.resource.method()."""

    def test_three_level_chain(self):
        manager = ApiKeyManager(
            apikey_list=[NestedApiKey(k) for k in nested_apikeys],
        )
        manager.check_usable()

        result = manager.dummyclient.api.v1.users_list(limit=3)
        assert result is not None
        assert len(result) == 3


class TestChainCallFourLevel:
    """4-level attribute chain (CoinGecko SDK style)."""

    def test_four_level_coingecko_style(self):
        manager = ApiKeyManager(
            apikey_list=[CoinGeckoStyleApiKey(k) for k in coingecko_apikeys],
            reach_limit_exc=ReachLimitError,
        )
        manager.check_usable()

        result = manager.dummyclient.coins.simple.price.get(
            ids="bitcoin", vs_currencies="usd"
        )
        assert "bitcoin" in result


class TestChainCallDeepRotation:
    """Deep chain calls rotate keys correctly."""

    def test_deep_chain_rotation(self):
        manager = ApiKeyManager(
            apikey_list=[CoinGeckoStyleApiKey(k) for k in coingecko_apikeys],
            reach_limit_exc=ReachLimitError,
        )
        manager.check_usable()

        for _ in range(20):
            result = manager.dummyclient.a.b.c.d.e.call()
            assert result == "deep_call_ok"

        stats = manager.stats.usage_count_stats_in_recent_n_seconds(3600)
        assert len(stats) > 1  # at least 2 keys participated


class TestChainCallErrorHandling:
    """Exception handling in deep chains."""

    def test_normal_error_does_not_remove_key(self):
        manager = ApiKeyManager(
            apikey_list=[CoinGeckoStyleApiKey(k) for k in coingecko_apikeys],
            reach_limit_exc=ReachLimitError,
        )
        manager.check_usable()
        original_count = len(manager.apikey_chain)

        with pytest.raises(ValueError):
            manager.dummyclient.a.b.c.raise_error()

        assert len(manager.apikey_chain) == original_count

    def test_reach_limit_removes_key(self):
        manager = ApiKeyManager(
            apikey_list=[CoinGeckoStyleApiKey(k) for k in coingecko_apikeys],
            reach_limit_exc=ReachLimitError,
        )
        manager.check_usable()
        original_count = len(manager.apikey_chain)

        with pytest.raises(ReachLimitError):
            manager.dummyclient.a.b.c.raise_reach_limit_error()

        assert len(manager.apikey_chain) == original_count - 1


class TestChainProxyRepr:
    """ChainProxy has a readable repr for debugging."""

    def test_repr_single_level(self):
        manager = ApiKeyManager(
            apikey_list=[NestedApiKey(k) for k in nested_apikeys],
        )

        proxy = manager.dummyclient.coins
        assert "coins" in repr(proxy)

    def test_repr_multi_level(self):
        manager = ApiKeyManager(
            apikey_list=[NestedApiKey(k) for k in nested_apikeys],
        )

        proxy1 = manager.dummyclient.coins
        proxy2 = proxy1.simple
        repr_str = repr(proxy2)
        assert "coins" in repr_str
        assert "simple" in repr_str


if __name__ == "__main__":
    import os

    basename = os.path.basename(__file__)
    pytest.main([basename, "-s", "--tb=native"])
