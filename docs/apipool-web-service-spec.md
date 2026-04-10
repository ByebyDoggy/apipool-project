# apipool Web 服务化改造开发文档

> **版本**: v1.0  
> **日期**: 2026-04-09  
> **优先级**: P1  
> **提出方**: apipool-ng 项目组  

---

## 1. 概述

### 1.1 改造目标

将 apipool 从纯 Python 库改造为带前端页面的 Web 服务，实现：

- **Web 管理界面**：用户通过浏览器动态配置和管理 API Keys
- **用户登录认证**：多用户隔离，每人管理自己的密钥池
- **标识符映射**：API Key 通过唯一标识符（ID 或别名）引用，敏感 Key 不再暴露给调用方
- **透明无感调用**：脚本调用时只需指定标识符，由服务端自动完成 Key 选择、轮换、限流处理

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **业务逻辑不变** | 现有的 `ApiKeyManager`、`ChainProxy`、`StatsCollector` 核心机制完全保留 |
| **敏感信息零暴露** | 调用方永远无法获取原始 API Key 明文 |
| **向后兼容** | 原有的纯库模式仍然可用，Web 模式为可选增强 |
| **最小依赖** | 后端和前端依赖尽量精简，避免引入重量级框架 |

### 1.3 调用方式对比

**改造前**（直接内嵌敏感 Key）：

```python
from apipool import ApiKey, ApiKeyManager

class MyKey(ApiKey):
    def get_primary_key(self): return "sk-real-api-key-12345"  # 敏感信息硬编码
    def create_client(self): return SomeClient(self.get_primary_key())
    def test_usability(self, client): return True

manager = ApiKeyManager([MyKey(), MyKey2()])
result = manager.dummyclient.some_api.call("param")
```

**改造后**（标识符引用，无感调用）：

```python
from apipool import ApiKeyManager

# 通过服务端获取 manager，仅需标识符
manager = ApiKeyManager.from_service(
    service_url="http://localhost:8000",
    identifier="my-google-geocoding",  # 别名，非敏感
    auth_token="user-jwt-token"
)

result = manager.dummyclient.some_api.call("param")
# 业务代码与改造前完全一致，ChainProxy / 统计 / 轮换机制不变
```

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        调用方 (Client)                           │
│  ┌───────────────┐    ┌────────────────┐    ┌───────────────┐  │
│  │  Python 脚本   │    │  CI/CD Pipeline │    │  其他服务调用  │  │
│  └───────┬───────┘    └───────┬────────┘    └───────┬───────┘  │
│          │                    │                     │           │
│          └────────────────────┼─────────────────────┘           │
│                               │                                 │
│                   apipool SDK (pip install)                     │
│                               │                                 │
└───────────────────────────────┼─────────────────────────────────┘
                                │ HTTP / HTTPS
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     apipool Web Service                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    API Gateway Layer                       │  │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │  │
│  │  │ 认证中间件 │  │ 限流中间件 │  │ 请求日志/审计中间件    │  │  │
│  │  └──────────┘  └──────────┘  └───────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Auth 模块   │  │  Key 管理模块  │  │  Proxy 调用模块       │  │
│  │             │  │              │  │                      │  │
│  │ · 登录/注册  │  │ · CRUD Keys  │  │ · 标识符 → Key 映射  │  │
│  │ · JWT 签发  │  │ · 别名管理    │  │ · 自动选择/轮换      │  │
│  │ · 权限校验  │  │ · 可用性检测  │  │ · ChainProxy 代理    │  │
│  │ · 角色管理  │  │ · 批量导入    │  │ · 统计收集           │  │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                │                      │              │
│         └────────────────┼──────────────────────┘              │
│                          │                                     │
│  ┌───────────────────────┼─────────────────────────────────┐  │
│  │              核心引擎 (现有 apipool 核心)                  │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │  │
│  │  │ ApiKeyManager │  │  ChainProxy   │  │ StatsCollector │ │  │
│  │  │  (池管理)     │  │  (链式代理)   │  │  (统计追踪)    │ │  │
│  │  └──────────────┘  └──────────────┘  └───────────────┘ │  │
│  └─────────────────────────────────────────────────────────┘  │
│                          │                                     │
│  ┌───────────────────────┼─────────────────────────────────┐  │
│  │              数据持久层                                   │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │  │
│  │  │  PostgreSQL   │  │   Redis      │  │  加密存储      │ │  │
│  │  │  (用户/Key/   │  │  (会话/缓存/ │  │  (Key 明文     │ │  │
│  │  │   统计/事件)  │  │   限流计数)  │  │   AES-256)     │ │  │
│  │  └──────────────┘  └──────────────┘  └───────────────┘ │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     前端管理界面 (SPA)                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ 登录页面  │  │ Key 管理  │  │ 统计面板  │  │ 系统设置     │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 技术选型

| 层级 | 技术 | 理由 |
|------|------|------|
| **Web 框架** | FastAPI | 异步高性能，自动生成 OpenAPI 文档，类型安全 |
| **前端框架** | Vue 3 + TDesign Vue | 腾讯 TDesign 企业级组件库，与 apipool-ng 定位一致 |
| **数据库** | PostgreSQL | 生产级关系数据库，支持 JSON 字段 |
| **缓存** | Redis | 会话管理、限流计数、Key 池热缓存 |
| **ORM** | SQLAlchemy (现有) | 无需引入新依赖，与现有 `StatsCollector` 一致 |
| **认证** | JWT (python-jose) | 无状态认证，适合分布式部署 |
| **加密** | cryptography (Fernet) | API Key 明文的对称加密存储 |
| **任务队列** | Celery + Redis | 异步执行可用性检测、批量导入等长任务 |

### 2.3 项目结构

