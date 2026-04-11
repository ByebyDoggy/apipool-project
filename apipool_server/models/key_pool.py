#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Key pool and pool member models."""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, JSON, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship

from ..database import Base


class KeyPool(Base):
    __tablename__ = "key_pools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    identifier = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)

    # Client configuration
    client_type = Column(String(128), nullable=False)
    reach_limit_exception = Column(String(256), nullable=True)

    # Rotation strategy
    rotation_strategy = Column(
        Enum("random", "round_robin", "least_used", name="rotation_strategy"),
        default="random",
    )

    # Pool-level configuration (synced to client managers)
    pool_config = Column(JSON, nullable=True, comment="Client-synced config: concurrency, timeout, rate_limit, etc.")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    owner = relationship("User", back_populates="pools")
    members = relationship("PoolMember", back_populates="pool", cascade="all, delete-orphan")

    def __repr__(self):
        return f"KeyPool(id={self.id}, identifier={self.identifier!r})"


class PoolMember(Base):
    __tablename__ = "pool_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_id = Column(Integer, ForeignKey("key_pools.id"), nullable=False, index=True)
    key_id = Column(Integer, ForeignKey("api_key_entries.id"), nullable=False, index=True)
    priority = Column(Integer, default=0)
    weight = Column(Integer, default=1)
    joined_at = Column(DateTime, default=func.now())

    # Relationships
    pool = relationship("KeyPool", back_populates="members")
    api_key = relationship("ApiKeyEntry", back_populates="pool_memberships")

    __table_args__ = (
        UniqueConstraint("pool_id", "key_id", name="uq_pool_key"),
    )

    def __repr__(self):
        return f"PoolMember(pool_id={self.pool_id}, key_id={self.key_id})"
