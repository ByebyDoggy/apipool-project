#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""API Key entry model — stores encrypted API keys with identifiers."""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, JSON, ForeignKey, func
from sqlalchemy.orm import relationship

from ..database import Base


class ApiKeyEntry(Base):
    __tablename__ = "api_key_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Identifier — globally unique, non-sensitive reference
    identifier = Column(String(128), unique=True, nullable=False, index=True)
    alias = Column(String(128), nullable=True)

    # Encrypted key data
    encrypted_key = Column(Text, nullable=False)

    # Client configuration (service type is determined by pool membership, not here)
    client_config = Column(JSON, nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    is_archived = Column(Boolean, default=False)
    last_verified_at = Column(DateTime, nullable=True)
    verification_status = Column(
        Enum("unknown", "valid", "invalid", "rate_limited", name="verification_status"),
        default="unknown",
    )

    # Metadata
    tags = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    owner = relationship("User", back_populates="api_keys")
    pool_memberships = relationship("PoolMember", back_populates="api_key", cascade="all, delete-orphan")

    def __repr__(self):
        return f"ApiKeyEntry(id={self.id}, identifier={self.identifier!r})"
