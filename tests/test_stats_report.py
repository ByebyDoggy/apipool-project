#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Unit tests for the new client stats reporting features:

1. StatsCollector: latency/method columns, migration, fetch_events_batch, delete_events
2. ApiCaller/AsyncApiCaller: latency and method recording
3. ChainProxy: attr_path propagation
4. DynamicKeyManager: stats reporting background thread
5. AsyncDynamicKeyManager: async stats reporting
6. Server-side: StatsService.receive_report, ClientCallLog, POST /stats/report
"""

import asyncio
import os
import time
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, inspect

from apipool.stats import StatsCollector, StatusCollection, Event, ApiKey, Base
from apipool.manager import (
    ApiCaller,
    AsyncApiCaller,
    ChainProxy,
    DynamicKeyManager,
    AsyncDynamicKeyManager,
    ApiKeyManager,
)
from apipool.apikey import ApiKey as ApiKeyBase
from apipool.tests import (
    GoogleMapApiKey,
    NestedApiKey,
    CoinGeckoStyleApiKey,
    AsyncNestedApiKey,
    AsyncCoinGeckoStyleApiKey,
    ReachLimitError,
    apikeys,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. StatsCollector new features
# ═══════════════════════════════════════════════════════════════════════


class TestEventLatencyMethodColumns:
    """Test that Event model has latency and method columns."""

    def test_event_has_latency_column(self):
        assert hasattr(Event, "latency")
        col = Event.__table__.c.latency
        assert col.nullable is True

    def test_event_has_method_column(self):
        assert hasattr(Event, "method")
        col = Event.__table__.c.method
        assert col.nullable is True


class TestAddEventWithLatencyMethod:
    """Test add_event with latency and method parameters."""

    @pytest.fixture
    def collector(self):
        engine = create_engine("sqlite:///:memory:")
        c = StatsCollector(engine=engine)
        c.add_all_apikey([GoogleMapApiKey(apikey=k) for k in apikeys])
        return c

    def test_add_event_with_latency(self, collector):
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id, latency=0.5)
        events = collector.fetch_events_batch(limit=10)
        assert len(events) == 1
        assert events[0]["latency"] == 0.5

    def test_add_event_with_method(self, collector):
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id, method="geocode")
        events = collector.fetch_events_batch(limit=10)
        assert len(events) == 1
        assert events[0]["method"] == "geocode"

    def test_add_event_with_both(self, collector):
        collector.add_event(
            "example1@gmail.com", StatusCollection.c1_Success.id,
            latency=1.23, method="get_lat_lng_by_address",
        )
        events = collector.fetch_events_batch(limit=10)
        assert len(events) == 1
        assert events[0]["latency"] == 1.23
        assert events[0]["method"] == "get_lat_lng_by_address"

    def test_add_event_without_latency_method(self, collector):
        """Backward compatibility: add_event without new params should still work."""
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id)
        events = collector.fetch_events_batch(limit=10)
        assert len(events) == 1
        assert events[0]["latency"] is None
        assert events[0]["method"] is None


class TestMigrateEventTable:
    """Test _migrate_event_table adds columns to existing tables."""

    def test_migration_adds_latency_and_method(self):
        from sqlalchemy import text

        engine = create_engine("sqlite:///:memory:")
        # Create old schema WITHOUT latency/method columns
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE apikey (id INTEGER PRIMARY KEY, key VARCHAR UNIQUE)"))
            conn.execute(text("CREATE TABLE status (id INTEGER PRIMARY KEY, description VARCHAR UNIQUE)"))
            conn.execute(text(
                "CREATE TABLE event (apikey_id INTEGER, finished_at DATETIME, "
                "status_id INTEGER, PRIMARY KEY(apikey_id, finished_at))"
            ))

        # Now initialize StatsCollector — should migrate
        collector = StatsCollector(engine=engine)

        # Verify columns exist
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("event")}
        assert "latency" in columns
        assert "method" in columns


class TestFetchEventsBatch:
    """Test fetch_events_batch returns events in correct format."""

    @pytest.fixture
    def collector(self):
        engine = create_engine("sqlite:///:memory:")
        c = StatsCollector(engine=engine)
        c.add_all_apikey([GoogleMapApiKey(apikey=k) for k in apikeys])
        return c

    def test_fetch_empty(self, collector):
        result = collector.fetch_events_batch()
        assert result == []

    def test_fetch_returns_correct_fields(self, collector):
        collector.add_event(
            "example1@gmail.com", StatusCollection.c1_Success.id,
            latency=0.3, method="test_method",
        )
        result = collector.fetch_events_batch()
        assert len(result) == 1
        evt = result[0]
        assert "key_identifier" in evt
        assert "status_id" in evt
        assert "latency" in evt
        assert "method" in evt
        assert "finished_at" in evt
        assert "_apikey_id" in evt
        assert "_finished_at" in evt

    def test_fetch_key_identifier_maps_correctly(self, collector):
        collector.add_event("example2@gmail.com", StatusCollection.c1_Success.id)
        result = collector.fetch_events_batch()
        assert result[0]["key_identifier"] == "example2@gmail.com"

    def test_fetch_respects_limit(self, collector):
        for _ in range(10):
            collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id)
        result = collector.fetch_events_batch(limit=5)
        assert len(result) == 5

    def test_fetch_ordered_by_finished_at(self, collector):
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id)
        time.sleep(0.01)
        collector.add_event("example2@gmail.com", StatusCollection.c5_Failed.id)
        result = collector.fetch_events_batch()
        assert result[0]["key_identifier"] == "example1@gmail.com"
        assert result[1]["key_identifier"] == "example2@gmail.com"


class TestDeleteEvents:
    """Test delete_events removes reported events."""

    @pytest.fixture
    def collector(self):
        engine = create_engine("sqlite:///:memory:")
        c = StatsCollector(engine=engine)
        c.add_all_apikey([GoogleMapApiKey(apikey=k) for k in apikeys])
        return c

    def test_delete_events_removes_fetched(self, collector):
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id)
        collector.add_event("example2@gmail.com", StatusCollection.c5_Failed.id)

        events = collector.fetch_events_batch()
        assert len(events) == 2

        collector.delete_events(events)

        remaining = collector.fetch_events_batch()
        assert len(remaining) == 0

    def test_delete_events_partial(self, collector):
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id)
        collector.add_event("example2@gmail.com", StatusCollection.c5_Failed.id)
        collector.add_event("example3@gmail.com", StatusCollection.c1_Success.id)

        events = collector.fetch_events_batch()
        # Delete only the first event
        collector.delete_events([events[0]])

        remaining = collector.fetch_events_batch()
        assert len(remaining) == 2

    def test_delete_events_empty_list(self, collector):
        """delete_events with empty list should not error."""
        collector.delete_events([])

    def test_delete_then_add_new_events(self, collector):
        """Events added after deletion should be fetchable."""
        collector.add_event("example1@gmail.com", StatusCollection.c1_Success.id)
        events = collector.fetch_events_batch()
        collector.delete_events(events)

        collector.add_event(
            "example2@gmail.com", StatusCollection.c1_Success.id,
            latency=0.1, method="new_call",
        )
        events = collector.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["method"] == "new_call"


class TestApikeyIdToKey:
    """Test the reverse mapping _apikey_id_to_key."""

    @pytest.fixture
    def collector(self):
        engine = create_engine("sqlite:///:memory:")
        c = StatsCollector(engine=engine)
        c.add_all_apikey([GoogleMapApiKey(apikey=k) for k in apikeys])
        return c

    def test_reverse_mapping(self, collector):
        mapping = collector._apikey_id_to_key
        # Should be a non-empty dict with int keys and string values
        assert len(mapping) == len(apikeys)
        for pk, aid in collector._cache_apikey.items():
            assert mapping[aid] == pk


# ═══════════════════════════════════════════════════════════════════════
# 2. ApiCaller / AsyncApiCaller latency & method recording
# ═══════════════════════════════════════════════════════════════════════


class TestApiCallerLatencyMethod:
    """Test ApiCaller records latency and method on calls."""

    @pytest.fixture
    def manager(self):
        keys = [GoogleMapApiKey(apikey=k) for k in apikeys[:2]]
        return ApiKeyManager(keys, reach_limit_exc=ReachLimitError)

    def test_success_records_latency_and_method(self, manager):
        apikey = list(manager.apikey_chain.values())[0]
        caller = ApiCaller(
            apikey=apikey,
            apikey_manager=manager,
            call_method=apikey._client.get_lat_lng_by_address,
            reach_limit_exc=ReachLimitError,
            attr_path=["get_lat_lng_by_address"],
        )
        result = caller("test address")
        assert result is not None

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["latency"] is not None
        assert events[0]["latency"] >= 0
        assert events[0]["method"] == "get_lat_lng_by_address"
        assert events[0]["status_id"] == StatusCollection.c1_Success.id

    def test_failure_records_latency_and_method(self, manager):
        apikey = list(manager.apikey_chain.values())[0]
        caller = ApiCaller(
            apikey=apikey,
            apikey_manager=manager,
            call_method=apikey._client.raise_other_error,
            reach_limit_exc=ReachLimitError,
            attr_path=["raise_other_error"],
        )
        with pytest.raises(ValueError):
            caller("test")

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["latency"] is not None
        assert events[0]["method"] == "raise_other_error"
        assert events[0]["status_id"] == StatusCollection.c5_Failed.id

    def test_reach_limit_records_latency_and_method(self, manager):
        apikey = list(manager.apikey_chain.values())[0]
        caller = ApiCaller(
            apikey=apikey,
            apikey_manager=manager,
            call_method=apikey._client.raise_reach_limit_error,
            reach_limit_exc=ReachLimitError,
            attr_path=["raise_reach_limit_error"],
        )
        with pytest.raises(ReachLimitError):
            caller("test")

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["latency"] is not None
        assert events[0]["method"] == "raise_reach_limit_error"
        assert events[0]["status_id"] == StatusCollection.c9_ReachLimit.id

    def test_no_attr_path_records_none_method(self, manager):
        apikey = list(manager.apikey_chain.values())[0]
        caller = ApiCaller(
            apikey=apikey,
            apikey_manager=manager,
            call_method=apikey._client.get_lat_lng_by_address,
            reach_limit_exc=ReachLimitError,
            attr_path=None,
        )
        caller("test address")

        events = manager.stats.fetch_events_batch()
        assert events[0]["method"] is None


class TestAsyncApiCallerLatencyMethod:
    """Test AsyncApiCaller records latency and method on calls."""

    @pytest.fixture
    def manager(self):
        keys = [AsyncNestedApiKey(apikey=k) for k in ["a1@test.com", "a2@test.com"]]
        return ApiKeyManager(keys, reach_limit_exc=ReachLimitError)

    @pytest.mark.asyncio
    async def test_success_records_latency_and_method(self, manager):
        apikey = list(manager.apikey_chain.values())[0]
        caller = AsyncApiCaller(
            apikey=apikey,
            apikey_manager=manager,
            call_method=apikey._client.nested.get_data,
            reach_limit_exc=ReachLimitError,
            attr_path=["nested", "get_data"],
        )
        result = await caller(id=42)
        assert result is not None

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["latency"] is not None
        assert events[0]["method"] == "nested.get_data"
        assert events[0]["status_id"] == StatusCollection.c1_Success.id

    @pytest.mark.asyncio
    async def test_failure_records_latency_and_method(self):
        """Use AsyncCoinGeckoStyleApiKey which has the deep chain with raise_error."""
        keys = [AsyncCoinGeckoStyleApiKey(apikey=k) for k in ["ac1@test.com"]]
        manager = ApiKeyManager(keys, reach_limit_exc=ReachLimitError)
        apikey = list(manager.apikey_chain.values())[0]

        caller = AsyncApiCaller(
            apikey=apikey,
            apikey_manager=manager,
            call_method=apikey._client.a.raise_error,
            reach_limit_exc=ReachLimitError,
            attr_path=["a", "raise_error"],
        )
        with pytest.raises(ValueError):
            await caller()

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["method"] == "a.raise_error"
        assert events[0]["status_id"] == StatusCollection.c5_Failed.id


# ═══════════════════════════════════════════════════════════════════════
# 3. ChainProxy attr_path propagation
# ═══════════════════════════════════════════════════════════════════════


class TestChainProxyAttrPath:
    """Test ChainProxy passes attr_path to ApiCaller for method recording."""

    def test_single_level_attr_path(self):
        keys = [GoogleMapApiKey(apikey=k) for k in apikeys[:2]]
        manager = ApiKeyManager(keys, reach_limit_exc=ReachLimitError)
        result = manager.dummyclient.get_lat_lng_by_address("test")
        assert result is not None

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["method"] == "get_lat_lng_by_address"

    def test_multi_level_attr_path(self):
        keys = [CoinGeckoStyleApiKey(apikey=k) for k in apikeys[:2]]
        manager = ApiKeyManager(keys, reach_limit_exc=ReachLimitError)
        result = manager.dummyclient.coins.simple.price.get(ids="btc", vs_currencies="usd")
        assert result is not None

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["method"] == "coins.simple.price.get"


class TestAsyncChainProxyAttrPath:
    """Test AsyncChainProxy passes attr_path to AsyncApiCaller."""

    @pytest.mark.asyncio
    async def test_multi_level_async_attr_path(self):
        keys = [AsyncCoinGeckoStyleApiKey(apikey=k) for k in ["ac1@test.com"]]
        manager = ApiKeyManager(keys, reach_limit_exc=ReachLimitError)
        result = await manager.adummyclient.coins.simple.price.get(
            ids="btc", vs_currencies="usd"
        )
        assert result is not None

        events = manager.stats.fetch_events_batch()
        assert len(events) == 1
        assert events[0]["method"] == "coins.simple.price.get"


# ═══════════════════════════════════════════════════════════════════════
# 4. check_usable records method
# ═══════════════════════════════════════════════════════════════════════


class TestCheckUsableMethod:
    """Test check_usable records method='check_usable' in stats."""

    def test_check_usable_records_method(self):
        keys = [GoogleMapApiKey(apikey=k) for k in apikeys]
        manager = ApiKeyManager(keys, reach_limit_exc=ReachLimitError)
        manager.check_usable()

        events = manager.stats.fetch_events_batch()
        assert len(events) > 0
        for evt in events:
            assert evt["method"] == "check_usable"


# ═══════════════════════════════════════════════════════════════════════
# 5. DynamicKeyManager stats reporting
# ═══════════════════════════════════════════════════════════════════════


class TestDynamicKeyManagerStatsReport:
    """Test DynamicKeyManager stats reporting functionality."""

    def test_do_report_sends_events_and_deletes(self):
        """_do_report should POST events to server and delete on success."""
        keys = [GoogleMapApiKey(apikey=k) for k in apikeys[:2]]

        # Create manager without stats reporting URL initially
        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,  # don't refresh during test
        )

        # Generate some events
        manager.dummyclient.get_lat_lng_by_address("test1")
        manager.dummyclient.get_lat_lng_by_address("test2")

        events_before = manager.stats.fetch_events_batch()
        assert len(events_before) == 2

        # Set up reporting URL and token
        manager._stats_report_url = "http://fake-server"
        manager._stats_report_token = "test-token"
        manager._pool_identifier = "test-pool"
        manager._stats_report_batch_size = 500

        # Mock httpx.post
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {"accepted": 2}
            mock_post.return_value = mock_response

            manager._do_report()

            # Verify POST was called with correct data
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            json_body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert json_body["pool_identifier"] == "test-pool"
            assert json_body["client_id"] is not None
            assert len(json_body["events"]) == 2
            for evt in json_body["events"]:
                assert "key_identifier" in evt
                assert "status" in evt
                assert "latency" in evt
                assert "method" in evt
                assert "finished_at" in evt

            # Verify events deleted after successful report
            events_after = manager.stats.fetch_events_batch()
            assert len(events_after) == 0

        manager.shutdown()

    def test_do_report_skips_when_no_events(self):
        """_do_report should be a no-op when no events exist."""
        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,
        )

        with patch("httpx.post") as mock_post:
            manager._stats_report_url = "http://fake-server"
            manager._do_report()
            mock_post.assert_not_called()

        manager.shutdown()

    def test_do_report_does_not_delete_on_failure(self):
        """_do_report should NOT delete events if server returns error."""
        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,
        )

        manager.dummyclient.get_lat_lng_by_address("test")

        manager._stats_report_url = "http://fake-server"
        manager._stats_report_token = "test-token"
        manager._pool_identifier = "test-pool"
        manager._stats_report_batch_size = 500

        with patch("httpx.post") as mock_post:
            mock_post.side_effect = Exception("Connection error")
            manager._do_report()

            # Events should still be in the DB
            events = manager.stats.fetch_events_batch()
            assert len(events) == 1

        manager.shutdown()

    def test_file_based_sqlite_when_reporting_enabled(self):
        """When stats_report_url is set and no db_engine, use file-based SQLite."""
        import tempfile

        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,
            pool_identifier="test-file-sqlite",
            stats_report_url="http://fake-server",
            stats_report_token="test-token",
        )

        # The engine URL should contain the file path
        engine_url = str(manager.stats.engine.url)
        assert "apipool_stats" in engine_url
        assert "test-file-sqlite" in engine_url

        manager.shutdown()

    def test_client_id_format(self):
        """_client_id should be hostname:pid format."""
        import socket

        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,
            pool_identifier="test-client-id",
            stats_report_url="http://fake-server",
            stats_report_token="test-token",
        )

        assert ":" in manager._client_id
        hostname, pid = manager._client_id.split(":", 1)
        assert hostname == socket.gethostname()
        assert pid == str(os.getpid())

        manager.shutdown()


class TestDynamicKeyManagerReportThread:
    """Test that the report thread starts and stops correctly."""

    def test_report_thread_starts_when_url_set(self):
        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,
            pool_identifier="test-thread-start",
            stats_report_url="http://fake-server",
            stats_report_token="test-token",
            stats_report_interval=9999,
        )

        assert manager._report_thread is not None
        assert manager._report_thread.is_alive()

        manager.shutdown()

    def test_no_report_thread_when_no_url(self):
        manager = DynamicKeyManager(
            key_fetcher=lambda: apikeys[:2],
            api_key_factory=lambda k: GoogleMapApiKey(apikey=k),
            refresh_interval=9999,
        )

        assert manager._report_thread is None
        manager.shutdown()


# ═══════════════════════════════════════════════════════════════════════
# 6. AsyncDynamicKeyManager stats reporting
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncDynamicKeyManagerStatsReport:
    """Test AsyncDynamicKeyManager async stats reporting."""

    @pytest.mark.asyncio
    async def test_ado_report_sends_events_and_deletes(self):
        manager = AsyncDynamicKeyManager(
            key_fetcher=lambda: ["a1@test.com", "a2@test.com"],
            api_key_factory=lambda k: AsyncNestedApiKey(apikey=k),
            refresh_interval=9999,
            pool_identifier="test-async-report",
            stats_report_url="http://fake-server",
            stats_report_token="test-token",
        )
        await manager.ainit()

        # Add events manually via stats
        manager.stats.add_event(
            "a1@test.com", StatusCollection.c1_Success.id,
            latency=0.1, method="get_data",
        )

        # httpx is imported inside _ado_report, so patch at module level
        import httpx as _real_httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accepted": 1}

        mock_client = MagicMock()

        async def _mock_post(*args, **kwargs):
            return mock_resp

        mock_client.post = _mock_post

        class _FakeAsyncCtx:
            async def __aenter__(self):
                return mock_client
            async def __aexit__(self, *args):
                pass

        with patch.object(_real_httpx, "AsyncClient", return_value=_FakeAsyncCtx()):
            await manager._ado_report()

        # Events should be deleted after successful report
        events = manager.stats.fetch_events_batch()
        assert len(events) == 0

        await manager.ashutdown()

    @pytest.mark.asyncio
    async def test_report_task_starts_when_url_set(self):
        manager = AsyncDynamicKeyManager(
            key_fetcher=lambda: ["a1@test.com"],
            api_key_factory=lambda k: AsyncNestedApiKey(apikey=k),
            refresh_interval=9999,
            pool_identifier="test-async-task",
            stats_report_url="http://fake-server",
            stats_report_token="test-token",
            stats_report_interval=9999,
        )
        await manager.astart()

        assert manager._report_task is not None
        assert not manager._report_task.done()

        # ashutdown cancels tasks which raises CancelledError — catch it
        try:
            await manager.ashutdown()
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_no_report_task_when_no_url(self):
        manager = AsyncDynamicKeyManager(
            key_fetcher=lambda: ["a1@test.com"],
            api_key_factory=lambda k: AsyncNestedApiKey(apikey=k),
            refresh_interval=9999,
        )
        await manager.astart()

        assert manager._report_task is None

        try:
            await manager.ashutdown()
        except asyncio.CancelledError:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 7. Server-side: StatsService.receive_report & ClientCallLog
# ═══════════════════════════════════════════════════════════════════════


class TestStatsServiceReceiveReport:
    """Test StatsService.receive_report method with in-memory SQLite."""

    @pytest.fixture
    def db_session(self):
        """Create an in-memory SQLite session with ClientCallLog table."""
        from sqlalchemy.orm import sessionmaker
        from apipool_server.database import Base as ServerBase

        engine = create_engine("sqlite:///:memory:")
        # Create only the client_call_logs table
        from apipool_server.models.client_call_log import ClientCallLog
        ServerBase.metadata.create_all(engine, tables=[ClientCallLog.__table__])
        Session = sessionmaker(bind=engine)
        return Session()

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 1
        return user

    def test_receive_report_stores_events(self, db_session, mock_user):
        from apipool_server.services.stats_service import StatsService
        from apipool_server.schemas.stats import (
            StatsReportRequest, ClientCallEvent,
        )

        service = StatsService(db_session)

        req = StatsReportRequest(
            pool_identifier="test-pool",
            client_id="host:1234",
            events=[
                ClientCallEvent(
                    key_identifier="key-1",
                    status="success",
                    latency=0.5,
                    method="geocode",
                    finished_at=datetime.now(),
                ),
                ClientCallEvent(
                    key_identifier="key-2",
                    status="failed",
                    latency=1.2,
                    method="reverse_geocode",
                    finished_at=datetime.now(),
                ),
            ],
        )

        result = service.receive_report(mock_user, req)
        assert result.accepted == 2

        # Verify records in DB
        from apipool_server.models.client_call_log import ClientCallLog
        records = db_session.query(ClientCallLog).all()
        assert len(records) == 2
        assert records[0].key_identifier == "key-1"
        assert records[0].status == "success"
        assert records[0].latency == 0.5
        assert records[0].method == "geocode"
        assert records[0].client_id == "host:1234"
        assert records[0].pool_identifier == "test-pool"

    def test_receive_report_empty_events(self, db_session, mock_user):
        from apipool_server.services.stats_service import StatsService
        from apipool_server.schemas.stats import StatsReportRequest

        service = StatsService(db_session)
        req = StatsReportRequest(
            pool_identifier="test-pool",
            client_id="host:1234",
            events=[],
        )

        result = service.receive_report(mock_user, req)
        assert result.accepted == 0


class TestClientCallLogModel:
    """Test ClientCallLog ORM model."""

    def test_model_fields(self):
        from apipool_server.models.client_call_log import ClientCallLog

        log = ClientCallLog(
            user_id=1,
            pool_identifier="test-pool",
            key_identifier="key-1",
            status="success",
            latency=0.5,
            method="geocode",
            finished_at=datetime.now(),
            client_id="host:1234",
        )

        assert log.user_id == 1
        assert log.pool_identifier == "test-pool"
        assert log.key_identifier == "key-1"
        assert log.status == "success"
        assert log.latency == 0.5
        assert log.method == "geocode"
        assert log.client_id == "host:1234"

    def test_model_nullable_fields(self):
        from apipool_server.models.client_call_log import ClientCallLog

        # latency, method, client_id should be nullable
        log = ClientCallLog(
            user_id=1,
            pool_identifier="test-pool",
            key_identifier="key-1",
            status="success",
            finished_at=datetime.now(),
        )
        assert log.latency is None
        assert log.method is None
        assert log.client_id is None


class TestStatsReportSchemas:
    """Test Pydantic schemas for stats reporting."""

    def test_client_call_event(self):
        from apipool_server.schemas.stats import ClientCallEvent

        evt = ClientCallEvent(
            key_identifier="key-1",
            status="success",
            latency=0.5,
            method="geocode",
            finished_at=datetime.now(),
        )
        assert evt.key_identifier == "key-1"
        assert evt.latency == 0.5

    def test_client_call_event_optional_fields(self):
        from apipool_server.schemas.stats import ClientCallEvent

        evt = ClientCallEvent(
            key_identifier="key-1",
            status="success",
            finished_at=datetime.now(),
        )
        assert evt.latency is None
        assert evt.method is None

    def test_stats_report_request(self):
        from apipool_server.schemas.stats import StatsReportRequest, ClientCallEvent

        req = StatsReportRequest(
            pool_identifier="test-pool",
            client_id="host:1234",
            events=[
                ClientCallEvent(
                    key_identifier="key-1",
                    status="success",
                    finished_at=datetime.now(),
                ),
            ],
        )
        assert req.pool_identifier == "test-pool"
        assert len(req.events) == 1

    def test_stats_report_request_optional_client_id(self):
        from apipool_server.schemas.stats import StatsReportRequest

        req = StatsReportRequest(
            pool_identifier="test-pool",
            events=[],
        )
        assert req.client_id is None

    def test_stats_report_response(self):
        from apipool_server.schemas.stats import StatsReportResponse

        resp = StatsReportResponse(accepted=5)
        assert resp.accepted == 5
        assert resp.duplicates == 0


# ═══════════════════════════════════════════════════════════════════════
# 8. Integration: Full round-trip (client → server report)
# ═══════════════════════════════════════════════════════════════════════


class TestFullRoundTrip:
    """Integration test: client creates events, reports to server, server stores them."""

    def test_client_events_to_server_report(self):
        """Simulate the full flow: stats → fetch_batch → report → receive_report."""
        from apipool_server.services.stats_service import StatsService
        from apipool_server.schemas.stats import StatsReportRequest, ClientCallEvent
        from apipool_server.database import Base as ServerBase
        from apipool_server.models.client_call_log import ClientCallLog
        from sqlalchemy.orm import sessionmaker

        # --- Client side: create events ---
        engine = create_engine("sqlite:///:memory:")
        collector = StatsCollector(engine=engine)
        collector.add_all_apikey([GoogleMapApiKey(apikey=k) for k in apikeys[:2]])

        collector.add_event(
            "example1@gmail.com", StatusCollection.c1_Success.id,
            latency=0.5, method="geocode",
        )
        collector.add_event(
            "example2@gmail.com", StatusCollection.c5_Failed.id,
            latency=2.0, method="reverse_geocode",
        )

        # --- Client side: fetch events for reporting ---
        events = collector.fetch_events_batch()
        assert len(events) == 2

        # Build report request (mimic _do_report logic)
        status_map = StatusCollection.get_mapper_id_to_description()
        report_events = []
        for evt in events:
            finished_at = evt["finished_at"]
            report_events.append({
                "key_identifier": evt["key_identifier"],
                "status": status_map.get(evt["status_id"], "unknown"),
                "latency": evt["latency"],
                "method": evt["method"],
                "finished_at": finished_at.isoformat() if finished_at else None,
            })

        req = StatsReportRequest(
            pool_identifier="test-pool",
            client_id="host:1234",
            events=[
                ClientCallEvent(**e) for e in report_events
            ],
        )

        # --- Server side: receive report ---
        server_engine = create_engine("sqlite:///:memory:")
        ServerBase.metadata.create_all(server_engine, tables=[ClientCallLog.__table__])
        Session = sessionmaker(bind=server_engine)
        db = Session()

        mock_user = MagicMock()
        mock_user.id = 1

        service = StatsService(db)
        result = service.receive_report(mock_user, req)
        assert result.accepted == 2

        # Verify server stored correct data
        records = db.query(ClientCallLog).all()
        assert len(records) == 2
        assert records[0].latency == 0.5
        assert records[0].method == "geocode"
        assert records[1].status == "failed"

        # --- Client side: delete after successful report ---
        collector.delete_events(events)
        remaining = collector.fetch_events_batch()
        assert len(remaining) == 0

        db.close()


if __name__ == "__main__":
    import os
    basename = os.path.basename(__file__)
    pytest.main([basename, "-s", "--tb=short", "-v"])
