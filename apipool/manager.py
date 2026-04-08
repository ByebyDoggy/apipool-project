#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
built-in stats collector service for api usage and status.
"""

import sys
import random
from collections import OrderedDict
from sqlalchemy import create_engine

from .apikey import ApiKey
from .stats import StatusCollection, StatsCollector


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