```
apipool-project/
├── apipool/                      # 现有核心库 (保持不变)
│   ├── __init__.py
│   ├── apikey.py
│   ├── manager.py
│   ├── stats.py
│   └── tests/
│
├── apipool_server/               # ===== 新增: Web 服务端 =====
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 配置管理 (环境变量 / .env)
│   ├── database.py               # 数据库连接与会话管理
│   ├── security.py               # 认证/加密/权限工具
│   │
│   ├── models/                   # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── user.py               # 用户模型
│   │   ├── api_key_entry.py      # API Key 存储模型
│   │   └── key_pool.py           # 密钥池模型
│   │
│   ├── schemas/                  # Pydantic 请求/响应模型
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── api_key.py
│   │   ├── pool.py
│   │   └── stats.py
│   │
│   ├── api/                      # API 路由
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py           # 认证接口
│   │   │   ├── keys.py           # Key 管理接口
│   │   │   ├── pools.py          # 密钥池管理接口
│   │   │   ├── proxy.py          # 透明代理调用接口
│   │   │   └── stats.py          # 统计查询接口
│   │   └── router.py             # 路由聚合
│   │
│   ├── services/                 # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── key_service.py
│   │   ├── pool_service.py       # 核心服务: 标识符映射 → ApiKeyManager
│   │   ├── proxy_service.py      # 核心服务: 透明代理调用
│   │   └── stats_service.py
│   │
│   ├── tasks/                    # 异步任务
│   │   ├── __init__.py
│   │   └── health_check.py       # 定时可用性检测
│   │
│   └── middleware/               # 中间件
│       ├── __init__.py
│       ├── auth.py               # JWT 认证中间件
│       ├── rate_limit.py         # 限流中间件
│       └── audit.py              # 审计日志中间件
│
├── apipool_web/                  # ===== 新增: 前端项目 =====
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── router/
│   │   ├── stores/               # Pinia 状态管理
│   │   ├── views/
│   │   │   ├── Login.vue
│   │   │   ├── Dashboard.vue     # 统计概览
│   │   │   ├── KeyManager.vue    # Key 管理
│   │   │   ├── PoolManager.vue   # 密钥池管理
│   │   │   └── Settings.vue
│   │   ├── components/
│   │   │   ├── KeyForm.vue       # Key 编辑表单
│   │   │   ├── KeyTable.vue      # Key 列表
│   │   │   ├── StatsChart.vue    # 统计图表
│   │   │   └── UsageTimeline.vue # 使用时间线
│   │   └── api/                  # 后端 API 调用封装
│   │       ├── auth.ts
│   │       ├── keys.ts
│   │       ├── pools.ts
│   │       └── stats.ts
│   └── dist/                     # 构建产物 (FastAPI 静态托管)
│
├── migrations/                   # Alembic 数据库迁移
│   ├── alembic.ini
│   └── versions/
│
├── docker-compose.yml            # 容器编排
├── Dockerfile
└── requirements-server.txt       # 服务端额外依赖
```

---

## 3. 数据模型设计

### 3.1 用户模型 (User)

```python
# apipool_server/models/user.py

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)       # bcrypt 哈希
    role = Column(Enum("admin", "user"), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)

    # 关系
    api_keys = relationship("ApiKeyEntry", back_populates="owner")
    pools = relationship("KeyPool", back_populates="owner")
```

### 3.2 API Key 存储模型 (ApiKeyEntry)

```python
# apipool_server/models/api_key_entry.py

class ApiKeyEntry(Base):
    __tablename__ = "api_key_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 标识信息
    identifier = Column(String(128), unique=True, nullable=False, index=True)
    # identifier 示例: "google-geocoding-prod-1", "openai-key-backup"
    # 全局唯一，用于替代敏感 Key 作为引用标识

    alias = Column(String(128), nullable=True)
    # 别名，更友好的显示名称，如 "Google地理编码-生产环境"

    # 敏感信息 (加密存储)
    encrypted_key = Column(Text, nullable=False)
    # 原始 API Key 明文经 AES-256-Fernet 加密后的密文

    # 客户端配置
    client_type = Column(String(128), nullable=False)
    # 客户端类型标识，如 "googlemaps", "openai", "custom"
    # 用于服务端自动实例化对应的 ApiKey 子类

    client_config = Column(JSON, nullable=True)
    # 客户端额外配置 (JSON)，如:
    # {"base_url": "https://api.example.com", "timeout": 30}

    # 状态
    is_active = Column(Boolean, default=True)
    is_archived = Column(Boolean, default=False)
    last_verified_at = Column(DateTime, nullable=True)
    verification_status = Column(
        Enum("unknown", "valid", "invalid", "rate_limited"),
        default="unknown"
    )

    # 元数据
    tags = Column(JSON, nullable=True)         # 标签，如 ["production", "backup"]
    description = Column(Text, nullable=True)  # 描述
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    owner = relationship("User", back_populates="api_keys")
    pool_memberships = relationship("PoolMember", back_populates="api_key")
```

### 3.3 密钥池模型 (KeyPool)

```python
# apipool_server/models/key_pool.py

class KeyPool(Base):
    __tablename__ = "key_pools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    identifier = Column(String(128), unique=True, nullable=False, index=True)
    # 密钥池标识符，如 "google-geocoding"
    # 这是 SDK 调用时传入的标识符

    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)

    # 客户端配置 (池级别，可被 Key 级别覆盖)
    client_type = Column(String(128), nullable=False)
    reach_limit_exception = Column(String(256), nullable=True)
    # reach_limit 异常类路径，如 "geopy.exc.GeocoderQuotaExceeded"

    # 轮换策略
    rotation_strategy = Column(
        Enum("random", "round_robin", "least_used"),
        default="random"
    )

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关系
    owner = relationship("User", back_populates="pools")
    members = relationship("PoolMember", back_populates="pool")


class PoolMember(Base):
    """密钥池与 API Key 的多对多关联"""
    __tablename__ = "pool_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_id = Column(Integer, ForeignKey("key_pools.id"), nullable=False, index=True)
    key_id = Column(Integer, ForeignKey("api_key_entries.id"), nullable=False, index=True)
    priority = Column(Integer, default=0)       # 优先级 (越大越优先)
    weight = Column(Integer, default=1)         # 权重 (随机策略中的概率权重)
    joined_at = Column(DateTime, default=func.now())

    pool = relationship("KeyPool", back_populates="members")
    api_key = relationship("ApiKeyEntry", back_populates="pool_memberships")

    __table_args__ = (
        UniqueConstraint("pool_id", "key_id", name="uq_pool_key"),
    )
```

### 3.4 ER 关系图

