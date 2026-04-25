#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SDK client module - transparent proxy calls to apipool web service.

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
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
from apipool import ApiKey, ApiKeyManager


# ── Pool Configuration ──────────────────────────────────────────────

@dataclass
class PoolConfig:
    """Configuration synced from the apipool-server.

    This dataclass mirrors the server-side pool_config JSON and provides
    typed defaults for all configurable parameters.  The client-side
    ``DynamicKeyManager`` calls :func:`get_config` periodically and
    applies changes via :meth:`ApiKeyManager.apply_config`.

    Attributes:
        concurrency: Max number of concurrent API calls (0 = unlimited).
        timeout: Per-request timeout in seconds.
        rate_limit: Max requests per key per interval (0 = unlimited).
        rate_limit_interval: Interval in seconds for rate_limit counting.
        retry_on_failure: Whether to retry failed calls on another key.
        max_retries: Maximum retry attempts per item before giving up.
        custom: Arbitrary key-value pairs for user-defined settings.
        batch_retry_on_failure: Whether batch_exec retries failed items on
            another key (defaults to ``retry_on_failure`` if not set).
        batch_max_retries: Max retries per item in batch_exec (defaults to
            ``max_retries`` if not set).
        ban_threshold: Number of consecutive failures before a key is
            temporarily banned from the batch group.
        ban_duration: Seconds a key stays banned before being re-admitted.
        reach_limit_exception: Dotted path to the exception class that
            signals key exhaustion (e.g. ``"openai.error.RateLimitError"``).
            When ``None`` or empty, **any** ``Exception`` triggers key
            rotation (the new default).  Set a specific class to narrow
            down which errors cause a key swap.
    """
    concurrency: int = 0
    timeout: float = 30.0
    rate_limit: int = 0
    rate_limit_interval: int = 60
    retry_on_failure: bool = False
    max_retries: int = 0
    custom: dict = field(default_factory=dict)

    # Batch execution tuning
    batch_retry_on_failure: Optional[bool] = None
    batch_max_retries: Optional[int] = None
    ban_threshold: int = 3
    ban_duration: float = 300.0

    # Server-level fields (not in pool_config JSON, but from pool record)
    reach_limit_exception: Optional[str] = None
    rotation_strategy: str = "random"
    client_type: str = ""

    @property
    def effective_batch_retry(self) -> bool:
        """Resolved batch retry setting (falls back to retry_on_failure)."""
        if self.batch_retry_on_failure is not None:
            return self.batch_retry_on_failure
        return self.retry_on_failure

    @property
    def effective_batch_max_retries(self) -> int:
        """Resolved batch max retries (falls back to max_retries)."""
        if self.batch_max_retries is not None:
            return self.batch_max_retries
        return self.max_retries

    @classmethod
    def from_server_response(cls, data: dict) -> "PoolConfig":
        """Build a PoolConfig from the GET /pools/{id}/config response."""
        raw_config = data.get("pool_config") or {}
        return cls(
            concurrency=raw_config.get("concurrency", 0),
            timeout=raw_config.get("timeout", 30.0),
            rate_limit=raw_config.get("rate_limit", 0),
            rate_limit_interval=raw_config.get("rate_limit_interval", 60),
            retry_on_failure=raw_config.get("retry_on_failure", False),
            max_retries=raw_config.get("max_retries", 0),
            custom=raw_config.get("custom", {}),
            batch_retry_on_failure=raw_config.get("batch_retry_on_failure"),
            batch_max_retries=raw_config.get("batch_max_retries"),
            ban_threshold=raw_config.get("ban_threshold", 3),
            ban_duration=raw_config.get("ban_duration", 300.0),
            reach_limit_exception=data.get("reach_limit_exception"),
            rotation_strategy=data.get("rotation_strategy", "random"),
            client_type=data.get("client_type", ""),
        )


# ── Synchronous client ──────────────────────────────────────────────

class ServiceApiKey(ApiKey):
    """Server-proxied ApiKey: no sensitive key material held locally."""

    def __init__(self, service_url: str, pool_identifier: str, auth_token: str, key_id: str):
        self._service_url = service_url.rstrip("/")
        self._pool_identifier = pool_identifier
        self._auth_token = auth_token
        self._key_id = key_id

    def get_primary_key(self):
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
    Async version of connect -- creates an ApiKeyManager with AsyncServiceApiKey
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
    await api_key.aconnect_client()
    api_key._client_connected = True

    manager = ApiKeyManager([api_key])

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
    pool_identifier: str,
    auth_token: str,
) -> list[str]:
    """
    Fetch decrypted raw API keys from the server for a given pool.

    This is the building block for constructing local SDK clients with
    key rotation. The typical workflow is:

        1. login()     -> get auth_token
        2. get_keys()  -> get raw keys as list[str]
        3. Wrap keys into your own ApiKey subclass (e.g. CoinGeckoClient)
        4. Build ApiKeyManager for transparent key rotation

    Args:
        service_url: Base URL of the apipool server
        pool_identifier: Pool identifier to fetch keys from (e.g. "ethereum-rpc")
        auth_token: JWT access token for authentication

    Returns:
        list[str] - the raw (decrypted) API key strings

    Example:
        from apipool import login, get_keys, ApiKeyManager

        tokens = login("http://localhost:8000", "alice", "password")
        keys = get_keys(
            service_url="http://localhost:8000",
            pool_identifier="ethereum-rpc",
            auth_token=tokens["access_token"],
        )
    """
    with httpx.Client(
        base_url=service_url.rstrip("/"),
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    ) as client:
        resp = client.get(
            "/api/v1/keys/raw",
            params={"pool_identifier": pool_identifier},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["raw_key"] for item in data.get("keys", [])]


