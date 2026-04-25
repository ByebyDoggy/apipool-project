#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Configuration management for apipool_server."""

import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # Application
    APP_NAME: str = "apipool-server"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite:///./apipool_server.db"

    # Redis (optional)
    REDIS_URL: str | None = None

    # Encryption (Fernet key for API Key storage)
    APIPOOL_ENCRYPTION_KEY: str = ""

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Admin bootstrap
    APIPOOL_ADMIN_USERNAME: str = "admin"
    APIPOOL_ADMIN_PASSWORD: str = "admin"
    APIPOOL_ADMIN_EMAIL: str = "admin@apipool.local"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Stats DB directory (per-pool SQLite files for call statistics)
    STATS_DB_DIR: str = "data/stats"

    # Rate limiting
    RATE_LIMIT_PER_USER_PER_MINUTE: int = 60
    RATE_LIMIT_PROXY_PER_POOL_PER_MINUTE: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


def get_settings() -> Settings:
    return Settings()