```
┌──────────────┐       ┌──────────────────────┐       ┌──────────────────┐
│    User      │       │    ApiKeyEntry        │       │    KeyPool       │
├──────────────┤       ├──────────────────────┤       ├──────────────────┤
│ id (PK)      │──┐    │ id (PK)              │──┐    │ id (PK)          │
│ username     │  │    │ user_id (FK)         │  │    │ user_id (FK)     │
│ email        │  │    │ identifier (UQ)  ◄───┼──┼────│ identifier (UQ)  │
│ hashed_pass  │  │    │ alias                │  │    │ name             │
│ role         │  │    │ encrypted_key        │  │    │ client_type      │
│ is_active    │  │    │ client_type          │  │    │ reach_limit_exc  │
│ created_at   │  │    │ client_config (JSON) │  │    │ rotation_strategy│
│ updated_at   │  │    │ is_active            │  │    │ is_active        │
│ last_login   │  │    │ is_archived          │  │    │ created_at       │
└──────────────┘  │    │ last_verified_at     │  │    └────────┬─────────┘
                  │    │ verification_status  │  │             │
                  │    │ tags (JSON)          │  │             │
                  │    │ description          │  │             │
                  │    │ created_at           │  │             │
                  │    └──────────────────────┘  │             │
                  │                              │             │
                  │         ┌────────────────────┴──┐    ┌─────┴──────────┐
                  │         │    PoolMember         │    │                │
                  │         ├───────────────────────┤    │                │
                  └─────────│ id (PK)               │    │                │
                            │ pool_id (FK) ─────────┼────┘                │
                            │ key_id (FK) ──────────┼─────┘               │
                            │ priority              │                      │
                            │ weight                │                      │
                            └───────────────────────┘                      │
                                                                         │
                                          调用方仅需知道 pool.identifier ──┘
```

---

## 4. 接口规范

### 4.1 认证接口

#### POST `/api/v1/auth/register`

注册新用户。

**请求体**:
```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "Str0ngP@ssw0rd"
}
```

**响应** `201 Created`:
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "role": "user",
  "created_at": "2026-04-09T10:00:00Z"
}
```

#### POST `/api/v1/auth/login`

用户登录，获取 JWT Token。

**请求体**:
```json
{
  "username": "alice",
  "password": "Str0ngP@ssw0rd"
}
```

**响应** `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

#### POST `/api/v1/auth/refresh`

刷新 Token。

**请求体**:
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**响应** `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

---

### 4.2 API Key 管理接口

#### POST `/api/v1/keys`

创建 API Key 条目。

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "identifier": "google-geocoding-prod-1",
  "alias": "Google地理编码-生产Key1",
  "raw_key": "AIzaSyD...",
  "client_type": "googlemaps",
  "client_config": {
    "timeout": 30
  },
  "tags": ["production", "geocoding"],
  "description": "生产环境主要Key"
}
```

> **安全说明**: `raw_key` 仅在创建请求中传输一次，服务端加密存储后立即从内存清除，永远不会通过 API 返回。

**响应** `201 Created`:
```json
{
  "id": 1,
  "identifier": "google-geocoding-prod-1",
  "alias": "Google地理编码-生产Key1",
  "client_type": "googlemaps",
  "client_config": {"timeout": 30},
  "is_active": true,
  "verification_status": "unknown",
  "tags": ["production", "geocoding"],
  "description": "生产环境主要Key",
  "created_at": "2026-04-09T10:30:00Z"
}
```

#### GET `/api/v1/keys`

列出当前用户的所有 API Key。

**请求头**: `Authorization: Bearer <token>`

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `client_type` | string | 按客户端类型筛选 |
| `is_active` | bool | 按状态筛选 |
| `tag` | string | 按标签筛选 |
| `page` | int | 页码 (默认 1) |
| `page_size` | int | 每页条数 (默认 20, 最大 100) |

**响应** `200 OK`:
```json
{
  "items": [
    {
      "id": 1,
      "identifier": "google-geocoding-prod-1",
      "alias": "Google地理编码-生产Key1",
      "client_type": "googlemaps",
      "is_active": true,
      "verification_status": "valid",
      "last_verified_at": "2026-04-09T11:00:00Z",
      "tags": ["production"],
      "created_at": "2026-04-09T10:30:00Z"
    }
  ],
  "total": 15,
  "page": 1,
  "page_size": 20
}
```

> **注意**: 列表接口永远不返回 `encrypted_key` 或 `raw_key` 字段。

#### GET `/api/v1/keys/{identifier}`

获取单个 Key 详情（不含密钥明文）。

**响应** `200 OK`: 同上单个条目结构。

#### PUT `/api/v1/keys/{identifier}`

更新 Key 元数据（别名、标签、描述等），**不能**更新密钥明文。

**请求体**:
```json
{
  "alias": "新别名",
  "tags": ["production", "backup"],
  "description": "更新描述"
}
```

#### PATCH `/api/v1/keys/{identifier}/rotate`

轮换密钥。使旧 Key 失效，绑定新 Key。

**请求体**:
```json
{
  "new_raw_key": "AIzaSyNewKey..."
}
```

#### DELETE `/api/v1/keys/{identifier}`

软删除（归档）Key。

**响应** `204 No Content`

#### POST `/api/v1/keys/{identifier}/verify`

触发可用性验证。

**响应** `200 OK`:
```json
{
  "identifier": "google-geocoding-prod-1",
  "verification_status": "valid",
  "verified_at": "2026-04-09T12:00:00Z"
}
```

#### POST `/api/v1/keys/batch-import`

批量导入 Keys。

**请求体**:
```json
{
  "client_type": "googlemaps",
  "keys": [
    {"raw_key": "AIzaSyKey1...", "alias": "Key 1"},
    {"raw_key": "AIzaSyKey2...", "alias": "Key 2"}
  ]
}
```

**响应** `202 Accepted`:
```json
{
  "task_id": "batch-import-abc123",
  "status": "processing",
  "total": 2
}
```

---

### 4.3 密钥池管理接口

#### POST `/api/v1/pools`

创建密钥池。

**请求体**:
```json
{
  "identifier": "google-geocoding",
  "name": "Google地理编码API池",
  "description": "生产环境Google地理编码API密钥池",
  "client_type": "googlemaps",
  "reach_limit_exception": "geopy.exc.GeocoderQuotaExceeded",
  "rotation_strategy": "random",
  "key_identifiers": [
    "google-geocoding-prod-1",
    "google-geocoding-prod-2"
  ]
}
```

**响应** `201 Created`:
```json
{
  "id": 1,
  "identifier": "google-geocoding",
  "name": "Google地理编码API池",
  "client_type": "googlemaps",
  "rotation_strategy": "random",
  "is_active": true,
  "member_count": 2,
  "created_at": "2026-04-09T11:00:00Z"
}
```

#### GET `/api/v1/pools`

列出当前用户的密钥池。

#### GET `/api/v1/pools/{identifier}`

获取密钥池详情（含成员列表，不含密钥明文）。

