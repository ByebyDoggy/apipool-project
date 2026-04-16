#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Regression test for refresh diff-set primary_key mismatch bug.

Bug: DynamicKeyManager._do_refresh() and AsyncDynamicKeyManager.arefresh()
used ``set(raw_keys)`` for diff comparison against ``set(apikey_chain.keys())``,
where raw_keys are original key strings but apikey_chain.keys() are
primary_key values returned by ApiKey.get_primary_key().

When get_primary_key() returns a value different from the raw key string
(e.g. CoinGeckoApiKeyAdapter returns "CG_" + key[-8:]), every refresh would
incorrectly mark ALL existing keys as "to_remove", causing pool_size=0.

Fix: Pre-create ALL ApiKey objects first to obtain their real primary_key,
then compare sets of primary_key values only.

Run:
    cd D:\\Programming\\Python\\apipool-project
    python -m pytest apipool/tests/test_refresh_primary_key_fix.py -v
    # OR
    python apipool/tests/test_refresh_primary_key_fix.py
"""

import sys
import os
import asyncio

# Ensure project root is on path so we import LOCAL source
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from apipool import ApiKey, ApiKeyManager, AsyncDynamicKeyManager, PoolExhaustedError


# ──────────────────────────────────────────────
# Mock classes — simulate primary_key != raw_key
# ──────────────────────────────────────────────


class _SimpleClient:
    def __init__(self, **kwargs):
        pass

    def ping(self):
        return {"status": "ok"}


class CustomPrimaryKeyApiKey(ApiKey):
    """ApiKey where get_primary_key() differs from raw key string.

    This mimics CoinGeckoApiKeyAdapter behavior where:
        raw_key = "cg_live_abc123def456"
        primary_key = "CG_f456"
    """

    def __init__(self, raw_key: str):
        self.raw_key = raw_key

    def get_primary_key(self) -> str:
        # Return a transformed version — NOT equal to raw_key
        tail = self.raw_key[-6:] if len(self.raw_key) > 6 else self.raw_key
        return f"CUSTOM_{tail}"

    def create_client(self):
        return _SimpleClient(tail=self.raw_key[-6:])

    def test_usability(self, client) -> bool:
        return True


# ── Sync DynamicKeyManager tests ────────────────────


class TestSyncRefreshPrimaryKeyMismatch:
    """Regression tests for DynamicKeyManager._do_refresh()."""

    def test_refresh_with_custom_primary_key_does_not_remove_all(self):
        """BUG FIX: When primary_key != raw_key, refresh must NOT remove all keys."""
        from apipool.manager import DynamicKeyManager

        raw_keys = ["key_alpha_111", "key_beta_222", "key_gamma_333"]

        manager = DynamicKeyManager(
            key_fetcher=lambda: raw_keys,
            api_key_factory=CustomPrimaryKeyApiKey,
            refresh_interval=9999,  # prevent auto-refresh during test
        )

        # Initial state: 3 keys loaded via initial fetch
        assert len(manager.apikey_chain) == 3
        # primary_key = "CUSTOM_" + last 6 chars of raw_key
        assert set(manager.apikey_chain.keys()) == {
            "CUSTOM_ha_111", "CUSTOM_ta_222", "CUSTOM_ma_333",
        }

        # Trigger a refresh with THE SAME keys — should be a no-op
        manager._do_refresh()

        # CRITICAL: pool should still have 3 keys (old bug: 0)
        assert len(manager.apikey_chain) == 3, (
            f"Expected 3 keys after no-op refresh, got {len(manager.apikey_chain)}. "
            f"Keys: {list(manager.apikey_chain.keys())}"
        )
        assert len(manager.archived_apikey_chain) == 0

    def test_refresh_removes_deleted_key(self):
        """When server actually removes a key, it should be removed."""
        from apipool.manager import DynamicKeyManager

        initial_keys = ["key_alpha_111", "key_beta_222", "key_gamma_333"]
        updated_keys = ["key_alpha_111", "key_beta_222"]  # gamma removed

        call_count = [0]

        def fetcher():
            call_count[0] += 1
            if call_count[0] <= 1:
                return initial_keys
            return updated_keys

        manager = DynamicKeyManager(
            key_fetcher=fetcher,
            api_key_factory=CustomPrimaryKeyApiKey,
        )

        assert len(manager.apikey_chain) == 3

        # Refresh: gamma should be removed
        manager._do_refresh()

        assert len(manager.apikey_chain) == 2, (
            f"Expected 2 keys after removal, got {len(manager.apikey_chain)}"
        )
        assert "CUSTOM_ma_333" not in manager.apikey_chain
        assert "CUSTOM_ma_333" in manager.archived_apikey_chain

    def test_refresh_adds_new_key(self):
        """When server adds a new key, it should appear in pool."""
        from apipool.manager import DynamicKeyManager

        initial_keys = ["key_alpha_111"]
        updated_keys = ["key_alpha_111", "key_delta_444"]

        call_count = [0]

        def fetcher():
            call_count[0] += 1
            if call_count[0] <= 1:
                return initial_keys
            return updated_keys

        manager = DynamicKeyManager(
            key_fetcher=fetcher,
            api_key_factory=CustomPrimaryKeyApiKey,
        )

        assert len(manager.apikey_chain) == 1

        manager._do_refresh()

        assert len(manager.apikey_chain) == 2, (
            f"Expected 2 keys after addition, got {len(manager.apikey_chain)}"
        )
        assert "CUSTOM_ta_444" in manager.apikey_chain


# ── Async DynamicKeyManager tests ──────────────────


# ── Async DynamicKeyManager tests ──────────────────


def test_async_arefresh_no_removal():
    """BUG FIX (async): refresh with same keys must NOT empty the pool."""
    raw_keys = ["akey_one_111", "akey_two_222", "akey_three_333"]

    async def key_fetcher():
        return raw_keys

    manager = AsyncDynamicKeyManager(
        key_fetcher=key_fetcher,
        api_key_factory=CustomPrimaryKeyApiKey,
        refresh_interval=9999,
    )

    async def _run():
        await manager.ainit()
        try:
            assert len(manager.apikey_chain) == 3

            # Refresh with SAME keys — should be a complete no-op
            await manager.arefresh()

            # CRITICAL: pool still has 3 keys (old bug: removed all)
            assert len(manager.apikey_chain) == 3, (
                f"Expected 3 keys after no-op arefresh, "
                f"got {len(manager.apikey_chain)}. "
                f"Active: {list(manager.apikey_chain.keys())}, "
                f"Archived: {list(manager.archived_apikey_chain.keys())}"
            )
            assert len(manager.archived_apikey_chain) == 0
        finally:
            await manager.ashutdown()

    asyncio.run(_run())


def test_async_refresh_removes_and_adds():
    """Async refresh correctly handles add/remove when primary_key != raw_key."""
    initial_keys = ["k_x_001", "k_y_002"]
    updated_keys = ["k_y_002", "k_z_003"]  # x removed, z added

    call_count = [0]

    async def key_fetcher():
        call_count[0] += 1
        if call_count[0] <= 1:
            return initial_keys
        return updated_keys

    manager = AsyncDynamicKeyManager(
        key_fetcher=key_fetcher,
        api_key_factory=CustomPrimaryKeyApiKey,
    )

    async def _run():
        await manager.ainit()
        try:
            assert len(manager.apikey_chain) == 2

            await manager.arefresh()

            # x removed, z added, y remains
            assert len(manager.apikey_chain) == 2, (
                f"Expected 2 keys after diff refresh, got {len(manager.apikey_chain)}"
            )
            assert "_001" not in "".join(manager.apikey_chain.keys()), "x should be gone"
            assert "_003" in "".join(manager.apikey_chain.keys()), "z should exist"
            assert "_002" in "".join(manager.apikey_chain.keys()), "y should remain"
        finally:
            await manager.ashutdown()

    asyncio.run(_run())


def test_async_consecutive_refreshes_stable():
    """Multiple consecutive refreshes with same keys keep pool stable."""
    raw_keys = ["stable_key_AAA", "stable_key_BBB"]

    manager = AsyncDynamicKeyManager(
        key_fetcher=lambda: [k for k in raw_keys],
        api_key_factory=CustomPrimaryKeyApiKey,
    )

    async def _run():
        await manager.ainit()
        try:
            for i in range(5):
                await manager.arefresh()

            assert len(manager.apikey_chain) == 2, (
                f"After 5 refreshes, expected 2 keys, got {len(manager.apikey_chain)}"
            )
            assert len(manager.archived_apikey_chain) == 0
        finally:
            await manager.ashutdown()

    asyncio.run(_run())


# ── Main runner (for direct execution without pytest) ──


def main():
    print("=" * 64)
    print("  Refresh Primary-Key Mismatch Fix — Regression Tests")
    print("=" * 64)

    passed = 0
    failed = 0

    sync_tests = TestSyncRefreshPrimaryKeyMismatch()
    for name, method in [
        ("Sync: no-op refresh keeps pool", sync_tests.test_refresh_with_custom_primary_key_does_not_remove_all),
        ("Sync: removes deleted key", sync_tests.test_refresh_removes_deleted_key),
        ("Sync: adds new key", sync_tests.test_refresh_adds_new_key),
    ]:
        try:
            method()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    # Async tests (run via asyncio.run)
    for name, func in [
        ("Async: no-op refresh keeps pool", test_async_arefresh_no_removal),
        ("Async: removes and adds", test_async_refresh_removes_and_adds),
        ("Async: consecutive refreshes stable", test_async_consecutive_refreshes_stable),
    ]:
        try:
            func()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    total = passed + failed
    print("\n" + "=" * 64)
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 64)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
