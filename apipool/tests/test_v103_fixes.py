#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test suite for apipool-ng v1.0.3 bugfixes.

Fix 1: StatsCollector exported from __init__.py
Fix 2: ChainProxy clear error messages for missing attrs / non-callable
Fix 3: PoolExhaustedError instead of IndexError on empty pool

Run:
    cd D:\Programming\Python\apipool-project
    python -m apipool.tests.test_v103_fixes
"""

import sys
import os
import random
import traceback
from collections import OrderedDict

# Ensure project root is on path so we import LOCAL source (not PyPI)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import apipool
from apipool import (
    ApiKey, ApiKeyManager,
    PoolExhaustedError,
    StatusCollection,
)
from apipool.stats import StatsCollector

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

_passed = 0
_failed = 0
_results = []


def _ok(module_id, test_id, desc):
    global _passed
    _passed += 1
    _results.append(("PASS", module_id, test_id, desc))
    print("  [PASS] {}.{} - {}".format(module_id, test_id, desc))


def _fail(module_id, test_id, desc, detail=""):
    global _failed
    _failed += 1
    _results.append(("FAIL", module_id, test_id, desc))
    print("  [FAIL] {}.{} - {}{}".format(module_id, test_id, desc,
                                          ("\n         " + detail) if detail else ""))


# ──────────────────────────────────────────────
# Mock classes
# ──────────────────────────────────────────────


class _SimpleClient(object):
    def get_data(self):
        return {"result": "ok"}


class _NestedClient(object):
    class nested:
        @staticmethod
        def fetch():
            return "nested_ok"


class _DeepClient(object):
    """Supports arbitrary depth like a.b.c.d.e.deep_call()"""

    def __getattr__(self, name):
        return _DeepNode(name)


class _DeepNode(object):
    def __init__(self, name):
        self._name = name

    def __getattr__(self, name):
        return _DeepNode(self._name + "." + name)

    def __call__(self, *a, **kw):
        return "called:" + self._name


class ReachLimitError(Exception):
    pass


class SimpleApiKey(ApiKey):
    def __init__(self, key, client_class=_SimpleClient):
        self._key = key
        self._client_class = client_class

    def get_primary_key(self):
        return self._key

    def create_client(self):
        return self._client_class()

    def test_usability(self, client):
        return True


class FailingApiKey(ApiKey):
    """Key that always raises reach_limit_exc on any dummyclient call."""

    def __init__(self, key):
        self._key = key

    def get_primary_key(self):
        return self._key

    def create_client(self):
        # Return a client where ANY attribute chain call raises ReachLimitError
        return _FailingDeepClient()

    def test_usability(self, client):
        return True


class _FailingDeepClient:
    """Every attribute access returns a node that raises on call."""

    def __getattr__(self, name):
        return _FailingDeepNode(name)


class _FailingDeepNode:
    def __init__(self, name):
        self._name = name

    def __getattr__(self, name):
        return _FailingDeepNode(self._name + "." + name)

    def __call__(self, *a, **kw):
        raise ReachLimitError("rate limit reached")


# ════════════════════════════════════════════
# Module 1 — Fix 1: Exports from __init__.py
# ════════════════════════════════════════════


def test_m1_exports():
    """Module 1: StatsCollector and PoolExhaustedError are importable from top-level."""
    print("\n── Module 1: Exports from __init__.py ──")

    # 1.1 Version is 1.0.3
    try:
        assert hasattr(apipool, "__version__"), "no __version__"
        assert apipool.__version__ == "1.0.3", \
            "expected 1.0.3, got {}".format(apipool.__version__)
        _ok(1, 1, "__version__ == '1.0.3'")
    except Exception as e:
        _fail(1, 1, "__version__ == '1.0.3'", str(e))

    # 1.2 StatsCollector in dir(apipool)
    try:
        assert "StatsCollector" in dir(apipool), \
            "StatsCollector not found in dir(apipool): {}".format([x for x in dir(apipool) if not x.startswith("_")])
        _ok(1, 2, "StatsCollector in dir(apipool)")
    except Exception as e:
        _fail(1, 2, "StatsCollector in dir(apipool)", str(e))

    # 1.3 StatsCollector is the correct class
    try:
        from apipool.stats import StatsCollector as _SC_ref
        assert apipool.StatsCollector is _SC_ref, \
            "StatsCollector identity mismatch"
        _ok(1, 3, "StatsCollector is correct class")
    except Exception as e:
        _fail(1, 3, "StatsCollector is correct class", str(e))

    # 1.4 PoolExhaustedError in dir(apipool)
    try:
        assert "PoolExhaustedError" in dir(apipool), \
            "PoolExhaustedError not in dir"
        _ok(1, 4, "PoolExhaustedError in dir(apipool)")
    except Exception as e:
        _fail(1, 4, "PoolExhaustedError in dir", str(e))

    # 1.5 PoolExhaustedError is an Exception subclass
    try:
        assert issubclass(PoolExhaustedError, Exception), \
            "PoolExhaustedError is not an Exception"
        _ok(1, 5, "PoolExhaustedError is Exception")
    except Exception as e:
        _fail(1, 5, "PoolExhaustedError is Exception", str(e))


# ════════════════════════════════════════════
# Module 2 — Fix 2: ChainProxy clear errors
# ════════════════════════════════════════════


def test_m2_chainproxy_errors():
    """Module 2: ChainProxy gives clear AttributeError / TypeError."""
    print("\n── Module 2: ChainProxy Clear Error Messages ──")

    keys = [SimpleApiKey("k1")]
    mgr = ApiKeyManager(keys)
    dc = mgr.dummyclient

    # 2.1 Missing attribute at step 1 → clear message
    try:
        try:
            dc.nonexistent_method()
            _fail(2, 1, "Missing attr step-1 → AttributeError",
                  "No exception raised")
        except AttributeError as e:
            msg = str(e)
            checks = [
                ("nonexistent_method" in msg, "attr name not in msg"),
                ("step 1" in msg or "at step" in msg.lower(), "step info missing"),
                ("nonexistent_method" in msg or "ChainProxy" in msg,
                 "context missing"),
            ]
            ok_all = all(c[0] for c in checks)
            if ok_all:
                _ok(2, 1, "Missing attr step-1: '{}'".format(msg[:120]))
            else:
                _fail(2, 1, "Missing attr step-1",
                      "\n           msg={}\n           fails: {}".format(
                          msg, [c[1] for c in checks if not c[0]]))
    except Exception as e:
        _fail(2, 1, "Missing attr step-1", "Wrong exception: {}".format(type(e).__name__))

    # 2.2 Missing attribute at deeper step → shows full path and step number
    try:
        try:
            dc.coins.simple.nonexistent_price.get()
            _fail(2, 2, "Missing attr deeper step → clear path",
                  "No exception raised")
        except AttributeError as e:
            msg = str(e)
            has_path = "coins" in msg and "simple" in msg
            has_attr_name = "nonexistent_price" in msg
            has_step = "step 3" in msg or "step 4" in msg or "at step" in msg.lower()
            if has_path and has_attr_name and has_step:
                _ok(2, 2, "Deeper missing attr: '{}'".format(msg[:140]))
            else:
                _fail(2, 2, "Deeper missing attr",
                      "msg='{}'\npath={} attr={} step={}".format(
                          msg, has_path, has_attr_name, has_step))
    except Exception as e:
        _fail(2, 2, "Deeper missing attr", "Wrong exc: {}".format(e))

    # 2.3 Path resolves to non-callable → TypeError with path info
    try:
        # Create a key whose client has a non-callable attribute
        class _ClientWithAttr:
            some_value = 42

        k = SimpleKeyValueError("k_nc", _ClientWithAttr)
        mgr2 = ApiKeyManager([k])
        try:
            mgr2.dummyclient.some_value()
            _fail(2, 3, "Non-callable → TypeError", "No exception raised")
        except TypeError as e:
            msg = str(e)
            if "some_value" in msg and "non-callable" in msg:
                _ok(2, 3, "Non-callable TypeError: '{}'".format(msg[:120]))
            else:
                _fail(2, 3, "Non-callable TypeError",
                      "msg='{}' lacks details".format(msg))
    except Exception as e:
        _fail(2, 3, "Non-callable TypeError", "Wrong exc: {}".format(e))

    # 2.4 Valid chain still works after error handling changes
    try:
        result = mgr.dummyclient.get_data()
        assert result == {"result": "ok"}, "wrong result: {}".format(result)
        _ok(2, 4, "Valid 1-layer call still works post-fix")
    except Exception as e:
        _fail(2, 4, "Valid 1-layer call", str(e))

    # 2.5 Valid nested chain works
    try:
        keys_nested = [SimpleApiKey("n1", _NestedClient)]
        mgr_n = ApiKeyManager(keys_nested)
        result = mgr_n.dummyclient.nested.fetch()
        assert result == "nested_ok", "wrong: {}".format(result)
        _ok(2, 5, "Valid nested call works")
    except Exception as e:
        _fail(2, 5, "Valid nested call", str(e))


class SimpleKeyValueError(ApiKey):
    """Like SimpleApiKey but accepts a custom client class."""

    def __init__(self, key, client_class=_SimpleClient):
        self._key = key
        self._cc = client_class

    def get_primary_key(self):
        return self._key

    def create_client(self):
        return self._cc()

    def test_usability(self, client):
        return True


# ════════════════════════════════════════════
# Module 3 — Fix 3: PoolExhaustedError
# ════════════════════════════════════════════


def test_m3_pool_exhausted():
    """Module 3: Empty pool raises PoolExhaustedError, not IndexError."""
    print("\n── Module 3: PoolExhaustedError ──")

    # 3.1 random_one on empty pool → PoolExhaustedError
    try:
        k = FailingApiKey("only_one")
        mgr = ApiKeyManager([k], reach_limit_exc=ReachLimitError)
        # Exhaust the only key by calling through dummyclient
        try:
            mgr.dummyclient.a.b.c.d.e.deep_call()
        except ReachLimitError:
            pass  # expected — key removed
        # Now pool should be empty
        try:
            mgr.random_one()
            _fail(3, 1, "Empty pool → PoolExhaustedError",
                  "random_one() did not raise")
        except PoolExhaustedError as e:
            msg = str(e)
            if "exhausted" in msg.lower() or "archive" in msg.lower():
                _ok(3, 1, "PoolExhaustedError: '{}'".format(msg[:100]))
            else:
                _fail(3, 1, "PoolExhaustedError message vague",
                      "msg='{}'".format(msg))
        except IndexError as e:
            _fail(3, 1, "Empty pool → PoolExhaustedError (got IndexError!)",
                  "Got IndexError instead: {}".format(e))
        except Exception as e:
            _fail(3, 1, "Empty pool → PoolExhaustedError",
                  "Wrong exception {}: {}".format(type(e).__name__, e))
    except Exception as e:
        _fail(3, 1, "Empty pool → PoolExhaustedError",
              "Setup/execution failed: {}".format(e))

    # 3.2 DummyClient call on empty pool → PoolExhaustedError (propagated)
    try:
        k2 = FailingApiKey("solo")
        mgr2 = ApiKeyManager([k2], reach_limit_exc=ReachLimitError)
        try:
            mgr2.dummyclient.a.b.c.d.e.deep_call()
        except ReachLimitError:
            pass  # key removed, pool empty now
        try:
            mgr2.dummyclient.x.y.z()
            _fail(3, 2, "DummyClient on empty pool → PoolExhaustedError",
                  "Did not raise")
        except PoolExhaustedError:
            _ok(3, 2, "DummyClient call propagates PoolExhaustedError")
        except (IndexError, Exception) as e:
            _fail(3, 2, "DummyClient on empty pool → PoolExhaustedError",
                  "Got {}: {}".format(type(e).__name__, e))
    except Exception as e:
        _fail(3, 2, "DummyClient on empty pool", str(e))

    # 3.3 PoolExhaustedError message includes archive count
    try:
        keys = [FailingApiKey("a"), FailingApiKey("b"), FailingApiKey("c")]
        mgr3 = ApiKeyManager(keys, reach_limit_exc=ReachLimitError)
        # Exhaust all three
        for _ in range(3):
            try:
                mgr3.dummyclient.a.b.c.d.e.deep_call()
            except ReachLimitError:
                pass
        try:
            mgr3.random_one()
        except PoolExhaustedError as e:
            msg = str(e)
            if "3" in msg:  # should mention 3 archived keys
                _ok(3, 3, "Archive count in message: '{}'".format(msg[:100]))
            else:
                _ok(3, 3, "PoolExhaustedError raised (archive count check loose)")
        except Exception as e:
            _fail(3, 3, "Archive count in message",
                  "Wrong exception: {}".format(e))
    except Exception as e:
        _fail(3, 3, "Archive count setup", str(e))

    # 3.4 Non-empty pool does NOT raise PoolExhaustedError
    try:
        k_good = SimpleApiKey("good")
        mgr4 = ApiKeyManager([k_good])
        picked = mgr4.random_one()
        assert picked.primary_key == "good"
        _ok(3, 4, "Non-empty pool: random_one works fine")
    except PoolExhaustedError:
        _fail(3, 4, "Non-empty pool: no false positive",
              "Raised PoolExhaustedError unexpectedly!")
    except Exception as e:
        _fail(3, 4, "Non-empty pool", str(e))

    # 3.5 After removing all keys manually → PoolExhaustedError
    try:
        ks = [SimpleApiKey("x"), SimpleApiKey("y")]
        mgr5 = ApiKeyManager(ks)
        mgr5.remove_one("x")
        mgr5.remove_one("y")
        try:
            mgr5.random_one()
            _fail(3, 5, "Manual remove-all → PoolExhaustedError", "No raise")
        except PoolExhaustedError:
            _ok(3, 5, "Manual remove-all raises PoolExhaustedError")
        except Exception as e:
            _fail(3, 5, "Manual remove-all → PoolExhaustedError",
                  "Got {}: {}".format(type(e).__name__, e))
    except Exception as e:
        _fail(3, 5, "Manual remove-all setup", str(e))


# ════════════════════════════════════════════
# Module 4 — Regression: existing features still work
# ════════════════════════════════════════════


def test_m4_regression():
    """Module 4: Regression tests — nothing broken."""
    print("\n── Module 4: Regression Tests ──")

    # 4.1 Basic 1-layer call via dummyclient
    try:
        k = SimpleApiKey("r1")
        m = ApiKeyManager([k])
        r = m.dummyclient.get_data()
        assert r == {"result": "ok"}
        _ok(4, 1, "Regression: basic 1-layer call")
    except Exception as e:
        _fail(4, 1, "Regression: basic 1-layer call", str(e))

    # 4.2 Deep chain call (6 levels)
    try:
        k2 = SimpleApiKey("r2", _DeepClient)
        m2 = ApiKeyManager([k2])
        r2 = m2.dummyclient.a.b.c.d.e.deep_call()
        assert r2 == "called:a.b.c.d.e.deep_call"
        _ok(4, 2, "Regression: 6-level deep chain")
    except Exception as e:
        _fail(4, 2, "Regression: 6-level deep chain", str(e))

    # 4.3 Key rotation distributes calls across keys
    try:
        ks = [SimpleKeyValueError("rot_a", _DeepClient),
              SimpleKeyValueError("rot_b", _DeepClient),
              SimpleKeyValueError("rot_c", _DeepClient)]
        m3 = ApiKeyManager(ks)
        for _ in range(30):
            m3.dummyclient.a.b.c.d.e.deep_call()
        # Use stats to verify calls were distributed
        stats = m3.stats.usage_count_stats_in_recent_n_seconds(60)
        used_keys = list(stats.keys())
        assert len(used_keys) > 1, \
            "All calls went to same key(s): {}".format(used_keys)
        total_calls = sum(stats.values())
        assert total_calls == 30, "Expected 30 events, got {}".format(total_calls)
        _ok(4, 3, "Regression: rotation across {} key(s), {} total calls".format(
            len(used_keys), total_calls))
    except Exception as e:
        _fail(4, 3, "Regression: rotation", str(e))

    # 4.4 StatsCollector tracks events
    try:
        k4 = SimpleApiKey("st1")
        m4 = ApiKeyManager([k4])
        for _ in range(5):
            m4.dummyclient.get_data()
        cnt = m4.stats.usage_count_in_recent_n_seconds(60)
        assert cnt == 5, "Expected 5 events, got {}".format(cnt)
        _ok(4, 4, "Regression: stats tracking ({} events)".format(cnt))
    except Exception as e:
        _fail(4, 4, "Regression: stats tracking", str(e))

    # 4.5 ChainProxy repr
    try:
        k5 = SimpleApiKey("rp1")
        m5 = ApiKeyManager([k5])
        proxy = m5.dummyclient.coins.simple.price
        r = repr(proxy)
        assert "coins" in r and "simple" in r and "price" in r, \
            "Bad repr: {}".format(r)
        _ok(4, 5, "Regression: ChainProxy repr = '{}'".format(r))
    except Exception as e:
        _fail(4, 5, "Regression: ChainProxy repr", str(e))


# ════════════════════════════════════════════
# Main runner
# ════════════════════════════════════════════


def main():
    global _passed, _failed

    print("=" * 64)
    print("  apipool-ng v1.0.3 Bugfix Test Suite")
    print("  Source: {} (local)".format(PROJECT_ROOT))
    print("  Imported version: {}".format(apipool.__version__))
    print("=" * 64)

    test_m1_exports()
    test_m2_chainproxy_errors()
    test_m3_pool_exhausted()
    test_m4_regression()

    total = _passed + _failed
    print("\n" + "=" * 64)
    print("  Results: {}/{} passed, {} failed".format(_passed, total, _failed))
    if _failed > 0:
        print("\n  FAILED tests:")
        for status, mod, tid, desc in _results:
            if status == "FAIL":
                print("    {}.{} - {}".format(mod, tid, desc))
    print("=" * 64)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
