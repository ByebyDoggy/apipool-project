#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""RefreshToken model — supports token revocation / rotation."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import relationship

from ..database import Base

logger = logging.getLogger("apipool.models.refresh_token")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_jti = Column(String(255), unique=True, nullable=False, index=True)  # unique identifier for this token
    is_revoked = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=func.now())
    revoked_at = Column(DateTime, nullable=True)

    # Relationship
    user = relationship("User", backref="refresh_tokens")

    def revoke(self) -> None:
        """Mark this token as revoked."""
        self.is_revoked = True
        self.revoked_at = datetime.now(timezone.utc)

    __table_args__ = (
        Index("ix_refresh_tokens_user_active", "user_id", "is_revoked"),
    )

    def __repr__(self):
        jti_short = self.token_jti[:8]
        return f"RefreshToken(id={self.id}, jti='{jti_short}...', revoked={self.is_revoked})"
