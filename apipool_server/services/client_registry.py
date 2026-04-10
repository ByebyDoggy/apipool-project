#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Client type registry — maps client_type strings to ApiKey subclasses."""

from apipool import ApiKey


class ClientRegistry:
    """
    Registry that maps client_type identifiers to ApiKey subclasses.
    
    Usage:
        @ClientRegistry.register("googlemaps")
        class GoogleMapsApiKey(ApiKey):
            ...
    """
    _registry: dict[str, type[ApiKey]] = {}

    @classmethod
    def register(cls, client_type: str):
        """Decorator: register an ApiKey subclass for a client_type."""
        def decorator(apikey_class: type[ApiKey]):
            if client_type in cls._registry:
                raise ValueError(f"client_type '{client_type}' already registered")
            cls._registry[client_type] = apikey_class
            return apikey_class
        return decorator

    @classmethod
    def get(cls, client_type: str) -> type[ApiKey]:
        """Get the ApiKey subclass for a given client_type."""
        if client_type not in cls._registry:
            raise ValueError(
                f"Unknown client_type: '{client_type}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return cls._registry[client_type]

    @classmethod
    def list_types(cls) -> list[str]:
        """List all registered client types."""
        return sorted(cls._registry.keys())

    @classmethod
    def has(cls, client_type: str) -> bool:
        return client_type in cls._registry


# ── Built-in client types ──

@ClientRegistry.register("generic")
class GenericApiKey(ApiKey):
    """Generic API key for any HTTP-based API."""

    def __init__(self, raw_key: str, client_config: dict | None = None):
        self._raw_key = raw_key
        self._client_config = client_config or {}

    def get_primary_key(self):
        return self._raw_key

    def create_client(self):
        """Create a generic HTTP client using httpx."""
        import httpx
        base_url = self._client_config.get("base_url", "")
        timeout = self._client_config.get("timeout", 30)
        headers = self._client_config.get("headers", {})
        # Inject the key into headers (common pattern: Bearer token)
        if "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self._raw_key}"
        return httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    def test_usability(self, client):
        """Generic usability check — try a HEAD/GET to the base URL."""
        try:
            base_url = self._client_config.get("test_url")
            if base_url:
                resp = client.get(base_url)
                return resp.status_code < 500
            return True
        except Exception:
            return False


@ClientRegistry.register("openai")
class OpenAIApiKey(ApiKey):
    """OpenAI API key."""

    def __init__(self, raw_key: str, client_config: dict | None = None):
        self._raw_key = raw_key
        self._client_config = client_config or {}

    def get_primary_key(self):
        return self._raw_key

    def create_client(self):
        try:
            import openai
            return openai.Client(api_key=self._raw_key)
        except ImportError:
            # Fallback to generic HTTP client
            import httpx
            base_url = self._client_config.get("base_url", "https://api.openai.com/v1")
            return httpx.Client(
                base_url=base_url,
                headers={
                    "Authorization": f"Bearer {self._raw_key}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )

    def test_usability(self, client):
        try:
            if hasattr(client, "models"):
                client.models.list()
                return True
            return True
        except Exception:
            return False


@ClientRegistry.register("googlemaps")
class GoogleMapsApiKey(ApiKey):
    """Google Maps API key."""

    def __init__(self, raw_key: str, client_config: dict | None = None):
        self._raw_key = raw_key
        self._client_config = client_config or {}

    def get_primary_key(self):
        return self._raw_key

    def create_client(self):
        try:
            import googlemaps
            return googlemaps.Client(key=self._raw_key)
        except ImportError:
            import httpx
            return httpx.Client(
                base_url="https://maps.googleapis.com/maps/api/",
                params={"key": self._raw_key},
                timeout=30,
            )

    def test_usability(self, client):
        try:
            if hasattr(client, "geocode"):
                client.geocode("test")
            return True
        except Exception:
            return False
