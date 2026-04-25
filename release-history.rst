Release and Version History
==============================================================================


1.0.9 (2026-04-25)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Features and Improvements**

- **Stats reporting**: `DynamicKeyManager` and `AsyncDynamicKeyManager` now
  automatically report local API call statistics to `apipool-server` via a
  background thread/asyncio task. Events include latency and method name.
- **Enhanced event model**: `StatsCollector.add_event()` accepts new optional
  parameters ``latency`` and ``method``. The Event table is auto-migrated for
  existing databases.
- **Latency & method tracking**: `ApiCaller` / `AsyncApiCaller` automatically
  record wall-clock latency and the full attribute path (e.g.
  ``"coins.simple.price.get"``) for every API call.
- **Batch event operations**: New `StatsCollector.fetch_events_batch()` and
  `delete_events()` methods enable efficient report-then-delete workflows.
- **Convenience functions**: New `connect_with_stats()` and
  `async_connect_with_stats()` one-line setup with stats reporting enabled.
- **Persistent local SQLite**: When `pool_identifier` is provided, stats are
  stored in a file-based SQLite database that survives process restarts.
- **Server endpoint**: New ``POST /api/v1/stats/report`` endpoint and
  ``client_call_logs`` table for receiving client-reported statistics.
- **47 new unit tests** covering all stats reporting features.


0.0.3 (todo)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Features and Improvements**

**Minor Improvements**

**Bugfixes**

**Miscellaneous**


0.0.2 (2018-08-21)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Features and Improvements**

- rewrite the core code.
- add database backed stats collector feature. convinent events query is provided.

**Minor Improvements**

- use pygitrepo skeleton.


0.0.1 (2017-04-06)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- First release