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
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
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


@dataclass
class BatchResult:
    """Result container for :meth:`ApiKeyManager.batch_exec` and
    :meth:`ApiKeyManager.abatch_exec`.

    Attributes:
        total: Total number of items submitted.
        succeeded: Number of items that completed successfully.
        failed: Number of items that failed after all retries.
        results: Dict mapping ``item_id`` → result value (successful items only).
        errors: Dict mapping ``item_id`` → last exception (failed items only).
        banned_keys: Dict mapping ``primary_key`` → ban expiry timestamp.
        elapsed: Wall-clock seconds for the entire batch.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: Dict[Any, Any] = field(default_factory=dict)
    errors: Dict[Any, Exception] = field(default_factory=dict)
    banned_keys: Dict[str, float] = field(default_factory=dict)
    elapsed: float = 0.0

    @property
    def success_rate(self) -> float:
        """Fraction of items that succeeded (0.0 ~ 1.0)."""
        return self.succeeded / self.total if self.total else 0.0


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
            reach_limit_exc = Exception
        self.reach_limit_exc = reach_limit_exc
        self.dummyclient = DummyClient()
        self.dummyclient._apikey_manager = self
        self.adummyclient = AsyncDummyClient()
        self.adummyclient._apikey_manager = self

        # Pool configuration (synced from server or set manually)
        self._config = None

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

    # ── Configuration ────────────────────────────────────────────────

    @property
    def config(self):
        """Current pool configuration (``PoolConfig`` or ``None``)."""
        return self._config

    def apply_config(self, config) -> None:
        """Apply a :class:`~apipool.client.PoolConfig` to this manager.

        Updates the following manager attributes based on the config:

        - ``reach_limit_exc`` — resolved from ``config.reach_limit_exception``
        - ``_config`` — stored for reference

        The ``concurrency``, ``timeout``, ``rate_limit`` etc. are consumed
        by :meth:`call_concurrent` and :meth:`acall_concurrent`.
        """
        self._config = config

        # Resolve reach_limit_exception from config if still at default (Exception)
        if config.reach_limit_exception and self.reach_limit_exc is Exception:
            resolved = self._resolve_exception_class(config.reach_limit_exception)
            if resolved is not None:
                self.reach_limit_exc = resolved

    @staticmethod
    def _resolve_exception_class(dotted_path: str):
        """Dynamically import an exception class from a dotted path string."""
        try:
            module_path, class_name = dotted_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError, ValueError):
            return None

    # ── Concurrent execution ─────────────────────────────────────────

    def call_concurrent(
        self,
        method_name: str,
        args_list: List[tuple],
        kwargs_list: Optional[List[dict]] = None,
        max_concurrency: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> List[Any]:
        """Execute the same method concurrently across multiple argument sets.

        Each call goes through the normal ``dummyclient`` chain (key selection,
        rotation, stats).  Concurrency is bounded by ``max_concurrency``
        (defaults to ``config.concurrency`` or unlimited if 0).

        Args:
            method_name: Attribute path on ``dummyclient`` (e.g. ``"some_method"``).
            args_list: List of positional argument tuples for each call.
            kwargs_list: Optional list of keyword argument dicts.
            max_concurrency: Override for max concurrent calls.
            timeout: Per-call timeout override in seconds.

        Returns:
            List of results in the same order as ``args_list``.
            Failed calls raise immediately unless handled by reach_limit_exc.
        """
        if kwargs_list is None:
            kwargs_list = [{}] * len(args_list)

        if len(args_list) != len(kwargs_list):
            raise ValueError("args_list and kwargs_list must have the same length")

        # Determine concurrency limit
        if max_concurrency is None:
            max_concurrency = self._config.concurrency if self._config else 0
        if timeout is None:
            timeout = self._config.timeout if self._config else 30.0

        # Resolve the method via ChainProxy
        chain = self.dummyclient
        for attr in method_name.split("."):
            chain = getattr(chain, attr)

        results = [None] * len(args_list)
        errors = [None] * len(args_list)

        def _worker(index):
            try:
                results[index] = chain(*args_list[index], **kwargs_list[index])
            except Exception as e:
                errors[index] = e

        if max_concurrency <= 0:
            # Unlimited: use ThreadPoolExecutor with all tasks
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=len(args_list)) as pool:
                futures = {pool.submit(_worker, i): i for i in range(len(args_list))}
                for future in as_completed(futures):
                    future.result()  # Propagate exceptions
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                futures = [pool.submit(_worker, i) for i in range(len(args_list))]
                for f in futures:
                    f.result()

        # Raise first error if any
        for i, err in enumerate(errors):
            if err is not None:
                raise err

        return results

    async def acall_concurrent(
        self,
        method_name: str,
        args_list: List[tuple],
        kwargs_list: Optional[List[dict]] = None,
        max_concurrency: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> List[Any]:
        """Async version of :meth:`call_concurrent`.

        Uses ``asyncio.Semaphore`` for concurrency control and ``asyncio.wait_for``
        for per-call timeout.
        """
        if kwargs_list is None:
            kwargs_list = [{}] * len(args_list)

        if len(args_list) != len(kwargs_list):
            raise ValueError("args_list and kwargs_list must have the same length")

        if max_concurrency is None:
            max_concurrency = self._config.concurrency if self._config else 0
        if timeout is None:
            timeout = self._config.timeout if self._config else 30.0

        # Resolve the method via AsyncChainProxy
        chain = self.adummyclient
        for attr in method_name.split("."):
            chain = getattr(chain, attr)

        semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None

        async def _worker(index):
            if semaphore:
                async with semaphore:
                    return await asyncio.wait_for(
                        chain(*args_list[index], **kwargs_list[index]),
                        timeout=timeout,
                    )
            else:
                return await asyncio.wait_for(
                    chain(*args_list[index], **kwargs_list[index]),
                    timeout=timeout,
                )

        tasks = [_worker(i) for i in range(len(args_list))]
        return await asyncio.gather(*tasks, return_exceptions=False)

    # ── Batch execution ─────────────────────────────────────────────

    @staticmethod
    def _safe_stats(stats, primary_key, status_id):
        """Record a stats event without letting DB errors propagate."""
        try:
            stats.add_event(primary_key, status_id)
        except Exception:
            logger.debug("batch_exec: stats recording failed (ignored)", exc_info=True)

    def _resolve_method(self, apikey, method_name: str):
        """Resolve an attribute path on an ApiKey's client object."""
        target = apikey._client
        for attr in method_name.split("."):
            target = getattr(target, attr)
        if not callable(target):
            raise TypeError(
                f"batch_exec: '{method_name}' resolved to non-callable "
                f"{type(target).__name__}"
            )
        return target

    def _get_available_keys(self) -> List[ApiKey]:
        """Return a snapshot of active keys (thread-safe)."""
        with self._lock if hasattr(self, "_lock") else _dummy_context():
            return list(self.apikey_chain.values())

    def batch_exec(
        self,
        method_name: str,
        items: List[Tuple[Any, tuple, dict]],
        max_concurrency: Optional[int] = None,
        timeout: Optional[float] = None,
        retry_on_failure: Optional[bool] = None,
        max_retries: Optional[int] = None,
        ban_threshold: Optional[int] = None,
        ban_duration: Optional[float] = None,
    ) -> BatchResult:
        """Execute a batch of unique API calls with retry, key rotation,
        and temporary key banning.

        This method is designed for high-volume workloads such as fetching
        10 000 token prices from CoinGecko.  Each item is uniquely
        identified and executed **at most once**.  When an API call fails,
        the item is retried on a *different* key (rotation).  Keys that
        accumulate ``ban_threshold`` consecutive failures are temporarily
        banned from the batch group for ``ban_duration`` seconds.

        All tuning parameters fall back to ``manager.config`` values when
        not explicitly provided, and those in turn fall back to sensible
        defaults — so the server can centrally control batch behaviour.

        Stats recording is best-effort: database errors (e.g. SQLite
        thread-safety issues) are silently ignored and never cause an
        item to fail.

        Args:
            method_name: Attribute path on each key's client
                (e.g. ``"coins.simple.price.get"``).
            items: List of ``(item_id, args_tuple, kwargs_dict)`` triples.
                ``item_id`` must be unique across the batch — it is used
                as the deduplication key and for result mapping.
            max_concurrency: Max parallel calls (0 = unlimited).
            timeout: Per-call timeout in seconds.
            retry_on_failure: Retry failed items on another key.
            max_retries: Max retry attempts per item.
            ban_threshold: Consecutive failures before a key is banned.
            ban_duration: Seconds a banned key is excluded.

        Returns:
            :class:`BatchResult` with per-item results/errors and stats.

        Example::

            items = [
                ("bitcoin",  (), {"ids": "bitcoin", "vs_currencies": "usd"}),
                ("ethereum", (), {"ids": "ethereum", "vs_currencies": "usd"}),
                # ... 10 000 more
            ]
            result = manager.batch_exec("coins.simple.price.get", items)
            print(f"Success: {result.succeeded}/{result.total}")
        """
        start = time.monotonic()

        # ── Resolve parameters from config ───────────────────────
        if max_concurrency is None:
            max_concurrency = self._config.concurrency if self._config else 0
        if timeout is None:
            timeout = self._config.timeout if self._config else 30.0
        if retry_on_failure is None:
            retry_on_failure = (
                self._config.effective_batch_retry
                if self._config
                else False
            )
        if max_retries is None:
            max_retries = (
                self._config.effective_batch_max_retries
                if self._config
                else 0
            )
        if ban_threshold is None:
            ban_threshold = self._config.ban_threshold if self._config else 3
        if ban_duration is None:
            ban_duration = self._config.ban_duration if self._config else 300.0

        # ── Shared mutable state (protected by lock) ─────────────
        lock = threading.Lock()
        # primary_key → consecutive failure count
        key_fail_counts: Dict[str, int] = {}
        # primary_key → ban expiry timestamp
        banned_keys: Dict[str, float] = {}
        # Results
        results: Dict[Any, Any] = {}
        errors: Dict[Any, Exception] = {}

        # Use a round-robin index to spread load across keys
        _rr_index = [0]

        def _is_key_available(primary_key: str) -> bool:
            """Check whether a key is usable (not banned)."""
            if primary_key in banned_keys:
                if time.monotonic() < banned_keys[primary_key]:
                    return False
                else:
                    # Ban expired — readmit
                    del banned_keys[primary_key]
                    key_fail_counts.pop(primary_key, None)
            return True

        def _pick_key() -> Optional[ApiKey]:
            """Pick an available key, skipping banned ones."""
            available = self._get_available_keys()
            if not available:
                return None
            # Round-robin with fallback to find an unbanned key
            with lock:
                start_idx = _rr_index[0] % len(available)
            for offset in range(len(available)):
                idx = (start_idx + offset) % len(available)
                ak = available[idx]
                if _is_key_available(ak.primary_key):
                    with lock:
                        _rr_index[0] = idx + 1
                    return ak
            return None

        def _record_key_success(primary_key: str) -> None:
            with lock:
                key_fail_counts.pop(primary_key, None)

        def _record_key_failure(primary_key: str) -> None:
            with lock:
                key_fail_counts[primary_key] = key_fail_counts.get(primary_key, 0) + 1
                if key_fail_counts[primary_key] >= ban_threshold:
                    banned_keys[primary_key] = time.monotonic() + ban_duration
                    logger.info(
                        "batch_exec: key %s banned for %.0fs after %d failures",
                        primary_key, ban_duration, ban_threshold,
                    )

        def _try_item(item_id: Any, args: tuple, kwargs: dict) -> Optional[Any]:
            """Execute one item. Returns result on success, None on failure
            (error stored in ``errors``)."""
            last_exc: Optional[Exception] = None
            attempts = 1 + (max_retries if retry_on_failure else 0)
            used_keys: set = set()

            for attempt in range(attempts):
                apikey = _pick_key()
                if apikey is None:
                    last_exc = PoolExhaustedError(
                        "No available keys (all banned or exhausted)"
                    )
                    break

                # Skip keys already tried for this item (ensure rotation)
                if apikey.primary_key in used_keys:
                    # Try to find a different key
                    all_keys = self._get_available_keys()
                    found_alt = False
                    for ak in all_keys:
                        if ak.primary_key not in used_keys and _is_key_available(ak.primary_key):
                            apikey = ak
                            found_alt = True
                            break
                    if not found_alt:
                        # All available keys already tried — retry anyway
                        pass

                used_keys.add(apikey.primary_key)

                try:
                    target = self._resolve_method(apikey, method_name)
                    result = target(*args, **kwargs)
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c1_Success.id
                    )
                    _record_key_success(apikey.primary_key)
                    return result
                except self.reach_limit_exc as e:
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c9_ReachLimit.id
                    )
                    # Key hit rate limit — remove from pool + ban
                    with self._lock if hasattr(self, "_lock") else _dummy_context():
                        if apikey.primary_key in self.apikey_chain:
                            self.remove_one(apikey.primary_key)
                    banned_keys[apikey.primary_key] = time.monotonic() + ban_duration
                    last_exc = e
                    if not retry_on_failure:
                        break
                except Exception as e:
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c5_Failed.id
                    )
                    _record_key_failure(apikey.primary_key)
                    last_exc = e
                    if not retry_on_failure:
                        break

            # All attempts exhausted
            with lock:
                errors[item_id] = last_exc
            return None

        # ── Execute with ThreadPoolExecutor ───────────────────────
        from concurrent.futures import ThreadPoolExecutor

        effective_workers = max_concurrency if max_concurrency > 0 else min(len(items), 64)

        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            future_map = {}
            for item_id, args, kwargs in items:
                fut = pool.submit(_try_item, item_id, args, kwargs)
                future_map[fut] = item_id

            for fut in list(future_map.keys()):
                item_id = future_map[fut]
                try:
                    result = fut.result(timeout=timeout * (max_retries + 1))
                    if result is not None:
                        with lock:
                            results[item_id] = result
                except Exception as e:
                    with lock:
                        errors[item_id] = e

        elapsed = time.monotonic() - start
        return BatchResult(
            total=len(items),
            succeeded=len(results),
            failed=len(errors),
            results=results,
            errors=errors,
            banned_keys=dict(banned_keys),
            elapsed=elapsed,
        )

    async def abatch_exec(
        self,
        method_name: str,
        items: List[Tuple[Any, tuple, dict]],
        max_concurrency: Optional[int] = None,
        timeout: Optional[float] = None,
        retry_on_failure: Optional[bool] = None,
        max_retries: Optional[int] = None,
        ban_threshold: Optional[int] = None,
        ban_duration: Optional[float] = None,
    ) -> BatchResult:
        """Async version of :meth:`batch_exec`.

        Uses ``asyncio.Semaphore`` for concurrency control and
        ``asyncio.wait_for`` for per-call timeout.  All parameters have
        the same meaning as the synchronous version.

        Example::

            items = [
                ("bitcoin",  (), {"ids": "bitcoin"}),
                ("ethereum", (), {"ids": "ethereum"}),
            ]
            result = await manager.abatch_exec("coins.simple.price.get", items)
        """
        start = time.monotonic()

        # ── Resolve parameters from config ───────────────────────
        if max_concurrency is None:
            max_concurrency = self._config.concurrency if self._config else 0
        if timeout is None:
            timeout = self._config.timeout if self._config else 30.0
        if retry_on_failure is None:
            retry_on_failure = (
                self._config.effective_batch_retry
                if self._config
                else False
            )
        if max_retries is None:
            max_retries = (
                self._config.effective_batch_max_retries
                if self._config
                else 0
            )
        if ban_threshold is None:
            ban_threshold = self._config.ban_threshold if self._config else 3
        if ban_duration is None:
            ban_duration = self._config.ban_duration if self._config else 300.0

        # ── Shared mutable state ─────────────────────────────────
        lock = asyncio.Lock()
        # primary_key → consecutive failure count
        key_fail_counts: Dict[str, int] = {}
        # primary_key → ban expiry timestamp
        banned_keys: Dict[str, float] = {}
        # Results
        results: Dict[Any, Any] = {}
        errors: Dict[Any, Exception] = {}
        # Round-robin index
        _rr_index = [0]

        def _is_key_available(primary_key: str) -> bool:
            if primary_key in banned_keys:
                if time.monotonic() < banned_keys[primary_key]:
                    return False
                else:
                    del banned_keys[primary_key]
                    key_fail_counts.pop(primary_key, None)
            return True

        async def _pick_key() -> Optional[ApiKey]:
            available = self._get_available_keys()
            if not available:
                return None
            start_idx = _rr_index[0] % len(available)
            for offset in range(len(available)):
                idx = (start_idx + offset) % len(available)
                ak = available[idx]
                if _is_key_available(ak.primary_key):
                    _rr_index[0] = idx + 1
                    return ak
            return None

        async def _record_key_success(primary_key: str) -> None:
            async with lock:
                key_fail_counts.pop(primary_key, None)

        async def _record_key_failure(primary_key: str) -> None:
            async with lock:
                key_fail_counts[primary_key] = key_fail_counts.get(primary_key, 0) + 1
                if key_fail_counts[primary_key] >= ban_threshold:
                    banned_keys[primary_key] = time.monotonic() + ban_duration
                    logger.info(
                        "abatch_exec: key %s banned for %.0fs after %d failures",
                        primary_key, ban_duration, ban_threshold,
                    )

        async def _try_item(item_id: Any, args: tuple, kwargs: dict) -> Optional[Any]:
            last_exc: Optional[Exception] = None
            attempts = 1 + (max_retries if retry_on_failure else 0)
            used_keys: set = set()

            for attempt in range(attempts):
                apikey = await _pick_key()
                if apikey is None:
                    last_exc = PoolExhaustedError(
                        "No available keys (all banned or exhausted)"
                    )
                    break

                # Skip keys already tried for this item
                if apikey.primary_key in used_keys:
                    all_keys = self._get_available_keys()
                    found_alt = False
                    for ak in all_keys:
                        if ak.primary_key not in used_keys and _is_key_available(ak.primary_key):
                            apikey = ak
                            found_alt = True
                            break
                    if not found_alt:
                        pass  # All keys tried, retry with same key

                used_keys.add(apikey.primary_key)

                try:
                    target = self._resolve_method(apikey, method_name)
                    result = target(*args, **kwargs)
                    if inspect.isawaitable(result):
                        result = await asyncio.wait_for(result, timeout=timeout)
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c1_Success.id
                    )
                    await _record_key_success(apikey.primary_key)
                    return result
                except self.reach_limit_exc as e:
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c9_ReachLimit.id
                    )
                    with self._lock if hasattr(self, "_lock") else _dummy_context():
                        if apikey.primary_key in self.apikey_chain:
                            self.remove_one(apikey.primary_key)
                    banned_keys[apikey.primary_key] = time.monotonic() + ban_duration
                    last_exc = e
                    if not retry_on_failure:
                        break
                except asyncio.TimeoutError as e:
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c5_Failed.id
                    )
                    await _record_key_failure(apikey.primary_key)
                    last_exc = e
                    if not retry_on_failure:
                        break
                except Exception as e:
                    self._safe_stats(
                        self.stats, apikey.primary_key, StatusCollection.c5_Failed.id
                    )
                    await _record_key_failure(apikey.primary_key)
                    last_exc = e
                    if not retry_on_failure:
                        break

            async with lock:
                errors[item_id] = last_exc
            return None

        # ── Execute with asyncio semaphore ────────────────────────
        semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None

        async def _run_item(item_id: Any, args: tuple, kwargs: dict):
            if semaphore:
                async with semaphore:
                    result = await _try_item(item_id, args, kwargs)
            else:
                result = await _try_item(item_id, args, kwargs)
            if result is not None:
                async with lock:
                    results[item_id] = result

        tasks = [_run_item(item_id, args, kwargs) for item_id, args, kwargs in items]
        await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.monotonic() - start
        return BatchResult(
            total=len(items),
            succeeded=len(results),
            failed=len(errors),
            results=results,
            errors=errors,
            banned_keys=dict(banned_keys),
            elapsed=elapsed,
        )