**响应** `200 OK`:
```json
{
  "id": 1,
  "identifier": "google-geocoding",
  "name": "Google地理编码API池",
  "client_type": "googlemaps",
  "rotation_strategy": "random",
  "is_active": true,
  "members": [
    {
      "key_identifier": "google-geocoding-prod-1",
      "alias": "Key 1",
      "priority": 0,
      "weight": 1,
      "verification_status": "valid"
    },
    {
      "key_identifier": "google-geocoding-prod-2",
      "alias": "Key 2",
      "priority": 0,
      "weight": 1,
      "verification_status": "valid"
    }
  ],
  "created_at": "2026-04-09T11:00:00Z"
}
```

#### PUT `/api/v1/pools/{identifier}`

更新密钥池配置。

#### POST `/api/v1/pools/{identifier}/members`

向池中添加 Key。

**请求体**:
```json
{
  "key_identifiers": ["google-geocoding-prod-3"],
  "priority": 0,
  "weight": 1
}
```

#### DELETE `/api/v1/pools/{identifier}/members/{key_identifier}`

从池中移除 Key。

---

### 4.4 透明代理调用接口

#### POST `/api/v1/proxy/{pool_identifier}/call`

核心接口：通过标识符透明调用 API。

**请求头**: `Authorization: Bearer <token>`

**请求体**:
```json
{
  "method_chain": "geocode",
  "args": ["1600 Amphitheatre Parkway"],
  "kwargs": {}
}
```

**响应** `200 OK`:
```json
{
  "success": true,
  "data": {
    "latitude": 37.4224764,
    "longitude": -122.0842499
  },
  "key_used": "google-geocoding-prod-1",
  "stats": {
    "pool_available": 2,
    "pool_total": 3
  }
}
```

**多层链式调用示例**:

```json
{
  "method_chain": "coins.simple.price.get",
  "args": [],
  "kwargs": {"ids": "bitcoin", "vs_currencies": "usd"}
}
```

#### POST `/api/v1/proxy/{pool_identifier}/invoke

SDK 专用接口：接收完整的调用指令。

**请求体**:
```json
{
  "attr_path": ["coins", "simple", "price", "get"],
  "args": [],
  "kwargs": {"ids": "bitcoin", "vs_currencies": "usd"}
}
```

**响应**: 同上。

#### GET `/api/v1/proxy/{pool_identifier}/status

查询池状态。

**响应** `200 OK`:
```json
{
  "pool_identifier": "google-geocoding",
  "available_keys": 2,
  "archived_keys": 1,
  "total_keys": 3,
  "recent_stats": {
    "success_count_1h": 150,
    "failed_count_1h": 2,
    "reach_limit_count_1h": 1
  }
}
```

---

### 4.5 统计接口

#### GET `/api/v1/stats/{pool_identifier}/usage

查询使用统计。

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `seconds` | int | 统计最近 N 秒 (默认 3600) |
| `group_by` | string | 分组维度: `key` / `status` / `hour` |
| `status` | string | 筛选状态: `success` / `failed` / `reach_limit` |

**响应** `200 OK`:
```json
{
  "pool_identifier": "google-geocoding",
  "period_seconds": 3600,
  "summary": {
    "total_calls": 153,
    "success": 150,
    "failed": 2,
    "reach_limit": 1
  },
  "by_key": {
    "google-geocoding-prod-1": {
      "success": 80,
      "failed": 1,
      "reach_limit": 0
    },
    "google-geocoding-prod-2": {
      "success": 70,
      "failed": 1,
      "reach_limit": 1
    }
  }
}
```

#### GET `/api/v1/stats/{pool_identifier}/timeline

时间线统计（用于图表渲染）。

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `seconds` | int | 统计最近 N 秒 |
| `interval` | string | 采样间隔: `minute` / `hour` / `day` |

---

## 5. 标识符映射与自动加载机制

### 5.1 核心设计

标识符映射是本次改造的核心机制，其设计目标是将 **"直接持有敏感 Key"** 转变为 **"持有非敏感标识符"**。

```
调用方                          服务端
  │                               │
  │  identifier = "google-geo"    │
  │  ─────────────────────────►   │
  │                               │  1. 验证用户权限
  │                               │  2. 根据 identifier 查询 KeyPool
  │                               │  3. 解密池内所有 ApiKeyEntry
  │                               │  4. 动态实例化 ApiKey 子类
  │                               │  5. 构建 ApiKeyManager
  │                               │  6. 执行 ChainProxy 调用
  │                               │
  │  ◄─────────────────────────   │
  │  返回调用结果 (不含Key明文)     │
```

### 5.2 客户端类型注册表

服务端维护一个客户端类型注册表，将 `client_type` 字符串映射到具体的 `ApiKey` 子类：

```python
# apipool_server/services/client_registry.py

from apipool import ApiKey

class ClientRegistry:
    """客户端类型注册表"""
    _registry: dict[str, type[ApiKey]] = {}

    @classmethod
    def register(cls, client_type: str):
        """装饰器：注册 ApiKey 子类"""
        def decorator(apikey_class):
            cls._registry[client_type] = apikey_class
            return apikey_class
        return decorator

    @classmethod
    def get(cls, client_type: str) -> type[ApiKey]:
        if client_type not in cls._registry:
            raise ValueError(f"Unknown client_type: {client_type}")
        return cls._registry[client_type]

    @classmethod
    def list_types(cls) -> list[str]:
        return list(cls._registry.keys())


# 使用示例
@ClientRegistry.register("googlemaps")
class GoogleMapsApiKey(ApiKey):
    def get_primary_key(self):
        return self._raw_key  # 由服务端注入

    def create_client(self):
        from googlemaps import Client
        return Client(key=self._raw_key)

    def test_usability(self, client):
        try:
            client.geocode("test")
            return True
        except Exception:
            return False


@ClientRegistry.register("openai")
class OpenAIApiKey(ApiKey):
    def get_primary_key(self):
        return self._raw_key

    def create_client(self):
        import openai
        return openai.Client(api_key=self._raw_key)

    def test_usability(self, client):
        try:
            client.models.list()
            return True
        except Exception:
            return False


@ClientRegistry.register("custom")
class CustomApiKey(ApiKey):
    """通用自定义客户端，通过 client_config 配置"""
    def get_primary_key(self):
        return self._raw_key

    def create_client(self):
        # 根据 client_config 动态构建客户端
        config = self._client_config or {}
        # ... 基于 config 创建客户端实例
        pass

    def test_usability(self, client):
        return True  # 自定义类型需用户自行验证
```

### 5.3 池服务：标识符 → ApiKeyManager 的映射

