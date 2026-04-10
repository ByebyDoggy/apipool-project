#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Proxy call service — transparent API invocation through identifier mapping."""

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from apipool import ApiKeyManager

from ..models.user import User
from ..schemas.pool import ProxyInvokeRequest, ProxyCallRequest, ProxyResponse
from ..services.pool_service import PoolService, PoolNotFoundError, PoolEmptyError


class ProxyService:
    def __init__(self, db: Session):
        self.db = db
        self.pool_service = PoolService(db)

    def invoke(self, user: User, pool_identifier: str, req: ProxyInvokeRequest) -> ProxyResponse:
        """
        Execute a proxied API call through the pool's ApiKeyManager.
        
        The attr_path is resolved via ChainProxy transparently.
        """
        try:
            manager = self.pool_service.build_manager(pool_identifier, user.id)
        except PoolNotFoundError:
            raise HTTPException(status_code=404, detail=f"Pool '{pool_identifier}' not found")
        except PoolEmptyError:
            raise HTTPException(status_code=503, detail=f"Pool '{pool_identifier}' has no available keys")

        # Navigate the attribute chain via ChainProxy
        target = manager.dummyclient
        for attr in req.attr_path:
            try:
                target = getattr(target, attr)
            except AttributeError:
                path = ".".join(req.attr_path)
                raise HTTPException(
                    status_code=400,
                    detail=f"Attribute '{attr}' not found in chain '{path}'",
                )

        if not callable(target):
            path = ".".join(req.attr_path)
            raise HTTPException(
                status_code=400,
                detail=f"Chain '{path}' resolved to non-callable",
            )

        # Execute the call
        try:
            result = target(*req.args, **req.kwargs)
            result = self._serialize_result(result)
            available = len(manager.apikey_chain)
            total = available + len(manager.archived_apikey_chain)
            return ProxyResponse(
                success=True,
                data=result,
                pool_available=available,
                pool_total=total,
            )
        except Exception as e:
            exc_type = type(e).__name__
            available = len(manager.apikey_chain)
            total = available + len(manager.archived_apikey_chain)
            # Check if it's a reach-limit error (key was removed)
            return ProxyResponse(
                success=False,
                error=f"{exc_type}: {str(e)}",
                pool_available=available,
                pool_total=total,
            )

    def call(self, user: User, pool_identifier: str, req: ProxyCallRequest) -> ProxyResponse:
        """Convenience: invoke with dot-separated method_chain string."""
        attr_path = req.method_chain.split(".")
        invoke_req = ProxyInvokeRequest(
            attr_path=attr_path,
            args=req.args,
            kwargs=req.kwargs,
        )
        return self.invoke(user, pool_identifier, invoke_req)

    @staticmethod
    def _serialize_result(result):
        """Convert non-serializable result types to JSON-safe values."""
        # httpx.Response
        if hasattr(result, "status_code") and hasattr(result, "json"):
            try:
                return {
                    "_type": "httpx.Response",
                    "status_code": result.status_code,
                    "headers": dict(result.headers),
                    "data": result.json() if result.text else None,
                }
            except Exception:
                return {
                    "_type": "httpx.Response",
                    "status_code": result.status_code,
                    "text": result.text[:10000] if result.text else None,
                }
        return result