async def aget_keys(
    service_url: str,
    pool_identifier: str,
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
            params={"pool_identifier": pool_identifier},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["raw_key"] for item in data.get("keys", [])]


# ── Config sync helpers ─────────────────────────────────────────────

def get_config(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
) -> PoolConfig:
    """Fetch pool configuration from the apipool-server.

    Returns a :class:`PoolConfig` instance with all server-side settings
    (concurrency, timeout, rate_limit, reach_limit_exception, etc.)
    that the client-side manager should apply.

    Args:
        service_url: Base URL of the apipool server
        pool_identifier: The pool identifier to query
        auth_token: JWT access token for authentication

    Returns:
        PoolConfig -- typed configuration object
    """
    with httpx.Client(
        base_url=service_url.rstrip("/"),
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    ) as client:
        resp = client.get(f"/api/v1/pools/{pool_identifier}/config")
        resp.raise_for_status()
        return PoolConfig.from_server_response(resp.json())


async def aget_config(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
) -> PoolConfig:
    """Async version of get_config."""
    async with httpx.AsyncClient(
        base_url=service_url.rstrip("/"),
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    ) as client:
        resp = await client.get(f"/api/v1/pools/{pool_identifier}/config")
        resp.raise_for_status()
        return PoolConfig.from_server_response(resp.json())


# ── Convenience: connect with stats reporting ───────────────────────

def connect_with_stats(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
    refresh_interval: float = 60.0,
    stats_report_interval: float = 30.0,
) -> "DynamicKeyManager":
    """Connect to an apipool service with stats reporting enabled.

    Creates a DynamicKeyManager that:
    - Periodically fetches keys from the server
    - Periodically reports API call statistics back to the server
    - Uses file-based SQLite for persistent local stats

    Args:
        service_url: Base URL of the apipool server
        pool_identifier: The pool identifier to use
        auth_token: JWT access token for authentication
        refresh_interval: Seconds between key refreshes
        stats_report_interval: Seconds between stats reports

    Returns:
        DynamicKeyManager with stats reporting configured.

    Example::

        from apipool import connect_with_stats, login

        tokens = login("http://localhost:8000", "alice", "password")
        manager = connect_with_stats(
            service_url="http://localhost:8000",
            pool_identifier="my-pool",
            auth_token=tokens["access_token"],
        )
        result = manager.dummyclient.ping()
        manager.shutdown()
    """
    from .manager import DynamicKeyManager

    return DynamicKeyManager(
        key_fetcher=lambda: get_keys(service_url, pool_identifier, auth_token),
        api_key_factory=lambda raw_key: _GenericApiKey(raw_key),
        refresh_interval=refresh_interval,
        config_fetcher=lambda: get_config(service_url, pool_identifier, auth_token),
        pool_identifier=pool_identifier,
        stats_report_url=service_url,
        stats_report_token=auth_token,
        stats_report_interval=stats_report_interval,
    )


class _GenericApiKey(ApiKey):
    """Minimal ApiKey subclass that stores the raw key as primary_key."""

    def __init__(self, raw_key: str):
        self._raw_key = raw_key

    def get_primary_key(self):
        return self._raw_key

    def create_client(self):
        return _GenericClient()

    def test_usability(self, client):
        return True


class _GenericClient:
    """Placeholder client for _GenericApiKey — actual API calls go through
    the service proxy or are handled by user-provided client classes."""

    def __getattr__(self, item):
        raise AttributeError(
            f"_GenericClient does not implement '{item}'. "
            "Provide your own api_key_factory with a real client class, "
            "or use connect() for server-proxied calls."
        )


async def async_connect_with_stats(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
    refresh_interval: float = 60.0,
    stats_report_interval: float = 30.0,
) -> "AsyncDynamicKeyManager":
    """Async version of connect_with_stats.

    Creates an AsyncDynamicKeyManager with stats reporting enabled.

    Example::

        from apipool import async_connect_with_stats, alogin

        tokens = await alogin("http://localhost:8000", "alice", "password")
        manager = await async_connect_with_stats(
            service_url="http://localhost:8000",
            pool_identifier="my-pool",
            auth_token=tokens["access_token"],
        )
        result = await manager.adummyclient.ping()
        await manager.ashutdown()
    """
    from .manager import AsyncDynamicKeyManager

    manager = AsyncDynamicKeyManager(
        key_fetcher=lambda: aget_keys(service_url, pool_identifier, auth_token),
        api_key_factory=lambda raw_key: _GenericApiKey(raw_key),
        refresh_interval=refresh_interval,
        config_fetcher=lambda: aget_config(service_url, pool_identifier, auth_token),
        pool_identifier=pool_identifier,
        stats_report_url=service_url,
        stats_report_token=auth_token,
        stats_report_interval=stats_report_interval,
    )
    await manager.astart()
    return manager