```python
# apipool_server/services/pool_service.py

from apipool import ApiKeyManager
from apipool_server.security import KeyEncryption
from apipool_server.services.client_registry import ClientRegistry

class PoolService:
    def __init__(self, db_session, cache_client):
        self.db = db_session
        self.cache = cache_client

    def build_manager(self, pool_identifier: str, user_id: int) -> ApiKeyManager:
        """
        根据标识符构建 ApiKeyManager 实例。
        
        流程:
        1. 查询 KeyPool 和其成员
        2. 解密所有 Key 的明文
        3. 动态实例化 ApiKey 子类
        4. 构建 ApiKeyManager
        """
        # 查询池
        pool = self.db.query(KeyPool).filter(
            KeyPool.identifier == pool_identifier,
            KeyPool.user_id == user_id,
            KeyPool.is_active == True
        ).first()

        if not pool:
            raise PoolNotFoundError(pool_identifier)

        # 查询池成员 (活跃 Key)
        members = (
            self.db.query(ApiKeyEntry)
            .join(PoolMember)
            .filter(
                PoolMember.pool_id == pool.id,
                ApiKeyEntry.is_active == True,
                ApiKeyEntry.is_archived == False
            )
            .all()
        )

        if not members:
            raise PoolEmptyError(pool_identifier)

        # 解密 + 实例化
        apikey_list = []
        key_class = ClientRegistry.get(pool.client_type)

        for member in members:
            raw_key = KeyEncryption.decrypt(member.encrypted_key)

            # 动态创建 ApiKey 实例
            apikey = key_class.__new__(key_class)
            apikey._raw_key = raw_key
            apikey._client_config = member.client_config
            apikey._client = None
            apikey._apikey_manager = None

            apikey_list.append(apikey)

        # 解析 reach_limit_exception
        reach_limit_exc = self._resolve_exception(pool.reach_limit_exception)

        # 构建缓存引擎 (避免每次重建数据库)
        stats_engine = self._get_or_create_stats_engine(pool_identifier)

        # 构建管理者 — 核心对象，与现有 ApiKeyManager 完全一致
        manager = ApiKeyManager(
            apikey_list=apikey_list,
            reach_limit_exc=reach_limit_exc,
            db_engine=stats_engine
        )

        return manager

    def _resolve_exception(self, exception_path: str | None):
        """根据类路径动态导入异常类"""
        if not exception_path:
            return None
        module_path, class_name = exception_path.rsplit(".", 1)
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)

    def _get_or_create_stats_engine(self, pool_identifier: str):
        """获取或创建统计数据库引擎 (按池隔离)"""
        # 优先使用 Redis 缓存的热引擎
        # 降级使用 SQLite 内存数据库
        ...
```

### 5.4 SDK 客户端：透明调用

SDK 封装使得调用方代码几乎不变：

```python
# apipool/client.py (新增模块，作为 SDK 的一部分)

import httpx
from apipool import ApiKey, ApiKeyManager

class ServiceApiKey(ApiKey):
    """服务端代理 ApiKey：本地不持有 Key 明文"""

    def __init__(self, service_url, pool_identifier, auth_token, key_id):
        self._service_url = service_url
        self._pool_identifier = pool_identifier
        self._auth_token = auth_token
        self._key_id = key_id

    def get_primary_key(self):
        # 返回标识符而非敏感 Key
        return self._key_id

    def create_client(self):
        return ServiceClient(
            base_url=self._service_url,
            pool_identifier=self._pool_identifier,
            auth_token=self._auth_token,
        )

    def test_usability(self, client):
        # 通过服务端健康检查接口验证
        resp = client._request("GET", f"/proxy/{self._pool_identifier}/status")
        return resp.get("available_keys", 0) > 0


class ServiceClient:
    """服务端代理客户端：将所有调用转发到服务端"""

    def __init__(self, base_url, pool_identifier, auth_token):
        self._base_url = base_url.rstrip("/")
        self._pool_identifier = pool_identifier
        self._http = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=30.0,
        )

    def _request(self, method, path, **kwargs):
        resp = self._http.request(method, f"/api/v1{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def __getattr__(self, item):
        """支持 ChainProxy 链式调用"""
        # 将属性访问记录到链路中
        return _ServiceChainLink(self, [item])


class _ServiceChainLink:
    """链式调用节点：收集属性路径，最终转发到服务端"""

    def __init__(self, service_client, attr_path):
        self._client = service_client
        self._attr_path = list(attr_path)

    def __getattr__(self, item):
        return _ServiceChainLink(self._client, self._attr_path + [item])

    def __call__(self, *args, **kwargs):
        # 最终调用：将完整链路发送到服务端
        return self._client._request(
            "POST",
            f"/proxy/{self._client._pool_identifier}/invoke",
            json={
                "attr_path": self._attr_path,
                "args": list(args),
                "kwargs": kwargs,
            }
        )


# ===== 便捷入口 =====

def connect(service_url: str, pool_identifier: str, auth_token: str) -> ApiKeyManager:
    """
    连接到 apipool 服务，获取可用的 ApiKeyManager。

    用法:
        manager = connect(
            service_url="http://localhost:8000",
            pool_identifier="google-geocoding",
            auth_token="eyJhbGciOiJIUzI1NiIs..."
        )
        result = manager.dummyclient.geocode("1600 Amphitheatre Parkway")
    """
    # 1. 查询池状态获取可用 Key 数量
    api_key = ServiceApiKey(service_url, pool_identifier, auth_token, key_id="service-proxy")

    # 2. 构建 manager (包含至少一个 ServiceApiKey)
    manager = ApiKeyManager([api_key])

    return manager
```

### 5.5 调用流程

```
SDK 调用方                                   apipool Web Service
    │                                                │
    │  manager = connect(url, "google-geo", token)   │
    │  ──────────────────────────────────────────►   │
    │          (查询池状态，构建本地 Manager)           │
    │                                                │
    │  manager.dummyclient.geocode(address)          │
    │  ──► ChainProxy.__getattr__("geocode")         │
    │  ──► ChainProxy.__call__("1600...")            │
    │  ──► random_one() → ServiceApiKey              │
    │  ──► ApiCaller → ServiceClient._request()      │
    │  ──────────────────────────────────────────►   │
    │          POST /api/v1/proxy/google-geo/invoke   │
    │          {attr_path:["geocode"], args:["1600"]} │
    │                                                │
    │                                    PoolService.build_manager()
    │                                    ├─ 查 KeyPool (by identifier)
    │                                    ├─ 查 ApiKeyEntry (池成员)
    │                                    ├─ 解密 raw_key
    │                                    ├─ 实例化 GoogleMapsApiKey
    │                                    ├─ 构建 ApiKeyManager (内存)
    │                                    └─ manager.dummyclient.geocode("1600")
    │                                         ├─ ChainProxy 导航
    │                                         ├─ ApiCaller 执行
    │                                         └─ StatsCollector 记录
    │                                                │
    │  ◄──────────────────────────────────────────   │
    │  {"success": true, "data": {...}}              │
```

