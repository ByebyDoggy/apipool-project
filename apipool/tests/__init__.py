#!/usr/bin/env python
# -*- coding: utf-8 -*-

from ..apikey import ApiKey


class ReachLimitError(Exception):
    pass


class GoogleMapApiClient(object):
    def __init__(self, apikey):
        self.apikey = apikey

    def get_lat_lng_by_address(self, address):
        return {"lat": 40.762882, "lng": -73.973700}

    def raise_other_error(self, address):
        raise ValueError

    def raise_reach_limit_error(self, address):
        raise ReachLimitError


class NestedApiClient(object):
    """Mock client with multi-level attribute chain for testing ChainProxy."""

    def __init__(self, apikey):
        self.apikey = apikey
        self.nested = _NestedResource()
        self.api = _ApiResource()


class _NestedResource(object):
    def get_data(self, id=None):
        return {"id": id, "result": "nested_ok"}


class _ApiResource(object):
    def __init__(self):
        self.v1 = _V1Resource()


class _V1Resource(object):
    def users_list(self, limit=None):
        return [{"user_id": i} for i in range(limit or 5)]


class CoinGeckoStyleClient(object):
    """Mock client mimicking 4-level CoinGecko-style SDK chain."""

    def __init__(self, apikey):
        self.apikey = apikey
        self.coins = _CoinsResource()
        self.a = _DeepChainNode("a")


class _CoinsResource(object):
    def __init__(self):
        self.simple = _SimpleResource()


class _SimpleResource(object):
    def __init__(self):
        self.price = _PriceResource()


class _PriceResource(object):
    def get(self, ids=None, vs_currencies=None):
        return {ids: {vs_currencies: 50000.0}}


class _DeepChainNode(object):
    """Generic deep chain node for testing arbitrary depth."""

    def __init__(self, name=""):
        self._name = name

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        return _DeepChainNode(item)

    def call(self):
        return "deep_call_ok"

    def raise_error(self):
        raise ValueError

    def raise_reach_limit_error(self):
        raise ReachLimitError


# ── Async mock clients ──────────────────────────────────────────────


class AsyncNestedApiClient(object):
    """Mock async client with multi-level attribute chain."""

    def __init__(self, apikey):
        self.apikey = apikey
        self.nested = _AsyncNestedResource()
        self.api = _AsyncApiResource()


class _AsyncNestedResource(object):
    async def get_data(self, id=None):
        return {"id": id, "result": "async_nested_ok"}


class _AsyncApiResource(object):
    def __init__(self):
        self.v1 = _AsyncV1Resource()


class _AsyncV1Resource(object):
    async def users_list(self, limit=None):
        return [{"user_id": i} for i in range(limit or 5)]


class AsyncCoinGeckoStyleClient(object):
    """Mock async client mimicking CoinGecko-style SDK chain."""

    def __init__(self, apikey):
        self.apikey = apikey
        self.coins = _AsyncCoinsResource()
        self.a = _AsyncDeepChainNode("a")


class _AsyncCoinsResource(object):
    def __init__(self):
        self.simple = _AsyncSimpleResource()


class _AsyncSimpleResource(object):
    def __init__(self):
        self.price = _AsyncPriceResource()


class _AsyncPriceResource(object):
    async def get(self, ids=None, vs_currencies=None):
        return {ids: {vs_currencies: 50000.0}}


class _AsyncDeepChainNode(object):
    """Generic async deep chain node."""

    def __init__(self, name=""):
        self._name = name

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        return _AsyncDeepChainNode(item)

    async def call(self):
        return "async_deep_call_ok"

    async def raise_error(self):
        raise ValueError

    async def raise_reach_limit_error(self):
        raise ReachLimitError


# ── ApiKey subclasses ──────────────────────────────────────────────


class GoogleMapApiKey(ApiKey):
    def __init__(self, apikey):
        self.apikey = apikey

    def get_primary_key(self):
        return self.apikey

    def create_client(self):
        return GoogleMapApiClient(self.apikey)

    def test_usability(self, client):
        if "99" in self.apikey:
            return False
        response = client.get_lat_lng_by_address(
            "123 North St, NewYork, NY 10001")
        if ("lat" in response) and ("lng" in response):
            return True
        else:
            return False


class NestedApiKey(ApiKey):
    def __init__(self, apikey):
        self.apikey = apikey

    def get_primary_key(self):
        return self.apikey

    def create_client(self):
        return NestedApiClient(self.apikey)

    def test_usability(self, client):
        return True


class CoinGeckoStyleApiKey(ApiKey):
    def __init__(self, apikey):
        self.apikey = apikey

    def get_primary_key(self):
        return self.apikey

    def create_client(self):
        return CoinGeckoStyleClient(self.apikey)

    def test_usability(self, client):
        return True


class AsyncNestedApiKey(ApiKey):
    """ApiKey that creates an async mock client."""

    def __init__(self, apikey):
        self.apikey = apikey

    def get_primary_key(self):
        return self.apikey

    def create_client(self):
        return AsyncNestedApiClient(self.apikey)

    def test_usability(self, client):
        return True


class AsyncCoinGeckoStyleApiKey(ApiKey):
    """ApiKey that creates an async CoinGecko-style mock client."""

    def __init__(self, apikey):
        self.apikey = apikey

    def get_primary_key(self):
        return self.apikey

    def create_client(self):
        return AsyncCoinGeckoStyleClient(self.apikey)

    def test_usability(self, client):
        return True


apikeys = [
    "example1@gmail.com",
    "example2@gmail.com",
    "example3@gmail.com",
    "example99@gmail.com",
]

async_apikeys = [
    "async1@test.com",
    "async2@test.com",
    "async3@test.com",
]
