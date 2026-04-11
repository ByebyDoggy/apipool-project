# apipool-ng

`apipool-ng` is a next-generation **Multiple API Key Manager**.

It allows developers to manage multiple API keys simultaneously. For example,
if a single API key has 1000/day quota, you can register 10 API keys and let
`apipool-ng` automatically rotate them.

## Features

- Automatically rotate API keys across multiple credentials.
- Built-in usage statistics, searchable by time, status, and apikey.
  Stats collector can be deployed on any relational database (SQLite by default).
- Clean API, minimal code required to implement complex features.
- **Async support** — `adummyclient` provides full async chain-proxy with `await`.
- **Server SDK mode** — connect to an `apipool-server` instance and proxy all API
  calls through it, with transparent key rotation and zero local key material.
- **Dynamic scaling** — `DynamicKeyManager` auto-refreshes keys from server,
  expanding or shrinking the pool in real time.
- Lightweight dependencies — `sqlalchemy` + `httpx`.

## Installation

```bash
pip install apipool-ng
```

## Quick Start

### Library Mode (Local Keys)

Implement an `ApiKey` subclass, then create an `ApiKeyManager`:

```python
from apipool import ApiKey, ApiKeyManager

class MyApiKey(ApiKey):
    def __init__(self, key):
        self.key = key

    def get_primary_key(self):
        return self.key

    def create_client(self):
        return MyApiClient(api_key=self.key)

    def test_usability(self, client):
        return client.test_connection()

apikeys = [MyApiKey(k) for k in ["key1", "key2", "key3"]]
manager = ApiKeyManager(apikey_list=apikeys)
manager.check_usable()

# Synchronous calls — keys auto-rotate
result = manager.dummyclient.some_api_method(arg)
```

### Server SDK Mode (Remote Proxy)

Connect to an `apipool-server` instance — no API keys stored locally:

```python
import os
from apipool import connect, login

# 1. Authenticate
tokens = login(
    service_url="http://localhost:8000",
    username="alice",
    password="password",
)

# 2. Connect to a pool
manager = connect(
    service_url="http://localhost:8000",
    pool_identifier="google-geocoding",
    auth_token=tokens["access_token"],
)

# 3. Use exactly like library mode
result = manager.dummyclient.geocode("1600 Amphitheatre Parkway")
```

### Fetch Raw Keys from Server

Retrieve decrypted keys and build a local `ApiKeyManager`:

```python
from apipool import login, get_keys, ApiKeyManager

tokens = login("http://localhost:8000", "alice", "password")
raw_keys = get_keys(
    service_url="http://localhost:8000",
    client_type="coingecko",
    auth_token=tokens["access_token"],
)
# raw_keys = ["CG-xxx", "CG-yyy", ...]
```

## DummyClient & AsyncDummyClient

Use `manager.dummyclient` (sync) or `manager.adummyclient` (async) just like
your original API client. Under the hood, they automatically select a usable
key, record usage events, and rotate keys on rate-limit errors.

```python
# Sync — use dummyclient
result = manager.dummyclient.some_method()

# Async — use adummyclient
result = await manager.adummyclient.some_method()

# Multi-level attribute chains are supported natively
result = await manager.adummyclient.coins.simple.price.get(ids="bitcoin")
```

### Rate Limit Handling

Specify the exception type that indicates rate-limit exhaustion:

```python
from apipool import ApiKeyManager

manager = ApiKeyManager(
    apikey_list=apikeys,
    reach_limit_exc=RateLimitError,  # auto-rotate on this exception
)
```

When a call raises `reach_limit_exc`, the key is automatically removed from
the pool and the exception is re-raised. When all keys are exhausted,
`PoolExhaustedError` is raised on the next call.

```python
from apipool import ApiKeyManager, PoolExhaustedError

try:
    result = manager.dummyclient.some_method()
except PoolExhaustedError:
    print("All API keys exhausted")
```

## Server SDK Mode (Full API)

| Function | Sync | Async |
|---|---|---|
| Authenticate | `login(service_url, username, password)` | `await alogin(...)` |
| Connect to pool | `connect(service_url, pool_identifier, auth_token)` | `await async_connect(...)` |
| Fetch raw keys | `get_keys(service_url, client_type, auth_token)` | `await aget_keys(...)` |

Async example:

```python
from apipool import async_connect, alogin

tokens = await alogin("http://localhost:8000", "alice", "password")
manager = await async_connect(
    service_url="http://localhost:8000",
    pool_identifier="coingecko",
    auth_token=tokens["access_token"],
)
result = await manager.adummyclient.coins.simple.price.get(ids="bitcoin")
```

