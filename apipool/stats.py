#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
stats用于统计API的使用记录. 我们使用一个RDS数据库(通常是本地的sqlite), 记录每个
API Call所使用的api key, 返回的状态 以及 完成API Call的时间.
"""

from datetime import datetime, timedelta
from collections import OrderedDict

from sqlalchemy import Column, ForeignKey, create_engine, text, inspect
from sqlalchemy import String, Integer, Float, DateTime, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class ApiKey(Base):
    __tablename__ = "apikey"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True)

    events = relationship("Event", back_populates="apikey")

    def __repr__(self):
        return "ApiKey(id=%r, key=%r)" % (self.id, self.key)


class Status(Base):
    __tablename__ = "status"

    id = Column(Integer, primary_key=True)
    description = Column(String, unique=True)

    events = relationship("Event", back_populates="status")

    def __repr__(self):
        return "Status(id=%r, description=%r)" % (self.id, self.description)


class Event(Base):
    __tablename__ = "event"

    apikey_id = Column(Integer, ForeignKey("apikey.id"), primary_key=True)
    finished_at = Column(DateTime, primary_key=True)
    status_id = Column(Integer, ForeignKey("status.id"))
    latency = Column(Float, nullable=True)
    method = Column(String(128), nullable=True)

    apikey = relationship("ApiKey")
    status = relationship("Status")


class StatusCollection(object):
    class c1_Success(object):
        id = 1
        description = "success"

    class c5_Failed(object):
        id = 5
        description = "failed"

    class c9_ReachLimit(object):
        id = 9
        description = "reach limit"

    @classmethod
    def get_subclasses(cls):
        return [cls.c1_Success, cls.c5_Failed, cls.c9_ReachLimit]

    @classmethod
    def get_id_list(cls):
        return [klass.id for klass in cls.get_subclasses()]

    @classmethod
    def get_description_list(cls):
        return [klass.description for klass in cls.get_subclasses()]

    @classmethod
    def get_mapper_id_to_description(cls):
        return {
            klass.id: klass.description
            for klass in cls.get_subclasses()
        }

    @classmethod
    def get_mapper_description_to_id(cls):
        return {
            klass.description: klass.id
            for klass in cls.get_subclasses()
        }

    @classmethod
    def get_status_list(cls):
        return [
            Status(id=klass.id, description=klass.description)
            for klass in cls.get_subclasses()
        ]


def get_n_seconds_before(n_seconds):
    return datetime.now() - timedelta(seconds=n_seconds)


class StatsCollector(object):
    def __init__(self, engine):
        Base.metadata.create_all(engine)
        self.engine = engine
        self.ses = self.create_session()

        self._add_all_status()
        self._migrate_event_table()

        self._cache_apikey = dict()
        self._cache_status = StatusCollection.get_mapper_id_to_description()
        self._update_cache()

    def create_session(self):
        return sessionmaker(bind=self.engine)()

    def close(self):
        self.ses.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _add_all_status(self):
        ses = self.create_session()
        for status in StatusCollection.get_status_list():
            existing = (
                ses.query(Status)
                .filter(Status.id == status.id)
                .first()
            )
            if existing is None:
                ses.add(status)
        ses.commit()
        ses.close()

    def add_all_apikey(self, apikey_list):
        data = [ApiKey(key=apikey.primary_key) for apikey in apikey_list]
        ses = self.create_session()
        for item in data:
            existing = (
                ses.query(ApiKey)
                .filter(ApiKey.key == item.key)
                .first()
            )
            if existing is None:
                ses.add(item)
        ses.commit()
        ses.close()
        self._update_cache()

    def _update_cache(self):
        ses = self.create_session()
        apikey_list = ses.query(ApiKey).all()
        for apikey in apikey_list:
            self._cache_apikey.setdefault(apikey.key, apikey.id)
        ses.close()

    def add_event(self, primary_key, status_id, latency=None, method=None):
        event = Event(
            apikey_id=self._cache_apikey[primary_key],
            finished_at=datetime.now(),
            status_id=status_id,
            latency=latency,
            method=method,
        )
        ses = self.create_session()
        ses.add(event)
        ses.commit()
        ses.close()

    def query_event_in_recent_n_seconds(self,
                                        n_seconds,
                                        primary_key=None,
                                        status_id=None):
        n_seconds_before = get_n_seconds_before(n_seconds)
        filters = [Event.finished_at >= n_seconds_before, ]
        if not (primary_key is None):
            filters.append(Event.apikey_id == self._cache_apikey[primary_key])
        if not (status_id is None):
            filters.append(Event.status_id == status_id)
        return self.ses.query(Event).filter(*filters)

    def usage_count_in_recent_n_seconds(self,
                                        n_seconds,
                                        primary_key=None,
                                        status_id=None):
        q = self.query_event_in_recent_n_seconds(
            n_seconds,
            primary_key=primary_key,
            status_id=status_id,
        )
        return q.count()

    def usage_count_stats_in_recent_n_seconds(self, n_seconds):
        n_seconds_before = get_n_seconds_before(n_seconds)
        q = self.ses.query(ApiKey.key, func.count(Event.apikey_id)) \
            .select_from(Event).join(ApiKey) \
            .filter(Event.finished_at >= n_seconds_before) \
            .group_by(Event.apikey_id) \
            .order_by(ApiKey.key)
        return OrderedDict(q.all())

    # ── Migration for new columns ──────────────────────────────────────

    def _migrate_event_table(self):
        """Add latency and method columns to existing Event table."""
        try:
            inspector = inspect(self.engine)
        except Exception:
            return
        if "event" not in inspector.get_table_names():
            return
        columns = {col["name"] for col in inspector.get_columns("event")}
        if "latency" not in columns:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE event ADD COLUMN latency FLOAT"))
            except Exception:
                pass
        if "method" not in columns:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE event ADD COLUMN method VARCHAR(128)"))
            except Exception:
                pass

    # ── Batch fetch and delete for stats reporting ─────────────────────

    @property
    def _apikey_id_to_key(self):
        """Reverse mapping: apikey_id -> primary_key string."""
        return {v: k for k, v in self._cache_apikey.items()}

    def fetch_events_batch(self, limit=500):
        """Fetch a batch of events for reporting, ordered by finished_at.

        Returns a list of dicts with keys:
            key_identifier, status_id, latency, method, finished_at,
            _apikey_id, _finished_at (for deletion)
        """
        ses = self.create_session()
        events = (
            ses.query(Event)
            .order_by(Event.finished_at.asc())
            .limit(limit)
            .all()
        )
        id_to_key = self._apikey_id_to_key
        result = []
        for evt in events:
            result.append({
                "key_identifier": id_to_key.get(evt.apikey_id, ""),
                "status_id": evt.status_id,
                "latency": evt.latency,
                "method": evt.method,
                "finished_at": evt.finished_at,
                "_apikey_id": evt.apikey_id,
                "_finished_at": evt.finished_at,
            })
        ses.close()
        return result

    def delete_events(self, events_to_delete):
        """Delete reported events from local DB by their composite primary key.

        Args:
            events_to_delete: list of dicts as returned by fetch_events_batch
        """
        if not events_to_delete:
            return
        ses = self.create_session()
        try:
            for evt in events_to_delete:
                ses.query(Event).filter(
                    Event.apikey_id == evt["_apikey_id"],
                    Event.finished_at == evt["_finished_at"],
                ).delete()
            ses.commit()
        except Exception:
            ses.rollback()
        finally:
            ses.close()