---

## 6. 安全策略

### 6.1 API Key 加密存储

```python
# apipool_server/security.py

from cryptography.fernet import Fernet
import base64
import os

class KeyEncryption:
    """
    API Key 加密存储方案。
    
    使用 AES-256 (Fernet) 对称加密，主密钥从环境变量加载。
    支持密钥轮换：新旧密钥同时有效，逐步迁移。
    """

    # 主加密密钥 (环境变量 APIPOOL_ENCRYPTION_KEY)
    _primary_key: bytes | None = None

    # 轮换密钥列表 (用于解密旧数据)
    _rotation_keys: list[bytes] = []

    @classmethod
    def initialize(cls, encryption_key_b64: str = None):
        """
        初始化加密密钥。
        
        推荐通过环境变量传入:
          APIPOOL_ENCRYPTION_KEY = Fernet.generate_key().decode()
        """
        key_b64 = encryption_key_b64 or os.environ.get("APIPOOL_ENCRYPTION_KEY")
        if not key_b64:
            raise ValueError("Encryption key not configured")
        cls._primary_key = base64.urlsafe_b64decode(key_b64)

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """加密 API Key 明文，返回 Base64 编码的密文"""
        f = Fernet(cls._get_primary_key_b64())
        return f.encrypt(plaintext.encode()).decode()

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """解密 API Key 密文，返回明文"""
        # 先尝试主密钥，失败后依次尝试轮换密钥
        primary = Fernet(cls._get_primary_key_b64())
        try:
            return primary.decrypt(ciphertext.encode()).decode()
        except Exception:
            for old_key_b64 in cls._rotation_keys:
                try:
                    old_f = Fernet(old_key_b64)
                    return old_f.decrypt(ciphertext.encode()).decode()
                except Exception:
                    continue
            raise DecryptionError("No valid key found for decryption")

    @classmethod
    def _get_primary_key_b64(cls) -> bytes:
        return base64.urlsafe_b64encode(cls._primary_key)
```

### 6.2 认证与授权

```python
# 认证流程
#
# 1. 用户注册 → 密码 bcrypt 哈希存储
# 2. 用户登录 → 验证密码 → 签发 JWT (access + refresh)
# 3. 请求验证 → 中间件校验 JWT → 提取 user_id → 注入请求上下文
# 4. 权限控制 → 每个资源操作验证 user_id 一致性

# JWT 配置
JWT_CONFIG = {
    "algorithm": "HS256",
    "access_token_expire_minutes": 60,
    "refresh_token_expire_days": 30,
    "issuer": "apipool-server",
}
```

**权限模型**:

| 角色 | 权限 |
|------|------|
| `admin` | 管理所有用户、所有池、系统配置 |
| `user` | 仅管理自己的 Key 和池，仅查看自己的统计 |

**资源隔离**:

```python
# 每个 API 都强制 user_id 过滤
@app.get("/api/v1/keys")
async def list_keys(current_user: User = Depends(get_current_user)):
    # current_user 从 JWT 提取，不可伪造
    keys = db.query(ApiKeyEntry).filter(
        ApiKeyEntry.user_id == current_user.id  # 强制隔离
    ).all()
    ...
```

### 6.3 传输安全

| 措施 | 说明 |
|------|------|
| **HTTPS 强制** | 生产环境必须启用 TLS，所有请求走 443 |
| **Key 传输限制** | `raw_key` 仅在创建/轮换请求中出现，响应中永远不返回 |
| **内存清理** | 解密后的 Key 明文在使用后立即 `del`，减少内存驻留时间 |
| **请求日志脱敏** | 日志中自动过滤 `raw_key`、`encrypted_key` 等敏感字段 |

### 6.4 限流与防滥用

```python
# apipool_server/middleware/rate_limit.py

RATE_LIMIT_CONFIG = {
    # 全局限制: 每用户每分钟最大请求数
    "global_per_user_per_minute": 60,

    # 代理调用限制: 每池每用户每分钟
    "proxy_per_pool_per_minute": 30,

    # Key 管理操作限制
    "key_management_per_user_per_minute": 20,

    # 登录防暴力破解
    "login_attempts_per_ip_per_minute": 10,
}
```

### 6.5 审计日志

所有敏感操作均记录审计日志：

```python
# 审计事件类型
AUDIT_EVENTS = [
    "user.login",
    "user.register",
    "key.create",
    "key.rotate",
    "key.delete",
    "key.decrypt",         # 解密操作 (高危)
    "pool.create",
    "pool.add_member",
    "pool.remove_member",
    "proxy.call",          # 代理调用
    "proxy.key_exhausted", # 密钥池耗尽
]

# 审计日志结构
{
    "event": "key.decrypt",
    "user_id": 1,
    "resource": "google-geocoding-prod-1",
    "ip": "192.168.1.100",
    "timestamp": "2026-04-09T12:00:00Z",
    "details": {"pool": "google-geocoding", "reason": "proxy_call"}
}
```

---

## 7. 前端设计

### 7.1 页面结构

```
┌─────────────────────────────────────────────────────────┐
│  apipool 管理平台                        [用户名] [退出] │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│  📊 概览  │  ┌──────────────────────────────────────┐   │
│          │  │  今日调用统计                          │   │
│  🔑 Key  │  │  ┌───────┐ ┌───────┐ ┌───────┐      │   │
│   管理    │  │  │ 成功   │ │ 失败   │ │ 达限   │      │   │
│          │  │  │ 1,250 │ │   12  │ │    3   │      │   │
│  📦 密钥池│  │  └───────┘ └───────┘ └───────┘      │   │
│   管理    │  │                                      │   │
│          │  │  [调用趋势图 - ECharts]                │   │
│  📈 统计  │  │                                      │   │
│          │  └──────────────────────────────────────┘   │
│  ⚙️ 设置  │                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

### 7.2 Key 管理页面

```
┌──────────────────────────────────────────────────────────┐
│  API Key 管理                              [+ 新增 Key]   │
├──────────────────────────────────────────────────────────┤
│  筛选: [客户端类型 ▼] [状态 ▼] [标签 ▼]  🔍 搜索...      │
├──────────────────────────────────────────────────────────┤
│  标识符            │ 别名      │ 类型      │ 状态 │ 操作 │
│  ─────────────────┼──────────┼──────────┼─────┼────── │
│  google-geo-prod-1│ 生产Key1  │ googlemaps│ ✅  │ ⋮    │
│  google-geo-prod-2│ 生产Key2  │ googlemaps│ ⚠️  │ ⋮    │
│  openai-main      │ OpenAI主  │ openai    │ ✅  │ ⋮    │
└──────────────────────────────────────────────────────────┘