## Dynamic Key Manager (Auto-Refresh)

`DynamicKeyManager` extends `ApiKeyManager` with a background thread that
periodically fetches the latest key list from `apipool-server` and reconciles
the local pool — **adding new keys** and **removing deleted ones** automatically.

### Sync: DynamicKeyManager

```python
from apipool import DynamicKeyManager, get_keys, login

tokens = login("http://localhost:8000", "alice", "password")

manager = DynamicKeyManager(
    key_fetcher=lambda: get_keys(
        service_url="http://localhost:8000",
        client_type="coingecko",
        auth_token=tokens["access_token"],
    ),
    api_key_factory=lambda raw_key: CoinGeckoApiKey(raw_key),
    refresh_interval=120,  # seconds
    on_keys_added=lambda keys: print(f"Added: {keys}"),
    on_keys_removed=lambda keys: print(f"Removed: {keys}"),
)

# Use like a normal ApiKeyManager
result = manager.dummyclient.ping()
print(f"Pool size: {manager.pool_size}")

# Graceful shutdown
manager.shutdown()
```

### Async: AsyncDynamicKeyManager

```python
from apipool import AsyncDynamicKeyManager, aget_keys, alogin

tokens = await alogin("http://localhost:8000", "alice", "password")

manager = AsyncDynamicKeyManager(
    key_fetcher=lambda: aget_keys(
        service_url="http://localhost:8000",
        client_type="coingecko",
        auth_token=tokens["access_token"],
    ),
    api_key_factory=lambda raw_key: AsyncCoinGeckoKey(raw_key),
    refresh_interval=120,
)

await manager.astart()  # initial fetch + auto-refresh task

result = await manager.adummyclient.coins.simple.price.get(ids="bitcoin")
print(f"Pool size: {manager.pool_size}")

await manager.ashutdown()
```

### How It Works

| Step | Description |
|---|---|
| 1. Fetch | Call `key_fetcher()` to get the latest `list[str]` from the server |
| 2. Diff | Compare server keys vs. local active + archived keys |
| 3. Add | New keys → create via `api_key_factory` → add to pool |
| 4. Restore | Archived keys that reappear on server → restore to active pool |
| 5. Remove | Keys gone from server → remove from active pool to archive |
| 6. Callback | `on_keys_added` / `on_keys_removed` fired if keys changed |

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `key_fetcher` | `Callable[[], list[str]]` | Returns current raw keys from server |
| `api_key_factory` | `Callable[[str], ApiKey]` | Converts raw key to `ApiKey` instance |
| `refresh_interval` | `float` | Seconds between refreshes (default 60) |
| `on_keys_added` | `Callable[[list[str]], None]` | Callback after keys are added |
| `on_keys_removed` | `Callable[[list[str]], None]` | Callback after keys are removed |

## ApiKey Abstract Class

Subclass `ApiKey` and implement three methods:

| Method | Description |
|---|---|
| `get_primary_key()` | Return a unique identifier for this key |
| `create_client()` | Create and return the SDK client instance |
| `test_usability(client)` | Test if the key is usable; return `bool` |

Optional async methods on `ApiKey`:

| Method | Description |
|---|---|
| `aconnect_client()` | Async version of `connect_client()` |
| `ais_usable()` | Async version of `is_usable()` |

## StatsCollector

Query usage statistics through `manager.stats`:

```python
from apipool import StatusCollection

# Usage count per key in last hour
manager.stats.usage_count_stats_in_recent_n_seconds(3600)
# {"key1": 3, "key2": 5, "key3": 2}

# Count specific events
count = manager.stats.usage_count_in_recent_n_seconds(
    n_seconds=3600,
    status_id=StatusCollection.c9_ReachLimit.id,
)
```

## API Reference

### Exported Symbols

```python
from apipool import (
    # Core
    ApiKey,
    ApiKeyManager,
    PoolExhaustedError,

    # Async chain proxy
    AsyncDummyClient,
    AsyncChainProxy,
    AsyncApiCaller,

    # Dynamic scaling
    DynamicKeyManager,
    AsyncDynamicKeyManager,

    # Stats
    StatusCollection,
    StatsCollector,

    # Server SDK mode — sync
    connect,
    login,
    get_keys,

    # Server SDK mode — async
    async_connect,
    alogin,
    aget_keys,
)
```

## License

MIT License