def create_sqlite():
    return create_engine("sqlite:///:memory:")


class _DummyContext:
    """A no-op context manager for code that conditionally needs a lock."""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def _dummy_context():
    return _DummyContext()


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
        config_fetcher: Optional[Callable] = None,
    ):
        self._key_fetcher = key_fetcher
        self._api_key_factory = api_key_factory
        self._refresh_interval = refresh_interval
        self._on_keys_added = on_keys_added
        self._on_keys_removed = on_keys_removed
        self._config_fetcher = config_fetcher
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

        # Initial config sync
        if self._config_fetcher:
            try:
                config = self._config_fetcher()
                self.apply_config(config)
            except Exception:
                logger.warning("DynamicKeyManager: initial config sync failed", exc_info=True)

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

        # Sync config from server
        if self._config_fetcher:
            try:
                config = self._config_fetcher()
                self.apply_config(config)
            except Exception:
                logger.warning("DynamicKeyManager: config sync failed during refresh", exc_info=True)

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
        config_fetcher: Optional[Callable] = None,
    ):
        self._key_fetcher = key_fetcher
        self._api_key_factory = api_key_factory
        self._refresh_interval = refresh_interval
        self._on_keys_added = on_keys_added
        self._on_keys_removed = on_keys_removed
        self._config_fetcher = config_fetcher
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

        # Initial config sync
        if self._config_fetcher:
            try:
                config = self._config_fetcher()
                if inspect.isawaitable(config):
                    config = await config
                self.apply_config(config)
            except Exception:
                logger.warning("AsyncDynamicKeyManager: initial config sync failed", exc_info=True)

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

        # Sync config from server
        if self._config_fetcher:
            try:
                config = self._config_fetcher()
                if inspect.isawaitable(config):
                    config = await config
                self.apply_config(config)
            except Exception:
                logger.warning("AsyncDynamicKeyManager: config sync failed during refresh", exc_info=True)

    @property
    def pool_size(self) -> int:
        """Number of active keys in the pool."""
        with self._lock:
            return len(self.apikey_chain)
