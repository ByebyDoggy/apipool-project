# -*- coding: utf-8 -*-
"""Alembic initial migration for apipool_server."""

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(64), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('admin', 'user', name='user_role'), server_default='user'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table('api_key_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('identifier', sa.String(255), nullable=False),
        sa.Column('alias', sa.String(255), nullable=True),
        sa.Column('encrypted_key', sa.Text(), nullable=False),
        sa.Column('client_config', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('is_archived', sa.Boolean(), server_default='false'),
        sa.Column('verification_status', sa.String(32), server_default='unknown'),
        sa.Column('last_verified_at', sa.DateTime(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )
    op.create_index('ix_api_key_entries_identifier', 'api_key_entries', ['identifier'])

    op.create_table('key_pools',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('identifier', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('client_type', sa.String(64), nullable=True),
        sa.Column('rotation_strategy', sa.String(32), default='random'),
        sa.Column('pool_config', sa.JSON(), nullable=True),
        sa.Column('member_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )

    op.create_table('pool_members',
        sa.Column('pool_id', sa.Integer(), nullable=False),
        sa.Column('key_id', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('pool_id', 'key_id'),
        sa.ForeignKeyConstraint(['pool_id'], ['key_pools.id']),
        sa.ForeignKeyConstraint(['key_id'], ['api_key_entries.id'])
    )

    op.create_table('refresh_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_jti', sa.String(255), nullable=False),
        sa.Column('is_revoked', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )
    op.create_index('ix_refresh_tokens_jti', 'refresh_tokens', ['token_jti'], unique=True)


def downgrade() -> None:
    op.drop_table('refresh_tokens')
    op.drop_table('pool_members')
    op.drop_table('key_pools')
    op.drop_table('api_key_entries')
    op.drop_table('users')
