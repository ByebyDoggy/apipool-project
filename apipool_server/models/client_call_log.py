#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Client-reported API call log model."""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, func
from ..database import Base


class ClientCallLog(Base):
    """Stores API call statistics reported by SDK clients.

    Unlike the per-pool SQLite stats (which only capture proxy-mode calls),
    this table aggregates statistics from all DynamicKeyManager clients that
    periodically report their local call events.
    """

    __tablename__ = "client_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pool_identifier = Column(String(64), nullable=False, index=True)
    key_identifier = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False)
    latency = Column(Float, nullable=True)
    method = Column(String(128), nullable=True)
    finished_at = Column(DateTime, nullable=False, index=True)
    reported_at = Column(DateTime, server_default=func.now())
    client_id = Column(String(64), nullable=True)
