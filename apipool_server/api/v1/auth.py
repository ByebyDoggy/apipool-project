#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Auth API routes."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...schemas.auth import (
    RegisterRequest, LoginRequest, RefreshRequest,
    TokenResponse, UserResponse,
)
from ...services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate current user from Authorization header."""
    if not authorization.startswith("Bearer "):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:]
    auth_service = AuthService(db)
    return auth_service.get_current_user(token)


# Dependency for protected routes
get_current_user = _get_current_user


# Public endpoints

@router.post("/register", response_model=UserResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
    service = AuthService(db)
    return service.register(req)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Login and obtain JWT tokens."""
    service = AuthService(db)
    return service.login(req)


@router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    """Refresh access token."""
    service = AuthService(db)
    return service.refresh_access_token(req.refresh_token)


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return user
