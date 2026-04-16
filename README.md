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
    pool_identifier="coingecko",
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
| Fetch raw keys | `get_keys(service_url, pool_identifier, auth_token)` | `await aget_keys(...)` |

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
        pool_identifier="coingecko",
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
        pool_identifier="coingecko",
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
| `config_fetcher` | `Callable[[], PoolConfig]` | Returns pool config from server (optional) |

## Configuration Sync

`DynamicKeyManager` can automatically sync configuration from the server.
Pass a `config_fetcher` (typically `get_config` bound with your credentials)
to enable automatic config synchronization on each refresh cycle.

### PoolConfig

Server-side pool configuration is stored as `pool_config` JSON and synced to
the client as a `PoolConfig` dataclass:

| Field | Type | Default | Description |
|---|---|---|---|
| `concurrency` | `int` | `0` | Max concurrent calls (0 = unlimited) |
| `timeout` | `float` | `30.0` | Per-request timeout in seconds |
| `rate_limit` | `int` | `0` | Max requests per key per interval |
| `rate_limit_interval` | `int` | `60` | Interval for rate limit counting |
| `retry_on_failure` | `bool` | `False` | Retry failed calls on another key |
| `max_retries` | `int` | `0` | Maximum retry attempts |
| `custom` | `dict` | `{}` | Arbitrary key-value settings |
| `batch_retry_on_failure` | `bool \| None` | `None` | Batch retry (falls back to `retry_on_failure`) |
| `batch_max_retries` | `int \| None` | `None` | Batch retries (falls back to `max_retries`) |
| `ban_threshold` | `int` | `3` | Consecutive failures before key ban |
| `ban_duration` | `float` | `300.0` | Key ban duration in seconds |
| `reach_limit_exception` | `str` | `None` | Dotted path to exception class |
| `rotation_strategy` | `str` | `"random"` | Key rotation strategy |

### Sync Example

```python
from apipool import DynamicKeyManager, get_keys, get_config, login

tokens = login("http://localhost:8000", "alice", "password")

manager = DynamicKeyManager(
    key_fetcher=lambda: get_keys(
        service_url="http://localhost:8000",
        pool_identifier="coingecko",
        auth_token=tokens["access_token"],
    ),
    api_key_factory=lambda raw_key: CoinGeckoApiKey(raw_key),
    config_fetcher=lambda: get_config(
        service_url="http://localhost:8000",
        pool_identifier="my-pool",
        auth_token=tokens["access_token"],
    ),
    refresh_interval=120,
)

# Config is auto-synced. Access it anytime:
print(f"Concurrency: {manager.config.concurrency}")
print(f"Timeout: {manager.config.timeout}")
```

### Manual Config Fetch

```python
from apipool import get_config, aget_config

# Sync
config = get_config("http://localhost:8000", "my-pool", tokens["access_token"])
manager.apply_config(config)

# Async
config = await aget_config("http://localhost:8000", "my-pool", tokens["access_token"])
```

## Concurrent Execution

Execute the same method across multiple argument sets with bounded concurrency:

### Sync: `call_concurrent`

```python
# Execute 100 API calls with max 10 concurrent
results = manager.call_concurrent(
    method_name="some_api_method",
    args_list=[(arg1,), (arg2,), (arg3,)],
    kwargs_list=[{"key": "a"}, {"key": "b"}, {"key": "c"}],
    max_concurrency=10,   # overrides config.concurrency
    timeout=15.0,         # overrides config.timeout
)
```

### Async: `acall_concurrent`

```python
results = await manager.acall_concurrent(
    method_name="coins.simple.price.get",
    args_list=[(), (), ()],
    kwargs_list=[
        {"ids": "bitcoin"},
        {"ids": "ethereum"},
        {"ids": "solana"},
    ],
    max_concurrency=5,
    timeout=10.0,
)
```

Concurrency and timeout default to `manager.config` values when not specified.

## Batch Execution

