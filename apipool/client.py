#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SDK client module — transparent proxy calls to apipool web service.

Supports both synchronous and asynchronous SDK clients:

Synchronous:
    manager = connect(service_url="http://localhost:8000",
                      pool_identifier="my-pool",
                      auth_token="eyJhbGciOiJIUzI1NiIs...")
    result = manager.dummyclient.geocode("1600 Amphitheatre Parkway")

Asynchronous:
    manager = await async_connect(service_url="http://localhost:8000",
                                   pool_identifier="my-pool",
                                   auth_token="eyJhbGciOiJIUzI1NiIs...")
    result = await manager.adummyclient.coins.simple.price.get(ids="bitcoin")
"""

import inspect
import httpx
from apipool import ApiKey, ApiKeyManager


# ── Synchronous client ──────────────────────────────────────────────


class ServiceApiKey(ApiKey):
    """Server-proxied ApiKey: no sensitive key material held locally."""

    def __init__(self, service_url: str, pool_identifier: str, auth_token: str, key_id: str):
        self._service_url = service_url.rstrip("/")
        self._pool_identifier = pool_identifier
        self._auth_token = auth_token
        self._key_id = key_id

    def get_primary_key(self):
        # Return identifier, NOT the sensitive key
        return self._key_id

    def create_client(self):
        return _ServiceClient(
            base_url=self._service_url,
            pool_identifier=self._pool_identifier,
            auth_token=self._auth_token,
        )

    def test_usability(self, client):
        try:
            resp = client._request("GET", f"/proxy/{self._pool_identifier}/status")
            return resp.get("success", False)
        except Exception:
            return False


class _ServiceClient:
    """HTTP client that forwards all calls to the apipool server."""

    def __init__(self, base_url: str, pool_identifier: str, auth_token: str):
        self._base_url = base_url
        self._pool_identifier = pool_identifier
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=30.0,
        )

    def _request(self, method: str, path: str, **kwargs):
        resp = self._http.request(method, f"/api/v1{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def __getattr__(self, item):
        """Support ChainProxy-style chain navigation."""
        return _ServiceChainLink(self, [item])


class _ServiceChainLink:
    """Chain node: collects attribute path, forwards final call to server."""

    def __init__(self, service_client: _ServiceClient, attr_path: list[str]):
        self._client = service_client
        self._attr_path = list(attr_path)

    def __getattr__(self, item):
        return _ServiceChainLink(self._client, self._attr_path + [item])

    def __call__(self, *args, **kwargs):
        result = self._client._request(
            "POST",
            f"/proxy/{self._client._pool_identifier}/invoke",
            json={
                "attr_path": self._attr_path,
                "args": list(args),
                "kwargs": kwargs,
            },
        )
        if result.get("success"):
            return result.get("data")
        else:
            error = result.get("error", "Unknown error")
            raise RuntimeError(f"Proxy call failed: {error}")


# ── Asynchronous client ─────────────────────────────────────────────


class AsyncServiceApiKey(ApiKey):
    """Async server-proxied ApiKey: uses httpx.AsyncClient."""

    def __init__(self, service_url: str, pool_identifier: str, auth_token: str, key_id: str):
        self._service_url = service_url.rstrip("/")
        self._pool_identifier = pool_identifier
        self._auth_token = auth_token
        self._key_id = key_id

    def get_primary_key(self):
        return self._key_id

    def create_client(self):
        return _AsyncServiceClient(
            base_url=self._service_url,
            pool_identifier=self._pool_identifier,
            auth_token=self._auth_token,
        )

    async def test_usability(self, client):
        try:
            resp = await client._request("GET", f"/proxy/{self._pool_identifier}/status")
            return resp.get("success", False)
        except Exception:
            return False


class _AsyncServiceClient:
    """Async HTTP client that forwards all calls to the apipool server."""

    def __init__(self, base_url: str, pool_identifier: str, auth_token: str):
        self._base_url = base_url
        self._pool_identifier = pool_identifier
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=30.0,
        )

    async def _request(self, method: str, path: str, **kwargs):
        resp = await self._http.request(method, f"/api/v1{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def __getattr__(self, item):
        """Support AsyncChainProxy-style chain navigation."""
        return _AsyncServiceChainLink(self, [item])


class _AsyncServiceChainLink:
    """Async chain node: collects attribute path, forwards final call to server."""

    def __init__(self, service_client: _AsyncServiceClient, attr_path: list[str]):
        self._client = service_client
        self._attr_path = list(attr_path)

    def __getattr__(self, item):
        return _AsyncServiceChainLink(self._client, self._attr_path + [item])

    async def __call__(self, *args, **kwargs):
        result = await self._client._request(
            "POST",
            f"/proxy/{self._client._pool_identifier}/invoke",
            json={
                "attr_path": self._attr_path,
                "args": list(args),
                "kwargs": kwargs,
            },
        )
        if result.get("success"):
            return result.get("data")
        else:
            error = result.get("error", "Unknown error")
            raise RuntimeError(f"Proxy call failed: {error}")


# ── Public API: sync ────────────────────────────────────────────────


def connect(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
) -> ApiKeyManager:
    """
    Connect to an apipool web service and obtain an ApiKeyManager
    that transparently proxies all calls through the server.

    Args:
        service_url: Base URL of the apipool server (e.g. "http://localhost:8000")
        pool_identifier: The pool identifier to use for API calls
        auth_token: JWT access token for authentication

    Returns:
        ApiKeyManager with a single ServiceApiKey that proxies through the server.
        ChainProxy, key rotation, and statistics work transparently.

    Example:
        manager = connect(
            service_url="http://localhost:8000",
            pool_identifier="google-geocoding",
            auth_token=os.environ["APIPOOL_TOKEN"],
        )
        # Business code is identical to the library mode:
        result = manager.dummyclient.geocode("1600 Amphitheatre Parkway")
    """
    api_key = ServiceApiKey(
        service_url=service_url,
        pool_identifier=pool_identifier,
        auth_token=auth_token,
        key_id=f"service-proxy:{pool_identifier}",
    )
    manager = ApiKeyManager([api_key])
    return manager


# ── Public API: async ───────────────────────────────────────────────


async def async_connect(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
) -> ApiKeyManager:
    """
    Async version of connect — creates an ApiKeyManager with AsyncServiceApiKey
    that uses httpx.AsyncClient for all proxy calls.

    Use ``adummyclient`` for async chain calls::

        manager = await async_connect(...)
        result = await manager.adummyclient.coins.simple.price.get(ids="bitcoin")

    Args:
        service_url: Base URL of the apipool server
        pool_identifier: The pool identifier to use for API calls
        auth_token: JWT access token for authentication

    Returns:
        ApiKeyManager with a single AsyncServiceApiKey.
    """
    api_key = AsyncServiceApiKey(
        service_url=service_url,
        pool_identifier=pool_identifier,
        auth_token=auth_token,
        key_id=f"async-service-proxy:{pool_identifier}",
    )
    # Pre-connect the async client so ApiKeyManager.__init__ finds it ready
    await api_key.aconnect_client()
    # Temporarily mark as already connected so add_one skips connect_client()
    api_key._client_connected = True

    manager = ApiKeyManager([api_key])

    # Clean up the temp flag
    if hasattr(api_key, "_client_connected"):
        del api_key._client_connected

    return manager


# ── Auth helpers ────────────────────────────────────────────────────


def login(service_url: str, username: str, password: str) -> dict:
    """
    Authenticate with the apipool server and return tokens.

    Returns:
        dict with "access_token", "refresh_token", "token_type", "expires_in"

    Example:
        tokens = login("http://localhost:8000", "alice", "password")
        manager = connect(
            service_url="http://localhost:8000",
            pool_identifier="google-geocoding",
            auth_token=tokens["access_token"],
        )
    """
    with httpx.Client(base_url=service_url.rstrip("/")) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        return resp.json()


async def alogin(service_url: str, username: str, password: str) -> dict:
    """Async version of login."""
    async with httpx.AsyncClient(base_url=service_url.rstrip("/")) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        return resp.json()


# ── Key retrieval helpers ───────────────────────────────────────────


def get_keys(
    service_url: str,
    client_type: str,
    auth_token: str,
) -> list[str]:
    """
    Fetch decrypted raw API keys from the server for a given client_type.

    This is the building block for constructing local SDK clients with
    key rotation. The typical workflow is:

        1. login()     → get auth_token
        2. get_keys()  → get raw keys as list[str]
        3. Wrap keys into your own ApiKey subclass (e.g. CoinGeckoClient)
        4. Build ApiKeyManager for transparent key rotation

    Args:
        service_url: Base URL of the apipool server
        client_type: The client_type label to filter keys by (e.g. "coingecko")
        auth_token: JWT access token for authentication

    Returns:
        list[str] — the raw (decrypted) API key strings

    Example:
        from apipool import login, get_keys, ApiKeyManager

        tokens = login("http://localhost:8000", "alice", "password")
        keys = get_keys(
            service_url="http://localhost:8000",
            client_type="coingecko",
            auth_token=tokens["access_token"],
        )
        # keys = ["CG-xxx", "CG-yyy", ...]
    """
    with httpx.Client(
        base_url=service_url.rstrip("/"),
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    ) as client:
        resp = client.get(
            "/api/v1/keys/raw",
            params={"client_type": client_type},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["raw_key"] for item in data.get("keys", [])]


async def aget_keys(
    service_url: str,
    client_type: str,
    auth_token: str,
) -> list[str]:
    """Async version of get_keys."""
    async with httpx.AsyncClient(
        base_url=service_url.rstrip("/"),
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    ) as client:
        resp = await client.get(
            "/api/v1/keys/raw",
            params={"client_type": client_type},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["raw_key"] for item in data.get("keys", [])]
