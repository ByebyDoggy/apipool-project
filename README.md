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
- No uncommon dependencies — only requires `sqlalchemy`.

## Installation

```bash
pip install apipool-ng
```

## Quick Start

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

# Use dummyclient like your real client — keys auto-rotate
result = manager.dummyclient.some_api_method(arg)
```

## DummyClient

Use `manager.dummyclient` just like your original API client.
Under the hood, it automatically selects a usable key, records usage events,
and rotates keys on rate-limit errors.

```python
manager.check_usable()

# Keys are automatically rotated
result = manager.dummyclient.some_method()

for _ in range(10):
    manager.dummyclient.some_method()
```

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

## License

MIT License
