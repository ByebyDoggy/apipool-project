#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Security utilities: JWT, password hashing, API Key encryption."""

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet
from jose import JWTError, jwt
import bcrypt

from .config import get_settings

# ── Password hashing ──


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# ── JWT ──

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


# ── API Key encryption (Fernet / AES-256) ──

class KeyEncryption:
    """Encrypt/decrypt API Key plaintext using Fernet (AES-256-CBC)."""

    _fernet: Optional[Fernet] = None

    @classmethod
    def _get_fernet(cls) -> Fernet:
        if cls._fernet is None:
            settings = get_settings()
            key_b64 = settings.APIPOOL_ENCRYPTION_KEY
            if not key_b64:
                # Auto-generate for development (NOT for production)
                key_b64 = Fernet.generate_key().decode()
            cls._fernet = Fernet(key_b64.encode() if isinstance(key_b64, str) else key_b64)
        return cls._fernet

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """Encrypt API Key plaintext, return Base64-encoded ciphertext."""
        f = cls._get_fernet()
        return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """Decrypt API Key ciphertext, return plaintext."""
        f = cls._get_fernet()
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    @classmethod
    def generate_key(cls) -> str:
        """Generate a new Fernet key for configuration."""
        return Fernet.generate_key().decode("utf-8")