操作菜单 ⋮:
  ├── 编辑元数据 (别名/标签/描述)
  ├── 验证可用性
  ├── 轮换密钥
  └── 删除 (归档)

注意: 任何界面都不展示、不允许查看 Key 明文
```

### 7.3 新增 Key 表单

```
┌──────────────────────────────────────────────────────────┐
│  新增 API Key                                            │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  标识符 (必填)   [________________________]               │
│  ⚠️ 全局唯一，创建后不可修改。建议格式: 服务-环境-序号      │
│                                                          │
│  别名 (选填)     [________________________]               │
│                                                          │
│  客户端类型 (必填) [▼ 选择类型          ]                  │
│    - googlemaps                                          │
│    - openai                                              │
│    - custom                                              │
│                                                          │
│  API Key (必填)  [________________________]               │
│  ⚠️ 明文仅此一次传输，存储后不可查看                        │
│                                                          │
│  客户端配置 (JSON) [                        ]              │
│  例: {"timeout": 30, "base_url": "..."}                  │
│                                                          │
│  标签            [production] [geocoding] [+ 添加]        │
│                                                          │
│  描述            [________________________]               │
│                                                          │
│                    [取消]  [创建]                          │
└──────────────────────────────────────────────────────────┘
```

### 7.4 密钥池管理页面

```
┌──────────────────────────────────────────────────────────┐
│  密钥池管理                              [+ 新建密钥池]    │
├──────────────────────────────────────────────────────────┤
│  标识符          │ 名称           │ 可用 │ 总计 │ 策略    │
│  ───────────────┼───────────────┼─────┼─────┼────────  │
│  google-geocoding│ Google地理编码 │  2  │  3  │ 随机     │
│  openai-chat    │ OpenAI对话     │  1  │  1  │ 最少使用  │
└──────────────────────────────────────────────────────────┘

点击池名称 → 详情页:
┌──────────────────────────────────────────────────────────┐
│  密钥池: google-geocoding                                │
├──────────────────────────────────────────────────────────┤
│  [+ 添加Key]                                             │
│                                                          │
│  Key标识符          │ 别名    │ 状态 │ 优先级 │ 权重 │ 操作│
│  ──────────────────┼────────┼─────┼───────┼─────┼───── │
│  google-geo-prod-1 │ Key1   │ ✅  │   0   │  1  │ 移除 │
│  google-geo-prod-2 │ Key2   │ ⚠️  │   0   │  1  │ 移除 │
│  google-geo-backup │ 备份Key │ 🔴  │  -1   │  1  │ 移除 │
└──────────────────────────────────────────────────────────┘
```

---

## 8. 部署方案

### 8.1 Docker Compose 部署

```yaml
# docker-compose.yml

version: "3.9"

services:
  # PostgreSQL 数据库
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: apipool
      POSTGRES_USER: apipool
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U apipool"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis 缓存
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redisdata:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # apipool Web 服务
  api:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql://apipool:${DB_PASSWORD}@db:5432/apipool
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      APIPOOL_ENCRYPTION_KEY: ${ENCRYPTION_KEY}
      JWT_SECRET_KEY: ${JWT_SECRET}
      APIPOOL_ADMIN_USERNAME: ${ADMIN_USERNAME}
      APIPOOL_ADMIN_PASSWORD: ${ADMIN_PASSWORD}
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./apipool_server:/app/apipool_server

  # Celery Worker (异步任务)
  worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: celery -A apipool_server.tasks worker -l info
    environment:
      DATABASE_URL: postgresql://apipool:${DB_PASSWORD}@db:5432/apipool
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      APIPOOL_ENCRYPTION_KEY: ${ENCRYPTION_KEY}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  # Celery Beat (定时任务)
  beat:
    build:
      context: .
      dockerfile: Dockerfile
    command: celery -A apipool_server.tasks beat -l info
    environment:
      DATABASE_URL: postgresql://apipool:${DB_PASSWORD}@db:5432/apipool
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      APIPOOL_ENCRYPTION_KEY: ${ENCRYPTION_KEY}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

volumes:
  pgdata:
  redisdata:
```

### 8.2 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# 复制源码
COPY apipool/ ./apipool/
COPY apipool_server/ ./apipool_server/
COPY apipool_web/dist/ ./static/

# 数据库迁移
COPY migrations/ ./migrations/
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "apipool_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.3 服务端依赖

```
# requirements-server.txt

# 现有核心库
sqlalchemy>=1.0.0

# Web 框架
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6

# 数据库
psycopg2-binary>=2.9.9
alembic>=1.12.0

# Redis
redis>=5.0.0

# 认证
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4

# 加密
cryptography>=41.0.0

# 数据验证
pydantic>=2.5.0
pydantic-settings>=2.1.0

# HTTP 客户端 (SDK)
httpx>=0.25.0

# 异步任务
celery>=5.3.0

# 其他
python-dotenv>=1.0.0
```

### 8.4 环境变量

```bash
# .env.example

# 数据库
DATABASE_URL=postgresql://apipool:password@localhost:5432/apipool
DB_PASSWORD=changeme

# Redis
REDIS_URL=redis://:password@localhost:6379/0
REDIS_PASSWORD=changeme

# 加密 (生成: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
APIPOOL_ENCRYPTION_KEY=your-fernet-key-here

# JWT
JWT_SECRET_KEY=your-jwt-secret-here
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# 管理员初始账号
APIPOOL_ADMIN_USERNAME=admin
APIPOOL_ADMIN_PASSWORD=changeme

# 服务配置
APIPOOL_HOST=0.0.0.0
APIPOOL_PORT=8000
APIPOOL_DEBUG=false
APIPOOL_CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

---

## 9. 实施路线图

### Phase 1: 后端核心 (2 周)

