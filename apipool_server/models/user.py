#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""User model."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, func
from sqlalchemy.orm import relationship

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum("admin", "user", name="user_role"), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    api_keys = relationship("ApiKeyEntry", back_populates="owner", lazy="dynamic")
    pools = relationship("KeyPool", back_populates="owner", lazy="dynamic")

    def __repr__(self):
        return f"User(id={self.id}, username={self.username!r})"
