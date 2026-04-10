#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Example: CoinGecko client with key rotation via apipool server.

Supports both synchronous and asynchronous SDK clients:

Synchronous:
    python examples/coingecko_client.py

Asynchronous:
    python examples/coingecko_client.py --async
"""

import asyncio

from pycoingecko import CoinGeckoAPI

from apipool import ApiKey, ApiKeyManager, login, get_keys, alogin, aget_keys


# ── Sync CoinGecko Client ──────────────────────────────────────────


class CoinGeckoClient(ApiKey):
    """ApiKey wrapper for synchronous CoinGecko SDK client.

    CoinGecko's free API uses an API key passed via the 'x-cg-demo-api-key'
    header. This wrapper creates a CoinGeckoAPI client that includes the
    key in every request.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    def get_primary_key(self):
        return self._api_key

    def create_client(self):
        client = CoinGeckoAPI()
        client.session.headers.update({"x-cg-demo-api-key": self._api_key})
        return client

    def test_usability(self, client):
        try:
            client.ping()
            return True
        except Exception:
            return False


# ── Async CoinGecko Client ─────────────────────────────────────────


class AsyncCoinGeckoClient(ApiKey):
    """ApiKey wrapper for async CoinGecko-style client.

    Uses httpx.AsyncClient for fully async HTTP calls. The key is injected
    via the 'x-cg-demo-api-key' header, matching CoinGecko's API convention.

    Usage with adummyclient:
        manager = ApiKeyManager([AsyncCoinGeckoClient(k) for k in keys])
        result = await manager.adummyclient.simple.price(ids="bitcoin")
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    def get_primary_key(self):
        return self._api_key

    def create_client(self):
        import httpx
        return _AsyncCoinGeckoSDK(self._api_key)

    def test_usability(self, client):
        # test_usability is sync; async version would use ais_usable()
        return True

    async def atest_usability(self, client):
        try:
            result = await client.ping()
            return True
        except Exception:
            return False


class _AsyncCoinGeckoSDK:
    """Lightweight async CoinGecko SDK wrapper using httpx.AsyncClient."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, api_key: str):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "x-cg-demo-api-key": api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        # Expose sub-resources for ChainProxy navigation
        self.simple = _SimpleResource(self._client)
        self.coins = _CoinsResource(self._client)

    async def ping(self):
        resp = await self._client.get("/ping")
        resp.raise_for_status()
        return resp.json()

    async def aclose(self):
        await self._client.aclose()


class _SimpleResource:
    def __init__(self, client):
        self._client = client
        self.price = _PriceResource(client)


class _PriceResource:
    def __init__(self, client):
        self._client = client

    async def get(self, ids=None, vs_currencies=None, **kwargs):
        params = {}
        if ids:
            params["ids"] = ids
        if vs_currencies:
            params["vs_currencies"] = vs_currencies
        params.update(kwargs)
        resp = await self._client.get("/simple/price", params=params)
        resp.raise_for_status()
        return resp.json()


class _CoinsResource:
    def __init__(self, client):
        self._client = client

    async def markets(self, vs_currency="usd", per_page=100, **kwargs):
        params = {"vs_currency": vs_currency, "per_page": per_page}
        params.update(kwargs)
        resp = await self._client.get("/coins/markets", params=params)
        resp.raise_for_status()
        return resp.json()


# ── Sync main ───────────────────────────────────────────────────────


def sync_main():
    # 1. Login to the apipool server
    tokens = login(
        service_url="http://localhost:8000",
        username="your_username",
        password="your_password",
    )

    # 2. Fetch raw keys for the "coingecko" client_type
    raw_keys = get_keys(
        service_url="http://localhost:8000",
        client_type="coingecko",
        auth_token=tokens["access_token"],
    )
    print(f"Got {len(raw_keys)} CoinGecko API key(s)")

    if not raw_keys:
        print("No keys found. Please add keys with client_type='coingecko' first.")
        return

    # 3. Build local ApiKeyManager with CoinGeckoClient wrappers
    apikey_list = [CoinGeckoClient(key) for key in raw_keys]
    manager = ApiKeyManager(apikey_list=apikey_list)

    # 4. Use transparent key rotation — each call auto-picks a random key
    # CoinGecko SDK chain: client.coins.markets() → 2-level deep
    result = manager.dummyclient.coins.markets(vs_currency="usd", per_page=5)
    print(f"Top 5 coins: {[c['name'] for c in result]}")

    # Another example: client.simple.price()
    price = manager.dummyclient.simple.price(ids="bitcoin", vs_currencies="usd")
    print(f"BTC price: {price}")


# ── Async main ──────────────────────────────────────────────────────


async def async_main():
    # 1. Login to the apipool server (async)
    tokens = await alogin(
        service_url="http://localhost:8000",
        username="your_username",
        password="your_password",
    )

    # 2. Fetch raw keys (async)
    raw_keys = await aget_keys(
        service_url="http://localhost:8000",
        client_type="coingecko",
        auth_token=tokens["access_token"],
    )
    print(f"Got {len(raw_keys)} CoinGecko API key(s)")

    if not raw_keys:
        print("No keys found. Please add keys with client_type='coingecko' first.")
        return

    # 3. Build ApiKeyManager with async CoinGeckoClient wrappers
    apikey_list = [AsyncCoinGeckoClient(key) for key in raw_keys]
    manager = ApiKeyManager(apikey_list=apikey_list)

    # 4. Use adummyclient for async chain calls with key rotation
    # await is all that's needed — same API signature as sync version
    price = await manager.adummyclient.simple.price.get(ids="bitcoin", vs_currencies="usd")
    print(f"BTC price: {price}")

    result = await manager.adummyclient.coins.markets(vs_currency="usd", per_page=5)
    print(f"Top 5 coins: {[c['name'] for c in result]}")

    # Clean up async clients
    for apikey in manager.apikey_chain.values():
        if hasattr(apikey._client, 'aclose'):
            await apikey._client.aclose()


if __name__ == "__main__":
    import sys
    if "--async" in sys.argv:
        asyncio.run(async_main())
    else:
        sync_main()