| 序号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 1.1 | 项目脚手架搭建 | P0 | FastAPI 应用结构、配置管理、数据库连接 |
| 1.2 | 数据模型与迁移 | P0 | User / ApiKeyEntry / KeyPool / PoolMember 模型，Alembic 迁移 |
| 1.3 | 认证模块 | P0 | 注册/登录/JWT 签发/中间件 |
| 1.4 | Key 加密存储 | P0 | Fernet 加密/解密/密钥轮换 |
| 1.5 | Key CRUD 接口 | P0 | 创建/查询/更新/删除/批量导入 |
| 1.6 | 客户端类型注册表 | P0 | `ClientRegistry` + 内置类型 |
| 1.7 | 池管理接口 | P0 | 池 CRUD / 成员管理 |

### Phase 2: 代理调用引擎 (1.5 周)

| 序号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 2.1 | 标识符映射服务 | P0 | `PoolService.build_manager()` |
| 2.2 | 代理调用接口 | P0 | `/proxy/{pool}/invoke` |
| 2.3 | 统计数据持久化 | P1 | 从 SQLite 内存库迁移到 PostgreSQL |
| 2.4 | 限流中间件 | P1 | 基于Redis的滑动窗口限流 |
| 2.5 | 审计日志 | P1 | 敏感操作记录 |

### Phase 3: SDK 与客户端 (1 周)

| 序号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 3.1 | SDK 客户端模块 | P0 | `ServiceApiKey` / `ServiceClient` / `_ServiceChainLink` |
| 3.2 | `connect()` 便捷函数 | P0 | 一行代码连接服务 |
| 3.3 | SDK 单元测试 | P0 | 完整调用链路测试 |
| 3.4 | SDK 文档 | P1 | 使用示例与迁移指南 |

### Phase 4: 前端界面 (2 周)

| 序号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 4.1 | 前端脚手架 | P0 | Vue 3 + Vite + TDesign Vue |
| 4.2 | 登录/注册页 | P0 | JWT Token 管理 |
| 4.3 | Key 管理页 | P0 | 列表/新增/编辑/删除/验证 |
| 4.4 | 密钥池管理页 | P0 | 池列表/详情/成员管理 |
| 4.5 | 统计面板 | P1 | ECharts 图表 |
| 4.6 | 系统设置页 | P2 | 用户管理 (admin) |

### Phase 5: 部署与测试 (1 周)

| 序号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 5.1 | Docker 化 | P0 | Dockerfile + docker-compose.yml |
| 5.2 | CI/CD 流水线 | P1 | GitHub Actions: 测试/构建/推送镜像 |
| 5.3 | 集成测试 | P0 | 端到端测试：注册→建池→调用→统计 |
| 5.4 | 安全测试 | P0 | 渗透测试、Key 泄露检查 |
| 5.5 | 文档完善 | P1 | API 文档、部署文档、用户手册 |

---

## 10. 迁移指南

### 10.1 现有代码迁移

从纯库模式迁移到 Web 服务模式，调用方代码变更极小：

**迁移前**:
```python
from apipool import ApiKey, ApiKeyManager

class MyKey(ApiKey):
    def get_primary_key(self): return "sk-xxx"
    def create_client(self): return Client("sk-xxx")
    def test_usability(self, client): return True

manager = ApiKeyManager([MyKey()])
result = manager.dummyclient.geocode("address")
```

**迁移后**:
```python
from apipool import connect

manager = connect(
    service_url="http://apipool.internal:8000",
    pool_identifier="google-geocoding",
    auth_token=os.environ["APIPOOL_TOKEN"]
)
result = manager.dummyclient.geocode("address")
# 业务逻辑完全不变，ChainProxy / 轮换 / 统计全部生效
```

### 10.2 配置管理迁移

| 原方式 | 新方式 |
|--------|--------|
| 代码中硬编码 Key | Web 界面录入 Key |
| 配置文件存储 Key | 数据库加密存储 Key |
| 环境变量传递 Key | 仅传递标识符和 JWT Token |
| 手动维护 Key 列表 | Web 界面动态增删 |

### 10.3 向后兼容

纯库模式继续可用，不影响现有用户：

```python
# 纯库模式 — 无需任何改动，继续工作
from apipool import ApiKey, ApiKeyManager

manager = ApiKeyManager([MyKey()])
result = manager.dummyclient.geocode("address")

# Web 模式 — 可选升级
from apipool import connect

manager = connect(url, pool_id, token)
result = manager.dummyclient.geocode("address")
```

---

## 附录 A: 错误码定义

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| `AUTH_001` | 401 | Token 无效或已过期 |
| `AUTH_002` | 403 | 权限不足 |
| `AUTH_003` | 429 | 登录尝试过于频繁 |
| `KEY_001` | 404 | Key 标识符不存在 |
| `KEY_002` | 409 | Key 标识符已存在 |
| `KEY_003` | 400 | Key 明文格式无效 |
| `KEY_004` | 410 | Key 已归档 |
| `POOL_001` | 404 | 密钥池标识符不存在 |
| `POOL_002` | 409 | 密钥池标识符已存在 |
| `POOL_003` | 503 | 密钥池已耗尽 (所有 Key 不可用) |
| `PROXY_001` | 400 | method_chain 格式无效 |
| `PROXY_002` | 500 | 上游 API 调用失败 |
| `PROXY_003` | 502 | 上游 API 达到限流阈值 |
| `REGISTRY_001` | 400 | 未知的 client_type |

---

## 附录 B: 标识符命名规范

标识符 (`identifier`) 是整个系统最核心的引用标识，需遵循以下规范：

| 规则 | 说明 | 示例 |
|------|------|------|
| 格式 | 小写字母 + 数字 + 连字符 | `google-geocoding-prod-1` |
| 长度 | 3 ~ 128 字符 | — |
| 全局唯一 | 跨用户全局唯一 | 系统自动检查 |
| 语义化 | 包含服务名 + 环境 + 序号 | `openai-chat-prod-2` |
| 不可变 | 创建后不可修改 | — |

**推荐命名模板**:

```
{service_name}-{environment}-{sequence_number}

示例:
  google-geocoding-prod-1
  google-geocoding-prod-2
  google-geocoding-staging-1
  openai-chat-prod-1
  coingecko-market-prod-1
```

**密钥池标识符**（调用方使用）：

```
{service_name}-{feature}

示例:
  google-geocoding     (包含多个 google-geocoding-prod-* Key)
  openai-chat          (包含多个 openai-chat-prod-* Key)
  coingecko-market     (包含多个 coingecko-market-prod-* Key)
```
