#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Authentication service."""

import logging
import secrets
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from ..models.user import User
from ..models.refresh_token import RefreshToken
from ..security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse

logger = logging.getLogger("apipool.auth")


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register(self, req: RegisterRequest) -> UserResponse:
        if self.db.query(User).filter(User.username == req.username).first():
            raise HTTPException(status_code=409, detail="Username already exists")
        if self.db.query(User).filter(User.email == req.email).first():
            raise HTTPException(status_code=409, detail="Email already exists")

        user = User(
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return UserResponse.model_validate(user)

    def login(self, req: LoginRequest) -> TokenResponse:
        user = self.db.query(User).filter(User.username == req.username).first()
        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )

        # Revoke all existing refresh tokens for this user (single-session or rotate)
        _revoke_user_tokens(self.db, user.id)

        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()

        return self._issue_tokens(user)

    def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        jti = payload.get("jti")
        user_id = int(payload.get("sub", 0))

        # Check token revocation
        stored = self.db.query(RefreshToken).filter(
            RefreshToken.token_jti == jti,
            RefreshToken.user_id == user_id,
        ).first()
        if not stored or stored.is_revoked:
            logger.warning("Revoked/unknown refresh_token used: jti=%s", jti)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked",
            )

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled",
            )

        # Token Rotation: revoke old refresh token, issue new pair
        stored.revoke()
        return self._issue_tokens(user)

    def logout(self, refresh_token: str) -> None:
        """Revoke a refresh token on logout."""
        payload = decode_token(refresh_token)
        if not payload:
            return  # Invalid/expired — ignore gracefully
        jti = payload.get("jti")
        user_id = int(payload.get("sub", 0))
        stored = self.db.query(RefreshToken).filter(
            RefreshToken.token_jti == jti,
            RefreshToken.user_id == user_id,
        ).first()
        if stored and not stored.is_revoked:
            stored.revoke()
            self.db.commit()
            logger.info("User %s logged out, refresh token revoked.", user_id)

    def get_current_user(self, token: str) -> User:
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload.get("sub")
        user = self.db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        return user

    # ── Internal helpers ────────────────────────────────────────────

    def _issue_tokens(self, user: User) -> TokenResponse:
        """Create a new access + refresh token pair with JTI."""
        from ..config import get_settings

        jti = secrets.token_urlsafe(32)
        sub_data = {"sub": str(user.id), "username": user.username, "role": user.role, "jti": jti}

        access_token = create_access_token(sub_data)
        refresh_payload = {**sub_data, "jti": jti}
        refresh_token = create_refresh_token(refresh_payload)

        # Store refresh token for revocation tracking
        rt_record = RefreshToken(
            user_id=user.id,
            token_jti=jti,
            is_revoked=False,
        )
        self.db.add(rt_record)
        self.db.commit()

        settings = get_settings()
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )


def _revoke_user_tokens(db: Session, user_id: int) -> None:
    """Revoke ALL existing non-revoked refresh tokens for a user."""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False,
    ).update({"is_revoked": True, "revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
