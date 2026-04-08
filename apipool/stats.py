#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
stats用于统计API的使用记录. 我们使用一个RDS数据库(通常是本地的sqlite), 记录每个
API Call所使用的api key, 返回的状态 以及 完成API Call的时间.
"""

from datetime import datetime, timedelta
from collections import OrderedDict

from sqlalchemy import Column, ForeignKey, create_engine
from sqlalchemy import String, Integer, DateTime, func
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

        self._cache_apikey = dict()
        self._cache_status = StatusCollection.get_mapper_id_to_description()

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

    def add_event(self, primary_key, status_id):
        event = Event(
            apikey_id=self._cache_apikey[primary_key],
            finished_at=datetime.now(),
            status_id=status_id,
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
