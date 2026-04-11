#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
built-in stats collector service for api usage and status.
"""

import sys
import random
import inspect
import threading
import logging
import time
from collections import OrderedDict
from typing import Callable, List, Optional
from sqlalchemy import create_engine

from .apikey import ApiKey
from .stats import StatusCollection, StatsCollector

logger = logging.getLogger(__name__)


def validate_is_apikey(obj):
    if not isinstance(obj, ApiKey):  # pragma: no cover
        raise TypeError


class ApiCaller(object):
    def __init__(self, apikey, apikey_manager, call_method, reach_limit_exc):
        self.apikey = apikey
        self.apikey_manager = apikey_manager
        self.call_method = call_method
        self.reach_limit_exc = reach_limit_exc

    def __call__(self, *args, **kwargs):
        try:
            res = self.call_method(*args, **kwargs)
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c1_Success.id,
            )
            return res
        except self.reach_limit_exc as e:
            self.apikey_manager.remove_one(self.apikey.primary_key)
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c9_ReachLimit.id,
            )
            raise e
        except Exception as e:
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c5_Failed.id,
            )
            raise e


class ChainProxy(object):
    """Intermediate proxy for multi-level attribute chain navigation.

    Traverses the attribute chain until ``__call__`` is reached,
    at which point it resolves the real method and delegates to ``ApiCaller``.

    Key characteristics:
    - **Lazy key selection**: ``random_one()`` only happens at ``__call__``
    - **No caching**: each ``.a.b.c`` builds a new lightweight proxy
    - **Fully transparent**: caller code is completely unaware of the proxy
    """

    def __init__(self, manager, attr_path, reach_limit_exc):
        self._manager = manager
        self._attr_path = list(attr_path)
        self._reach_limit_exc = reach_limit_exc

    def __getattr__(self, item):
        """Continue navigating down the attribute chain."""
        return ChainProxy(
            manager=self._manager,
            attr_path=self._attr_path + [item],
            reach_limit_exc=self._reach_limit_exc,
        )

    def __call__(self, *args, **kwargs):
        """End of chain — resolve and execute the actual call."""
        apikey = self._manager.random_one()
        real_client = apikey._client

        target = real_client
        for i, attr in enumerate(self._attr_path):
            try:
                target = getattr(target, attr)
            except AttributeError:
                path_shown = ".".join(self._attr_path[: i + 1])
                raise AttributeError(
                    "ChainProxy: attribute '{}' not found at step {} "
                    "of path '{}' on client {!r}".format(
                        attr, i + 1, ".".join(self._attr_path), type(real_client).__name__
                    )
                ) from None

        if not callable(target):
            path_shown = ".".join(self._attr_path)
            raise TypeError(
                "ChainProxy: attribute path '{}' resolved to non-callable "
                "{} of type {}".format(path_shown, repr(target), type(target).__name__)
            )

        return ApiCaller(
            apikey=apikey,
            apikey_manager=self._manager,
            call_method=target,
            reach_limit_exc=self._reach_limit_exc,
        )(*args, **kwargs)

    def __repr__(self):
        return "ChainProxy(path={})".format(".".join(self._attr_path))


class DummyClient(object):
    def __init__(self):
        self._apikey_manager = None

    def __getattr__(self, item):
        manager = self._apikey_manager

        return ChainProxy(
            manager=manager,
            attr_path=[item],
            reach_limit_exc=manager.reach_limit_exc,
        )


class PoolExhaustedError(Exception):
    """Raised when all API keys in the pool have been exhausted."""
    pass


class NeverRaisesError(Exception):
    pass


class ApiKeyManager(object):
    _settings_api_client_class = None

    def __init__(self, apikey_list, reach_limit_exc=None, db_engine=None):
        # validate
        for apikey in apikey_list:
            validate_is_apikey(apikey)

        # stats collector
        if db_engine is None:
            db_engine = create_sqlite()

        self.stats = StatsCollector(engine=db_engine)
        self.stats.add_all_apikey(apikey_list)

        # initiate apikey chain data
        self.apikey_chain = OrderedDict()
        for apikey in apikey_list:
            self.add_one(apikey, upsert=False)

        self.archived_apikey_chain = OrderedDict()

        if reach_limit_exc is None:
            reach_limit_exc = NeverRaisesError
        self.reach_limit_exc = reach_limit_exc
        self.dummyclient = DummyClient()
        self.dummyclient._apikey_manager = self
        self.adummyclient = AsyncDummyClient()
        self.adummyclient._apikey_manager = self

    def add_one(self, apikey, upsert=False):
        validate_is_apikey(apikey)
        primary_key = apikey.primary_key

        do_insert = False
        if primary_key in self.apikey_chain:
            if upsert:
                do_insert = True
        else:
            do_insert = True

        if do_insert:
            try:
                # If the apikey was already connected (e.g. via aconnect_client),
                # skip the synchronous connect_client() call
                if not getattr(apikey, "_client_connected", False):
                    apikey.connect_client()
                self.apikey_chain[primary_key] = apikey
            except Exception as e:  # pragma: no cover
                sys.stdout.write(
                    "\nCan't create api client with {}, error: {}".format(
                        apikey.primary_key, e)
                )

        # update stats collector
        self.stats.add_all_apikey([apikey, ])

    def fetch_one(self, primary_key):
        return self.apikey_chain[primary_key]

    def remove_one(self, primary_key):
        apikey = self.apikey_chain.pop(primary_key)
        self.archived_apikey_chain[primary_key] = apikey
        return apikey

    def random_one(self):
        if len(self.apikey_chain) == 0:
            raise PoolExhaustedError(
                "All API keys have been exhausted. "
                "{} key(s) in archive.".format(len(self.archived_apikey_chain))
            )
        return random.choice(list(self.apikey_chain.values()))

    def check_usable(self):
        for primary_key, apikey in self.apikey_chain.items():
            if apikey.is_usable():
                self.stats.add_event(
                    primary_key, StatusCollection.c1_Success.id)
            else:
                self.remove_one(primary_key)
                self.stats.add_event(
                    primary_key, StatusCollection.c5_Failed.id)

        if len(self.apikey_chain) == 0:
            sys.stdout.write("\nThere's no API Key usable!")
        elif len(self.archived_apikey_chain) == 0:
            sys.stdout.write("\nAll API Key are usable.")
        else:
            sys.stdout.write("\nThese keys are not usable:")
            for key in self.archived_apikey_chain:
                sys.stdout.write("\n    %s: %r" % (key, apikey))


def create_sqlite():
    return create_engine("sqlite:///:memory:")


# ── Async variants ──────────────────────────────────────────────────


class AsyncApiCaller(object):
    """Async version of ApiCaller — awaits coroutine results and records stats."""

    def __init__(self, apikey, apikey_manager, call_method, reach_limit_exc):
        self.apikey = apikey
        self.apikey_manager = apikey_manager
        self.call_method = call_method
        self.reach_limit_exc = reach_limit_exc

    async def __call__(self, *args, **kwargs):
        try:
            res = self.call_method(*args, **kwargs)
            # If the resolved method is a coroutine, await it
            if inspect.isawaitable(res):
                res = await res
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c1_Success.id,
            )
            return res
        except self.reach_limit_exc as e:
            self.apikey_manager.remove_one(self.apikey.primary_key)
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c9_ReachLimit.id,
            )
            raise e
        except Exception as e:
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c5_Failed.id,
            )
            raise e


class AsyncChainProxy(object):
    """Async version of ChainProxy.

    Behaves identically to ChainProxy for attribute navigation (``__getattr__``),
    but ``__call__`` is an ``async`` method that correctly ``await``s
    coroutine results from async SDK clients.

    Usage::

        manager = ApiKeyManager([AsyncCoinGeckoKey(k) for k in keys])

        # sync calls still work via dummyclient:
        result = manager.dummyclient.ping()

        # async calls use adummyclient:
        result = await manager.adummyclient.coins.simple.price.get(
            ids="bitcoin", vs_currencies="usd"
        )
    """

    def __init__(self, manager, attr_path, reach_limit_exc):
        self._manager = manager
        self._attr_path = list(attr_path)
        self._reach_limit_exc = reach_limit_exc

    def __getattr__(self, item):
        """Continue navigating down the attribute chain."""
        return AsyncChainProxy(
            manager=self._manager,
            attr_path=self._attr_path + [item],
            reach_limit_exc=self._reach_limit_exc,
        )

    async def __call__(self, *args, **kwargs):
        """End of chain — resolve and execute the actual async call."""
        apikey = self._manager.random_one()
        real_client = apikey._client

        target = real_client
        for i, attr in enumerate(self._attr_path):
            try:
                target = getattr(target, attr)
            except AttributeError:
                path_shown = ".".join(self._attr_path[: i + 1])
                raise AttributeError(
                    "AsyncChainProxy: attribute '{}' not found at step {} "
                    "of path '{}' on client {!r}".format(
                        attr, i + 1, ".".join(self._attr_path), type(real_client).__name__
                    )
                ) from None

        if not callable(target):
            path_shown = ".".join(self._attr_path)
            raise TypeError(
                "AsyncChainProxy: attribute path '{}' resolved to non-callable "
                "{} of type {}".format(path_shown, repr(target), type(target).__name__)
            )

        return await AsyncApiCaller(
            apikey=apikey,
            apikey_manager=self._manager,
            call_method=target,
            reach_limit_exc=self._reach_limit_exc,
        )(*args, **kwargs)

    def __repr__(self):
        return "AsyncChainProxy(path={})".format(".".join(self._attr_path))


class AsyncDummyClient(object):
    """Async entry point for chain calls — mirrors DummyClient but uses AsyncChainProxy."""

    def __init__(self):
        self._apikey_manager = None

    def __getattr__(self, item):
        manager = self._apikey_manager
        return AsyncChainProxy(
            manager=manager,
            attr_path=[item],
            reach_limit_exc=manager.reach_limit_exc,
        )


# ── Dynamic Key Manager (auto-refresh from server) ──────────────────


class DynamicKeyManager(ApiKeyManager):
    """ApiKeyManager that periodically refreshes its key pool from an
    ``apipool-server`` instance.

    Given a *key_fetcher* callable (typically :func:`apipool.get_keys`) and
    an *api_key_factory* callable (e.g. ``lambda raw_key: MyApiKey(raw_key)``),
    the manager will:

    1. Fetch the latest raw key list from the server at a configurable
       interval.
    2. Diff the new list against the current pool.
    3. **Add** keys that appeared on the server but are missing locally.
    4. **Remove** keys that disappeared from the server (hard delete).
    5. Restore previously archived keys if they reappear on the server.

    A background daemon thread handles the periodic refresh.  Call
    :meth:`shutdown` to stop it gracefully.

    Args:
        key_fetcher: Callable that returns ``list[str]`` of raw keys.
            Signature: ``key_fetcher() -> list[str]``.
        api_key_factory: Callable that converts a raw key string into an
            :class:`ApiKey` instance.  Signature: ``api_key_factory(raw_key: str) -> ApiKey``.
        refresh_interval: Seconds between refreshes.  Default 60.
        reach_limit_exc: Exception type that signals rate-limit exhaustion.
        db_engine: SQLAlchemy engine for stats.  Defaults to in-memory SQLite.
        on_keys_added: Optional callback ``callback(added_keys: list[str])``
            invoked after new keys are added.
        on_keys_removed: Optional callback ``callback(removed_keys: list[str])``
            invoked after keys are removed.

    Example::

        from apipool import DynamicKeyManager, get_keys, login

        tokens = login("http://localhost:8000", "alice", "password")

        manager = DynamicKeyManager(
            key_fetcher=lambda: get_keys(
                service_url="http://localhost:8000",
                client_type="coingecko",
                auth_token=tokens["access_token"],
            ),
            api_key_factory=lambda raw_key: CoinGeckoApiKey(raw_key),
            refresh_interval=120,
        )

        # Use exactly like a normal ApiKeyManager
        result = manager.dummyclient.ping()

        # When done
        manager.shutdown()
    """

    def __init__(
        self,
        key_fetcher: Callable[[], List[str]],
        api_key_factory: Callable[[str], ApiKey],
        refresh_interval: float = 60.0,
        reach_limit_exc=None,
        db_engine=None,
        on_keys_added: Optional[Callable[[List[str]], None]] = None,
        on_keys_removed: Optional[Callable[[List[str]], None]] = None,
    ):
        self._key_fetcher = key_fetcher
        self._api_key_factory = api_key_factory
        self._refresh_interval = refresh_interval
        self._on_keys_added = on_keys_added
        self._on_keys_removed = on_keys_removed
        self._lock = threading.RLock()
        self._shutdown_event = threading.Event()

        # Initial fetch
        try:
            initial_keys = self._key_fetcher()
        except Exception:
            logger.warning("DynamicKeyManager: initial key fetch failed, starting with empty pool")
            initial_keys = []

        initial_apikeys = [self._api_key_factory(k) for k in initial_keys]

        super().__init__(
            apikey_list=initial_apikeys,
            reach_limit_exc=reach_limit_exc,
            db_engine=db_engine,
        )

        # Start background refresh thread
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            name="apipool-dynamic-refresh",
            daemon=True,
        )
        self._refresh_thread.start()

    # ── Thread-safe overrides ────────────────────────────────────────

    def random_one(self):
        with self._lock:
            return super().random_one()

    def add_one(self, apikey, upsert=False):
        with self._lock:
            return super().add_one(apikey, upsert=upsert)

    def remove_one(self, primary_key):
        with self._lock:
            return super().remove_one(primary_key)

    # ── Refresh logic ────────────────────────────────────────────────

    def _refresh_loop(self):
        """Background loop that periodically refreshes the key pool."""
        while not self._shutdown_event.wait(timeout=self._refresh_interval):
            try:
                self._do_refresh()
            except Exception:
                logger.exception("DynamicKeyManager: refresh failed")

    def _do_refresh(self):
        """Fetch latest keys from server and reconcile with local pool."""
        try:
            raw_keys = self._key_fetcher()
        except Exception:
            logger.warning("DynamicKeyManager: key fetch failed during refresh", exc_info=True)
            return

        if raw_keys is None:
            raw_keys = []

        with self._lock:
            # Current key identifiers in the active pool
            current_keys = set(self.apikey_chain.keys())
            # Also check archived keys — they can be restored
            archived_keys = set(self.archived_apikey_chain.keys())

            new_key_set = set(raw_keys)

            # Keys to add: in server but not in active pool
            keys_to_add = new_key_set - current_keys
            # Keys to remove: in active pool but not on server
            keys_to_remove = current_keys - new_key_set

            # Restore archived keys that reappear on the server
            keys_to_restore = keys_to_add & archived_keys
            # Truly new keys (never seen before)
            keys_to_create = keys_to_add - archived_keys

            added_identifiers = []
            removed_identifiers = []

            # Restore archived keys
            for pk in keys_to_restore:
                apikey = self.archived_apikey_chain.pop(pk)
                self.apikey_chain[pk] = apikey
                added_identifiers.append(pk)

            # Create new keys from factory
            for raw_key in keys_to_create:
                try:
                    apikey = self._api_key_factory(raw_key)
                    self.add_one(apikey)
                    added_identifiers.append(raw_key)
                except Exception:
                    logger.warning(
                        "DynamicKeyManager: failed to create ApiKey for %r",
                        raw_key, exc_info=True,
                    )

            # Remove keys that disappeared from server
            for pk in keys_to_remove:
                try:
                    super().remove_one(pk)
                    removed_identifiers.append(pk)
                except KeyError:
                    pass

        if added_identifiers and self._on_keys_added:
            try:
                self._on_keys_added(added_identifiers)
            except Exception:
                logger.warning("DynamicKeyManager: on_keys_added callback failed", exc_info=True)

        if removed_identifiers and self._on_keys_removed:
            try:
                self._on_keys_removed(removed_identifiers)
            except Exception:
                logger.warning("DynamicKeyManager: on_keys_removed callback failed", exc_info=True)

        if added_identifiers or removed_identifiers:
            logger.info(
                "DynamicKeyManager: refresh completed — added %d, removed %d, pool size %d",
                len(added_identifiers), len(removed_identifiers), len(self.apikey_chain),
            )

    # ── Lifecycle ────────────────────────────────────────────────────

    def shutdown(self):
        """Stop the background refresh thread gracefully."""
        self._shutdown_event.set()
        self._refresh_thread.join(timeout=5.0)
        logger.info("DynamicKeyManager: shutdown complete")

    @property
    def pool_size(self) -> int:
        """Number of active keys in the pool."""
        with self._lock:
            return len(self.apikey_chain)


class AsyncDynamicKeyManager(ApiKeyManager):
    """Async version of :class:`DynamicKeyManager`.

    Instead of a background thread, this manager relies on the caller to
    periodically invoke :meth:`arefresh` (e.g. from an ``asyncio`` task).
    Alternatively, call :meth:`astart` to launch an auto-refresh task
    inside the current event loop.

    Args:
        key_fetcher: Async callable that returns ``list[str]``.
            Signature: ``await key_fetcher() -> list[str]``.
        api_key_factory: Same as :class:`DynamicKeyManager`.
        refresh_interval: Seconds between refreshes.  Default 60.
        reach_limit_exc: Exception type for rate-limit detection.
        db_engine: SQLAlchemy engine for stats.
        on_keys_added: Optional async callback ``await callback(added_keys)``.
        on_keys_removed: Optional async callback ``await callback(removed_keys)``.

    Example::

        manager = AsyncDynamicKeyManager(
            key_fetcher=lambda: aget_keys(
                service_url="http://localhost:8000",
                client_type="coingecko",
                auth_token=tokens["access_token"],
            ),
            api_key_factory=lambda raw_key: AsyncCoinGeckoKey(raw_key),
            refresh_interval=120,
        )
        await manager.astart()

        # Use like a normal manager
        result = await manager.adummyclient.ping()

        # When done
        await manager.ashutdown()
    """

    def __init__(
        self,
        key_fetcher: Callable,
        api_key_factory: Callable[[str], ApiKey],
        refresh_interval: float = 60.0,
        reach_limit_exc=None,
        db_engine=None,
        on_keys_added: Optional[Callable] = None,
        on_keys_removed: Optional[Callable] = None,
    ):
        self._key_fetcher = key_fetcher
        self._api_key_factory = api_key_factory
        self._refresh_interval = refresh_interval
        self._on_keys_added = on_keys_added
        self._on_keys_removed = on_keys_removed
        self._lock = threading.RLock()
        self._async_shutdown_event = None  # asyncio.Event, set in astart()
        self._refresh_task = None

        # Initial fetch (sync — caller should do async init separately)
        initial_apikeys = []

        super().__init__(
            apikey_list=initial_apikeys,
            reach_limit_exc=reach_limit_exc,
            db_engine=db_engine,
        )

    # ── Thread-safe overrides ────────────────────────────────────────

    def random_one(self):
        with self._lock:
            return super().random_one()

    def add_one(self, apikey, upsert=False):
        with self._lock:
            return super().add_one(apikey, upsert=upsert)

    def remove_one(self, primary_key):
        with self._lock:
            return super().remove_one(primary_key)

    # ── Async lifecycle ──────────────────────────────────────────────

    async def ainit(self):
        """Perform the initial async key fetch.  Call this after construction."""
        try:
            raw_keys = self._key_fetcher()
            if inspect.isawaitable(raw_keys):
                raw_keys = await raw_keys
        except Exception:
            logger.warning("AsyncDynamicKeyManager: initial key fetch failed")
            raw_keys = []

        with self._lock:
            for raw_key in raw_keys:
                try:
                    apikey = self._api_key_factory(raw_key)
                    self.add_one(apikey)
                except Exception:
                    logger.warning(
                        "AsyncDynamicKeyManager: failed to create ApiKey for %r",
                        raw_key, exc_info=True,
                    )

    async def astart(self):
        """Start the auto-refresh background task in the current event loop."""
        import asyncio
        self._async_shutdown_event = asyncio.Event()
        await self.ainit()
        self._refresh_task = asyncio.ensure_future(self._arefresh_loop())

    async def ashutdown(self):
        """Stop the auto-refresh background task."""
        if self._async_shutdown_event is not None:
            self._async_shutdown_event.set()
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except Exception:
                pass
        logger.info("AsyncDynamicKeyManager: shutdown complete")

    async def _arefresh_loop(self):
        """Background asyncio task that periodically refreshes the key pool."""
        import asyncio
        while not self._async_shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._async_shutdown_event.wait(),
                    timeout=self._refresh_interval,
                )
                # Event was set → shutdown requested
                return
            except asyncio.TimeoutError:
                pass  # Normal timeout → do refresh

            try:
                await self.arefresh()
            except Exception:
                logger.exception("AsyncDynamicKeyManager: refresh failed")

    # ── Async refresh logic ──────────────────────────────────────────

    async def arefresh(self):
        """Manually trigger a key pool refresh (async)."""
        try:
            raw_keys = self._key_fetcher()
            if inspect.isawaitable(raw_keys):
                raw_keys = await raw_keys
        except Exception:
            logger.warning("AsyncDynamicKeyManager: key fetch failed during refresh", exc_info=True)
            return

        if raw_keys is None:
            raw_keys = []

        added_identifiers = []
        removed_identifiers = []

        with self._lock:
            current_keys = set(self.apikey_chain.keys())
            archived_keys = set(self.archived_apikey_chain.keys())
            new_key_set = set(raw_keys)

            keys_to_add = new_key_set - current_keys
            keys_to_remove = current_keys - new_key_set
            keys_to_restore = keys_to_add & archived_keys
            keys_to_create = keys_to_add - archived_keys

            # Restore archived keys
            for pk in keys_to_restore:
                apikey = self.archived_apikey_chain.pop(pk)
                self.apikey_chain[pk] = apikey
                added_identifiers.append(pk)

            # Create new keys (async client connect)
            for raw_key in keys_to_create:
                try:
                    apikey = self._api_key_factory(raw_key)
                    # Use aconnect_client for async SDK initialization
                    await apikey.aconnect_client()
                    self.apikey_chain[apikey.primary_key] = apikey
                    self.stats.add_all_apikey([apikey])
                    added_identifiers.append(raw_key)
                except Exception:
                    logger.warning(
                        "AsyncDynamicKeyManager: failed to create ApiKey for %r",
                        raw_key, exc_info=True,
                    )

            # Remove keys that disappeared from server
            for pk in keys_to_remove:
                try:
                    super().remove_one(pk)
                    removed_identifiers.append(pk)
                except KeyError:
                    pass

        if added_identifiers and self._on_keys_added:
            try:
                result = self._on_keys_added(added_identifiers)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning("AsyncDynamicKeyManager: on_keys_added callback failed", exc_info=True)

        if removed_identifiers and self._on_keys_removed:
            try:
                result = self._on_keys_removed(removed_identifiers)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning("AsyncDynamicKeyManager: on_keys_removed callback failed", exc_info=True)

        if added_identifiers or removed_identifiers:
            logger.info(
                "AsyncDynamicKeyManager: refresh completed — added %d, removed %d, pool size %d",
                len(added_identifiers), len(removed_identifiers), len(self.apikey_chain),
            )

    @property
    def pool_size(self) -> int:
        """Number of active keys in the pool."""
        with self._lock:
            return len(self.apikey_chain)
