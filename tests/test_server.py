#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Integration tests for apipool_server — full API flow test."""

import os
import sys
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a temporary file-based SQLite DB for testing (in-memory doesn't share across connections)
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["APIPOOL_ENCRYPTION_KEY"] = ""  # Auto-generate
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["APIPOOL_ADMIN_USERNAME"] = "admin"
os.environ["APIPOOL_ADMIN_PASSWORD"] = "admin123"
os.environ["APIPOOL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["DEBUG"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

# Reset database module globals to pick up new env vars
import apipool_server.database as _db_mod
_db_mod._engine = None
_db_mod._SessionLocal = None

from fastapi.testclient import TestClient

from apipool_server.database import get_engine, init_db, get_session_local, Base
from apipool_server.main import create_app
from apipool_server.security import hash_password, KeyEncryption
from apipool_server.models.user import User
from apipool_server.services.client_registry import ClientRegistry

# Create app and initialize DB
app = create_app()
init_db()

# Create test user
SessionLocal = get_session_local()
db = SessionLocal()
test_user = User(
    username="testuser",
    email="test@example.com",
    hashed_password=hash_password("TestPass123"),
    role="user",
)
db.add(test_user)
db.commit()
db.close()

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    print("[PASS] Health check")


def test_auth_flow():
    # Register
    resp = client.post("/api/v1/auth/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "Str0ngP@ss1",
    })
    assert resp.status_code == 201
    user_data = resp.json()
    assert user_data["username"] == "alice"
    print("[PASS] Register")

    # Login
    resp = client.post("/api/v1/auth/login", json={
        "username": "alice",
        "password": "Str0ngP@ss1",
    })
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    print("[PASS] Login")

    # Refresh
    resp = client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert "access_token" in new_tokens
    print("[PASS] Refresh token")

    return tokens["access_token"]


def test_key_management(token):
    headers = {"Authorization": f"Bearer {token}"}

    # Create key
    resp = client.post("/api/v1/keys", json={
        "identifier": "test-generic-key-1",
        "alias": "Test Generic Key",
        "raw_key": "sk-test-12345",
        "client_type": "generic",
        "tags": ["test"],
        "description": "A test key",
    }, headers=headers)
    if resp.status_code != 201:
        print(f"  [DEBUG] status={resp.status_code}, body={resp.text}")
    assert resp.status_code == 201
    key_data = resp.json()
    assert key_data["identifier"] == "test-generic-key-1"
    # raw_key must NEVER be in response
    assert "raw_key" not in resp.text or '"raw_key"' not in resp.text
    assert "encrypted_key" not in resp.text
    print("[PASS] Create key")

    # List keys
    resp = client.get("/api/v1/keys", headers=headers)
    assert resp.status_code == 200
    keys = resp.json()
    assert keys["total"] >= 1
    print("[PASS] List keys")

    # Get key
    resp = client.get("/api/v1/keys/test-generic-key-1", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["identifier"] == "test-generic-key-1"
    print("[PASS] Get key")

    # Update key
    resp = client.put("/api/v1/keys/test-generic-key-1", json={
        "alias": "Updated Alias",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["alias"] == "Updated Alias"
    print("[PASS] Update key")

    # Create second key
    resp = client.post("/api/v1/keys", json={
        "identifier": "test-generic-key-2",
        "raw_key": "sk-test-67890",
        "client_type": "generic",
    }, headers=headers)
    assert resp.status_code == 201
    print("[PASS] Create second key")

    return key_data


def test_pool_management(token):
    headers = {"Authorization": f"Bearer {token}"}

    # Create pool
    resp = client.post("/api/v1/pools", json={
        "identifier": "test-pool",
        "name": "Test Pool",
        "client_type": "generic",
        "rotation_strategy": "random",
        "key_identifiers": ["test-generic-key-1", "test-generic-key-2"],
    }, headers=headers)
    assert resp.status_code == 201
    pool_data = resp.json()
    assert pool_data["identifier"] == "test-pool"
    assert pool_data["member_count"] == 2
    print("[PASS] Create pool")

    # Get pool with members
    resp = client.get("/api/v1/pools/test-pool", headers=headers)
    assert resp.status_code == 200
    pool = resp.json()
    assert pool["members"] is not None
    assert len(pool["members"]) == 2
    print("[PASS] Get pool with members")

    # Pool status
    resp = client.get("/api/v1/pools/test-pool/status", headers=headers)
    assert resp.status_code == 200
    status_data = resp.json()
    assert status_data["available_keys"] == 2
    print("[PASS] Pool status")

    return pool_data


def test_proxy_call(token):
    headers = {"Authorization": f"Bearer {token}"}

    # Proxy status check
    resp = client.get("/api/v1/proxy/test-pool/status", headers=headers)
    assert resp.status_code == 200
    print("[PASS] Proxy status")

    # Proxy invoke with method_chain (generic client → httpx → get method exists)
    resp = client.post("/api/v1/proxy/test-pool/call", json={
        "method_chain": "get",
        "args": ["https://httpbin.org/get"],
        "kwargs": {},
    }, headers=headers)
    # May fail due to network, but API should accept the request
    assert resp.status_code == 200
    data = resp.json()
    print(f"[PASS] Proxy call (success={data['success']}, error={data.get('error', 'none')})")


def test_stats(token):
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/stats/test-pool/usage", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()
    assert "summary" in stats
    print("[PASS] Stats usage")


def test_client_types():
    resp = client.get("/api/v1/info/client-types")
    assert resp.status_code == 200
    data = resp.json()
    assert "generic" in data["client_types"]
    assert "openai" in data["client_types"]
    assert "googlemaps" in data["client_types"]
    print("[PASS] Client types listing")


def test_encryption():
    original = "sk-super-secret-key-12345"
    encrypted = KeyEncryption.encrypt(original)
    decrypted = KeyEncryption.decrypt(encrypted)
    assert decrypted == original
    assert encrypted != original
    print("[PASS] Key encryption/decryption")


def test_sdk_client():
    """Test the SDK client module (local import test)."""
    from apipool.client import connect, login, ServiceApiKey, _ServiceClient, _ServiceChainLink

    # Test ServiceApiKey instantiation
    key = ServiceApiKey(
        service_url="http://localhost:8000",
        pool_identifier="test-pool",
        auth_token="fake-token",
        key_id="test-key",
    )
    assert key.get_primary_key() == "test-key"
    print("[PASS] SDK client module")


if __name__ == "__main__":
    print("=" * 60)
    print("apipool_server Integration Tests")
    print("=" * 60)

    test_health()
    test_encryption()
    test_client_types()
    test_sdk_client()

    token = test_auth_flow()
    test_key_management(token)
    test_pool_management(token)
    test_proxy_call(token)
    test_stats(token)

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)
