#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Database connection and session management."""

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None

Base = declarative_base()

# Schema migrations: list of (table, column, alter_sql) to add missing columns
_MIGRATIONS = [
    # key_pools — new columns added in v1.1
    ("key_pools", "reach_limit_exception",
     "ALTER TABLE key_pools ADD COLUMN reach_limit_exception VARCHAR(256)"),
    ("key_pools", "rotation_strategy",
     "ALTER TABLE key_pools ADD COLUMN rotation_strategy VARCHAR(16) DEFAULT 'random'"),
    ("key_pools", "pool_config",
     "ALTER TABLE key_pools ADD COLUMN pool_config JSON"),
    # api_key_entries — new columns added in v1.1
    ("api_key_entries", "client_config",
     "ALTER TABLE api_key_entries ADD COLUMN client_config JSON"),
    ("api_key_entries", "is_archived",
     "ALTER TABLE api_key_entries ADD COLUMN is_archived BOOLEAN DEFAULT 0"),
    ("api_key_entries", "verification_status",
     "ALTER TABLE api_key_entries ADD COLUMN verification_status VARCHAR(16) DEFAULT 'unknown'"),
    ("api_key_entries", "last_verified_at",
     "ALTER TABLE api_key_entries ADD COLUMN last_verified_at DATETIME"),
    ("api_key_entries", "tags",
     "ALTER TABLE api_key_entries ADD COLUMN tags JSON"),
    ("api_key_entries", "description",
     "ALTER TABLE api_key_entries ADD COLUMN description TEXT"),
    # pool_members — new columns added in v1.1
    ("pool_members", "priority",
     "ALTER TABLE pool_members ADD COLUMN priority INTEGER DEFAULT 0"),
    ("pool_members", "weight",
     "ALTER TABLE pool_members ADD COLUMN weight INTEGER DEFAULT 1"),
]

# New tables to create if they don't exist (for backward compatibility)
_NEW_TABLES = [
    """CREATE TABLE IF NOT EXISTS refresh_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token_jti VARCHAR(255) UNIQUE NOT NULL,
        is_revoked BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        revoked_at DATETIME,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""",
]


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.DATABASE_URL,
            connect_args=(
                {"check_same_thread": False}
                if settings.DATABASE_URL.startswith("sqlite")
                else {}
            ),
            echo=settings.DEBUG,
        )
    return _engine


def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


def get_db():
    """FastAPI dependency that yields a database session."""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_migrations(engine):
    """Add missing columns to existing tables and create new tables."""
    inspector = inspect(engine)

    # Create new tables if they don't exist
    for create_sql in _NEW_TABLES:
        try:
            with engine.begin() as conn:
                conn.execute(text(create_sql))
            logger.info("Migration: created new table")
        except Exception as exc:
            logger.debug("Table creation skipped: %s", exc)

    # Add missing columns
    for table_name, column_name, alter_sql in _MIGRATIONS:
        if table_name not in inspector.get_table_names():
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name not in existing_columns:
            try:
                with engine.begin() as conn:
                    conn.execute(text(alter_sql))
                logger.info("Migration: added column %s.%s", table_name, column_name)
            except Exception as exc:
                logger.warning("Migration failed for %s.%s: %s", table_name, column_name, exc)


def init_db():
    """Create all tables and run migrations for missing columns."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
