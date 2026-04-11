#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pool management service — identifier mapping to ApiKeyManager."""

from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, status
from typing import Optional

from apipool import ApiKeyManager

from ..models.key_pool import KeyPool, PoolMember
from ..models.api_key_entry import ApiKeyEntry
from ..models.user import User
from ..security import KeyEncryption
from ..schemas.pool import (
    PoolCreateRequest, PoolUpdateRequest, PoolAddMembersRequest,
    PoolResponse, PoolMemberResponse, PoolStatusResponse, PoolConfigResponse,
)
from ..services.client_registry import GenericApiKey


class PoolNotFoundError(Exception):
    pass


class PoolEmptyError(Exception):
    pass


class PoolService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user: User, req: PoolCreateRequest) -> PoolResponse:
        # Check identifier uniqueness
        if self.db.query(KeyPool).filter(KeyPool.identifier == req.identifier).first():
            raise HTTPException(
                status_code=409,
                detail=f"Pool identifier '{req.identifier}' already exists",
            )

        pool = KeyPool(
            user_id=user.id,
            identifier=req.identifier,
            name=req.name,
            description=req.description,
            client_type=req.client_type,
            reach_limit_exception=req.reach_limit_exception,
            rotation_strategy=req.rotation_strategy,
            pool_config=req.pool_config,
        )
        self.db.add(pool)
        self.db.flush()

        # Add members if specified
        if req.key_identifiers:
            for key_id in req.key_identifiers:
                key_entry = self.db.query(ApiKeyEntry).filter(
                    and_(
                        ApiKeyEntry.identifier == key_id,
                        ApiKeyEntry.user_id == user.id,
                        ApiKeyEntry.is_active == True,
                        ApiKeyEntry.is_archived == False,
                    )
                ).first()
                if not key_entry:
                    raise HTTPException(
                        status_code=404,
                        detail=f"API Key '{key_id}' not found or not available",
                    )
                member = PoolMember(
                    pool_id=pool.id,
                    key_id=key_entry.id,
                )
                self.db.add(member)

        self.db.commit()
        self.db.refresh(pool)

        return self._to_response(pool)

    def list_pools(
        self, user: User, page: int = 1, page_size: int = 20,
    ) -> tuple[list[PoolResponse], int]:
        query = self.db.query(KeyPool).filter(
            and_(KeyPool.user_id == user.id, KeyPool.is_active == True)
        )
        total = query.count()
        items = query.order_by(KeyPool.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return [self._to_response(p) for p in items], total

    def get(self, user: User, identifier: str, include_members: bool = True) -> PoolResponse:
        pool = self._get_pool(user, identifier)
        return self._to_response(pool, include_members=include_members)

    def update(self, user: User, identifier: str, req: PoolUpdateRequest) -> PoolResponse:
        pool = self._get_pool(user, identifier)

        if req.name is not None:
            pool.name = req.name
        if req.description is not None:
            pool.description = req.description
        if req.reach_limit_exception is not None:
            pool.reach_limit_exception = req.reach_limit_exception
        if req.rotation_strategy is not None:
            pool.rotation_strategy = req.rotation_strategy
        if req.pool_config is not None:
            pool.pool_config = req.pool_config

        self.db.commit()
        self.db.refresh(pool)
        return self._to_response(pool)

    def delete(self, user: User, identifier: str) -> None:
        pool = self._get_pool(user, identifier)
        # Remove all member associations first
        self.db.query(PoolMember).filter(PoolMember.pool_id == pool.id).delete()
        self.db.delete(pool)
        self.db.commit()

    def add_members(self, user: User, identifier: str, req: PoolAddMembersRequest) -> PoolResponse:
        pool = self._get_pool(user, identifier)

        for key_id in req.key_identifiers:
            key_entry = self.db.query(ApiKeyEntry).filter(
                and_(
                    ApiKeyEntry.identifier == key_id,
                    ApiKeyEntry.user_id == user.id,
                    ApiKeyEntry.is_active == True,
                    ApiKeyEntry.is_archived == False,
                )
            ).first()
            if not key_entry:
                raise HTTPException(status_code=404, detail=f"API Key '{key_id}' not found")

            # Check if already a member
            existing = self.db.query(PoolMember).filter(
                and_(PoolMember.pool_id == pool.id, PoolMember.key_id == key_entry.id)
            ).first()
            if existing:
                continue

            member = PoolMember(
                pool_id=pool.id,
                key_id=key_entry.id,
                priority=req.priority,
                weight=req.weight,
            )
            self.db.add(member)

        self.db.commit()
        self.db.refresh(pool)
        return self._to_response(pool)

    def remove_member(self, user: User, pool_identifier: str, key_identifier: str) -> None:
        pool = self._get_pool(user, pool_identifier)
        key_entry = self.db.query(ApiKeyEntry).filter(
            and_(ApiKeyEntry.identifier == key_identifier, ApiKeyEntry.user_id == user.id)
        ).first()
        if not key_entry:
            raise HTTPException(status_code=404, detail=f"API Key '{key_identifier}' not found")

        member = self.db.query(PoolMember).filter(
            and_(PoolMember.pool_id == pool.id, PoolMember.key_id == key_entry.id)
        ).first()
        if not member:
            raise HTTPException(status_code=404, detail="Key is not a member of this pool")

        self.db.delete(member)
        self.db.commit()

    def get_status(self, user: User, identifier: str) -> PoolStatusResponse:
        pool = self._get_pool(user, identifier)
        members = self._get_active_members(pool)
        archived_count = self.db.query(PoolMember).join(ApiKeyEntry).filter(
            and_(
                PoolMember.pool_id == pool.id,
                ApiKeyEntry.is_archived == True,
            )
        ).count()

        return PoolStatusResponse(
            pool_identifier=pool.identifier,
            available_keys=len(members),
            archived_keys=archived_count,
            total_keys=len(pool.members),
        )

    def build_manager(self, pool_identifier: str, user_id: int) -> ApiKeyManager:
        """
        Core method: build an ApiKeyManager from a pool identifier.
        This implements the identifier → ApiKeyManager mapping.
        
        All keys are instantiated as GenericApiKey regardless of client_type.
        client_type is purely a user-defined label for categorization/filtering.
        Users create their own client objects on the SDK side.
        """
        pool = self.db.query(KeyPool).filter(
            and_(
                KeyPool.identifier == pool_identifier,
                KeyPool.user_id == user_id,
                KeyPool.is_active == True,
            )
        ).first()

        if not pool:
            raise PoolNotFoundError(f"Pool '{pool_identifier}' not found")

        members = self._get_active_members(pool)
        if not members:
            raise PoolEmptyError(f"Pool '{pool_identifier}' has no available keys")

        # Decrypt and instantiate GenericApiKey for all entries
        # client_type is metadata only — doesn't affect key instantiation
        apikey_list = []
        for member_entry in members:
            raw_key = KeyEncryption.decrypt(member_entry.encrypted_key)
            # Use GenericApiKey: creates a generic HTTP client (httpx)
            # with Bearer token auth. Users can customize via client_config.
            apikey = GenericApiKey(raw_key=raw_key, client_config=member_entry.client_config)
            apikey_list.append(apikey)

        # Resolve reach_limit_exception
        reach_limit_exc = self._resolve_exception(pool.reach_limit_exception)

        # Build the ApiKeyManager — same core object as the library mode
        manager = ApiKeyManager(
            apikey_list=apikey_list,
            reach_limit_exc=reach_limit_exc,
        )

        return manager

    def _get_pool(self, user: User, identifier: str) -> KeyPool:
        pool = self.db.query(KeyPool).filter(
            and_(
                KeyPool.identifier == identifier,
                KeyPool.user_id == user.id,
            )
        ).first()
        if not pool:
            raise HTTPException(status_code=404, detail=f"Pool '{identifier}' not found")
        return pool

    def _get_active_members(self, pool: KeyPool) -> list[ApiKeyEntry]:
        return (
            self.db.query(ApiKeyEntry)
            .join(PoolMember)
            .filter(
                and_(
                    PoolMember.pool_id == pool.id,
                    ApiKeyEntry.is_active == True,
                    ApiKeyEntry.is_archived == False,
                )
            )
            .all()
        )

    def _resolve_exception(self, exception_path: Optional[str]):
        """Dynamically import an exception class from its dotted path."""
        if not exception_path:
            return None
        try:
            module_path, class_name = exception_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError, ValueError):
            return None

    def get_config(self, user: User, identifier: str) -> PoolConfigResponse:
        """Get pool configuration for client-side sync."""
        pool = self._get_pool(user, identifier)
        return PoolConfigResponse(
            pool_identifier=pool.identifier,
            client_type=pool.client_type,
            reach_limit_exception=pool.reach_limit_exception,
            rotation_strategy=pool.rotation_strategy,
            pool_config=pool.pool_config,
        )

    def _to_response(self, pool: KeyPool, include_members: bool = False) -> PoolResponse:
        members_resp = None
        if include_members:
            members_resp = []
            for member in pool.members:
                key_entry = member.api_key
                members_resp.append(PoolMemberResponse(
                    key_identifier=key_entry.identifier,
                    alias=key_entry.alias,
                    priority=member.priority,
                    weight=member.weight,
                    verification_status=key_entry.verification_status,
                ))

        return PoolResponse(
            id=pool.id,
            identifier=pool.identifier,
            name=pool.name,
            description=pool.description,
            client_type=pool.client_type,
            reach_limit_exception=pool.reach_limit_exception,
            rotation_strategy=pool.rotation_strategy,
            pool_config=pool.pool_config,
            is_active=pool.is_active,
            member_count=len(pool.members),
            members=members_resp,
            created_at=pool.created_at,
            updated_at=pool.updated_at,
        )