`batch_exec` and `abatch_exec` are designed for **high-volume workloads**
such as fetching 10 000 token prices from CoinGecko.  Key features:

- **Deduplication** — each `item_id` is guaranteed to execute at most once.
- **Retry with rotation** — when an API call fails, the item is retried on a
  *different* key, honouring the key rotation strategy.
- **Temporary banning** — keys that accumulate `ban_threshold` consecutive
  failures are temporarily excluded from the batch group for `ban_duration`
  seconds, then automatically re-admitted.
- **Server-configurable** — all tuning parameters can be set centrally in
  `pool_config` on the server and synced to clients via `PoolConfig`.

### Sync: `batch_exec`

```python
from apipool import ApiKeyManager, BatchResult

manager = ApiKeyManager(apikey_list=apikeys)

# Each item is (item_id, args_tuple, kwargs_dict)
items = [
    ("bitcoin",  (), {"ids": "bitcoin",  "vs_currencies": "usd"}),
    ("ethereum", (), {"ids": "ethereum", "vs_currencies": "usd"}),
    # ... up to 10 000 items
]

result: BatchResult = manager.batch_exec(
    method_name="coins.simple.price.get",
    items=items,
    max_concurrency=20,    # 20 parallel calls
    timeout=10.0,          # per-call timeout
    retry_on_failure=True, # retry on another key
    max_retries=3,         # up to 3 retries per item
    ban_threshold=3,       # ban key after 3 consecutive failures
    ban_duration=300.0,    # ban for 5 minutes
)

print(f"Success: {result.succeeded}/{result.total} ({result.success_rate:.1%})")
print(f"Failed items: {list(result.errors.keys())}")
print(f"Banned keys: {list(result.banned_keys.keys())}")

# Access individual results
btc_price = result.results["bitcoin"]
```

### Async: `abatch_exec`

```python
result: BatchResult = await manager.abatch_exec(
    method_name="coins.simple.price.get",
    items=items,
    max_concurrency=50,
    retry_on_failure=True,
    max_retries=3,
)
```

### BatchResult

| Field | Type | Description |
|---|---|---|
| `total` | `int` | Total items submitted |
| `succeeded` | `int` | Items that completed successfully |
| `failed` | `int` | Items that failed after all retries |
| `results` | `dict` | `item_id → result` for successful items |
| `errors` | `dict` | `item_id → Exception` for failed items |
| `banned_keys` | `dict` | `primary_key → ban_expiry_timestamp` |
| `elapsed` | `float` | Wall-clock seconds for the batch |
| `success_rate` | `float` | Property: `succeeded / total` |

### How It Works

| Step | Description |
|---|---|
| 1. Deduplicate | Each `item_id` is unique — no item is executed twice |
| 2. Dispatch | Items are dispatched to `ThreadPoolExecutor` (sync) or `asyncio.Semaphore` (async) |
| 3. Execute | Each call goes through the normal key selection → ChainProxy → stats pipeline |
| 4. Fail → Retry | On failure, the item is retried on a *different* key (up to `max_retries`) |
| 5. Ban | Keys hitting `ban_threshold` consecutive failures are banned for `ban_duration` |
| 6. Collect | Successful results and final errors are collected into `BatchResult` |

### Batch Config Fields

These `PoolConfig` fields control batch behaviour from the server:

| Field | Type | Default | Description |
|---|---|---|---|
| `batch_retry_on_failure` | `bool \| None` | `None` (→ `retry_on_failure`) | Retry failed items on another key |
| `batch_max_retries` | `int \| None` | `None` (→ `max_retries`) | Max retries per item in batch |
| `ban_threshold` | `int` | `3` | Consecutive failures before banning a key |
| `ban_duration` | `float` | `300.0` | Seconds a banned key is excluded |

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
    BatchResult,

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

    # Configuration
    PoolConfig,

    # Server SDK mode — sync
    connect,
    login,
    get_keys,
    get_config,

    # Server SDK mode — async
    async_connect,
    alogin,
    aget_keys,
    aget_config,
)
```

## License

MIT License
