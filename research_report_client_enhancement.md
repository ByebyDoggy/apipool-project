# Apipool 客户端功能强化 — 综合研究报告

## Executive Summary

apipool 客端端（`apipool/` 包，v1.0.9）已具备完整的 Key 轮换、批量执行、动态刷新和服务端代理能力。但在生产级可用性方面存在 **6 个 P0 级缺陷**（资源泄漏、Token 管理、线程安全）、**8 个 P1 级改进机会**（断路器、可观测性、代码去重）和 **6 个 P2 级优化方向**。本报告按优先级给出具体实施方案。

---

## 一、P0 级 — 必须立即修复的缺陷

### P0-1: Token 自动刷新机制缺失

**问题描述**: `client.py` 的 `login()` 只返回一次性 token，无自动刷新逻辑。access_token 过期后所有请求 401，用户需手动重新 login。

**影响范围**: `client.py` 全部 Server SDK 函数（connect, get_keys, get_config 及其 async 版本）

**方案概述**:
在 `client.py` 中引入 `ApipoolSession` 会话管理类：

```python
class ApipoolSession:
    """Managed session with auto token refresh."""
    
    def __init__(self, service_url, username, password):
        self._service_url = service_url.rstrip("/")
        self._username = username
        self._password = password
        self._access_token = None
        self._refresh_token = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()
        self._http = httpx.Client(base_url=self._service_url, timeout=30.0)
    
    def ensure_auth(self) -> str:
        """Return valid access_token, refreshing if needed."""
        with self._lock:
            if time.monotonic() > self._token_expires_at - 30:  # 30s early refresh
                self._do_refresh()
            return self._access_token
    
    def _do_refresh(self):
        if self._refresh_token:
            try:
                resp = self._http.post("/api/v1/auth/refresh", json={
                    "refresh_token": self._refresh_token
                })
                data = resp.json()
                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                self._token_expires_at = time.monotonic() + data.get("expires_in", 900)
                return
            except Exception:
                pass  # Fall through to re-login
        # Full re-authentication
        resp = self._http.post("/api/v1/auth/login", json={
            "username": self._username,
            "password": self._password,
        })
        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._token_expires_at = time.monotonic() + data.get("expires_in", 900)
    
    def close(self):
        self._http.close()
    
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

# Async version
class AsyncApipoolSession:
    """Async managed session with auto token refresh."""
    # ... same pattern with httpx.AsyncClient + asyncio.Lock
```

**涉及文件**: `client.py`
**优先级**: P0
**工作量**: ~150 行

---

### P0-2: HTTP Client 资源泄漏

**问题描述**: 
- `ServiceApiKey.create_client()` 每次调用创建新 `_ServiceClient`（含新的 `httpx.Client`），但从未 close
- `AsyncServiceApiKey.create_client()` 同理，`httpx.AsyncClient` 从未 aclose
- `DynamicKeyManager._do_refresh()` 中每次 refresh 为每个 key 调用 `apikey.connect_client()` 创建客户端，旧客户端不释放

**当前代码证据** (`client.py:130-136`):
```python
def create_client(self):
    return _ServiceClient(   # 新建 httpx.Client，无生命周期管理
        base_url=self._service_url,
        pool_identifier=self._pool_identifier,
        auth_token=self._auth_token,
    )
```

**方案概述**:
1. 在 `ApiKey` 基类中添加 `close_client()` 抽象方法
2. 在 `_ServiceClient` / `_AsyncServiceClient` 中实现 `close()` 关闭底层 httpx 连接
3. 在 `DynamicKeyManager._do_refresh()` 的 remove 分支中调用 `old_apikey.close_client()`

```python
# apipool/apikey.py 补充
class ApiKey:
    def close_client(self):
        """Release client resources. Override in subclasses."""
        pass

# client.py 修复
class _ServiceClient:
    def close(self):
        self._http.close()

class ServiceApiKey(ApiKey):
    def close_client(self):
        if hasattr(self, '_client') and self._client is not None:
            self._client.close()
```

**涉及文件**: `apikey.py`, `client.py`, `manager.py`
**优先级**: P0
**工作量**: ~40 行

---

### P0-3: ApiKeyManager 线程安全缺陷

**问题描述**: 
- `ApiKeyManager.random_one()` 无锁保护，并发调用时 `random.choice(list(...))` 可能与 `remove_one()` / `add_one()` 产生竞态条件
- `batch_exec` 使用 `ThreadPoolExecutor` 并发调用 `self._resolve_method(apikey)` 和 `self.remove_one()`，但基类方法均无线程安全保证

**当前代码证据** (`manager.py:239-245`):
```python
def random_one(self):
    if len(self.apikey_chain) == 0:  # ← 非原子操作
        raise PoolExhaustedError(...)
    return random.choice(list(self.apikey_chain.values()))  # ← 快照可能与实际不一致
```

**方案概述**: 
为 `ApiKeyManager` 添加可选锁（与 `DynamicKeyManager` 已有的 RLock 对齐）：

```python
class ApiKeyManager:
    def __init__(self, ...):
        ...
        self._lock = threading.RLock()  # 所有公共方法加锁
    
    def random_one(self):
        with self._lock:
            if len(self.apikey_chain) == 0:
                raise PoolExhaustedError(...)
            return random.choice(list(self.apikey_chain.values()))
    
    def add_one(self, apikey, upsert=False):
        with self._lock:
            self._add_one_unlocked(apikey, upsert)
    
    def remove_one(self, primary_key):
        with self._lock:
            return self._remove_one_unlocked(primary_key)
```

注意：`DynamicKeyManager` 已经有自己的 `_lock` 并覆写了这些方法，此改动需确保兼容。

**涉及文件**: `manager.py`
**优先级**: P0
**工作量**: ~50 行修改

---

### P0-4: StatsCollector SQLite 线程安全问题

**问题描述**: 
- `create_sqlite()` 默认创建 `"sqlite:///:memory:"` 引擎，未设置 `check_same_thread=False`
- `batch_exec` 使用 `ThreadPoolExecutor` 多线程写入 stats，触发 SQLite 线程限制错误
- 当前已有 try/except 吞掉错误（`_safe_stats`），但这掩盖了数据丢失

**当前代码证据** (`manager.py:880-881`):
```python
def create_sqlite():
    return create_engine("sqlite:///:memory:")  # 缺少 connect_args
```

**方案概述**:
```python
def create_sqlite():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},  # 允许多线程访问
        pool_size=5,
        max_overflow=10,
    )
```

同时建议增加 `echo=False` 参数避免日志噪声。

**涉及文件**: `manager.py`
**优先级**: P0
**工作量**: 3 行

---

### P0-5: 异步链式代理死代码

**问题描述**: 
`AsyncChainProxy.__call__` 方法中有两处连续的 `return await AsyncApiCaller(...)` 调用（第1056行和1063行），第一处 return 后第二处永远不会执行。

**当前代码证据** (`manager.py:1050-1068`):
```python
async def __call__(self, *args, **kwargs):
    # ... resolve target ...
    try:
        target._attr_path = self._attr_path
    except AttributeError:
        pass
    
    return await AsyncApiCaller(      # ← 第一处 return
        apikey=apikey, apikey_manager=self._manager,
        call_method=target, reach_limit_exc=self._reach_limit_exc,
    )(*args, **kwargs)

    return await AsyncApiCaller(      # ← 死代码！永远不可达
        apikey=apikey, ...
    )(*args, **kwargs)
```

**方案概述**: 删除重复的第二段代码块。

**涉及文件**: `manager.py:1063-1068`
**优先级**: P0
**工作量**: 删除 6 行

---

### P0-6: 服务端代理模式超时不跟随配置

**问题描述**:
`_ServiceClient.__init__` 将 timeout 写死为 30 秒，而 `PoolConfig.timeout` 可能是其他值。

**当前代码证据** (`client.py:151-155`):
```python
def __init__(self, base_url, pool_identifier, auth_token):
    self._http = httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,  # ← 硬编码
    )
```

**方案概述**:
将 timeout 参数化，由 `ServiceApiKey` 从外部传入或延迟从 manager.config 获取：
```python
class ServiceApiKey(ApiKey):
    def __init__(self, ..., timeout=30.0):
        self._timeout = timeout
    
    def create_client(self):
        return _ServiceClient(
            ..., timeout=self._timeout,
        )
```

**涉及文件**: `client.py`
**优先级**: P0
**工作量**: ~15 行

---

## 二、P1 级 — 强烈建议实施的改进

### P1-1: 断路器 CircuitBreaker 模式

**问题描述**: 当服务端不可达或持续报错时，客户端仍会反复尝试，浪费时间和资源。

**方案概述**:
```python
from enum import Enum
import time

class CircuitState(Enum):
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 断开，快速失败
    HALF_OPEN = "half_open" # 半开，允许探测

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold=5,     # 连续 N 次失败后断开
        recovery_timeout=30.0,   # 断开 N 秒后进入半开
        half_open_max_calls=3,   # 半开状态允许的最大探测数
    ):
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._lock = threading.Lock()
    
    def can_execute(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            elif self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    return True
                return False
            else:  # HALF_OPEN
                return self._success_count < self._half_open_max_calls
    
    def record_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
    
    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
            elif self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
```

集成到 `_ServiceClient._request()` 和 `ChainProxy.__call__()` 中。

**涉及文件**: 新建 `circuit_breaker.py`, 修改 `client.py`, `manager.py`
**优先级**: P1
**工作量**: ~120 行

---

### P1-2: 可插拔重试策略

**问题描述**: 
当前 `batch_exec` 只有简单的 "retry on another key + ban" 策略，不支持指数退避、抖动等高级策略。`AsyncApiCaller` 有 null-retry 但策略写死在类内部。

**方案概述**:
```python
from abc import ABC, abstractmethod
import random
import math

class RetryStrategy(ABC):
    @abstractmethod
    def should_retry(self, attempt, max_attempts, error) -> bool: ...
    
    @abstractmethod
    def get_delay(self, attempt) -> float: ...

class FixedDelayRetry(RetryStrategy):
    def __init__(self, delay=1.0):
        self._delay = delay
    def should_retry(self, attempt, max_attempts, error): return attempt < max_attempts
    def get_delay(self, attempt): return self._delay

class ExponentialBackoffRetry(RetryStrategy):
    def __init__(self, base_delay=1.0, max_delay=60.0, jitter=True):
        self._base = base_delay
        self._max = max_delay
        self._jitter = jitter
    def should_retry(self, attempt, max_attempts, error): return attempt < max_attempts
    def get_delay(self, attempt):
        delay = min(self._base * (2 ** attempt), self._max)
        if self._jitter:
            delay *= (0.5 + random.random())
        return delay
```

**涉及文件**: 新建 `retry.py`, 修改 `manager.py`
**优先级**: P1
**工作量**: ~80 行

---

### P1-3: 结构化日志替代 sys.stdout.write

**问题描述**: 
代码中散布着多处 `sys.stdout.write(...)` 输出（如 `check_usable()`），无法控制日志级别、格式或输出目标。

**位置清单**:
- `manager.py:223-225`: add_one 失败
- `manager.py:258-264`: check_usable 结果输出

**方案概述**:
```python
import logging
logger = logging.getLogger("apipool.manager")

# 替换所有 sys.stdout.write(...) 为对应级别的 logger 调用
# check_usable 中:
def check_usable(self):
    for primary_key, apikey in self.apikey_chain.items():
        if apikey.is_usable():
            self.stats.add_event(primary_key, StatusCollection.c1_Success.id)
        else:
            self.remove_one(primary_key)
            self.stats.add_event(primary_key, StatusCollection.c5_Failed.id)
    
    active = len(self.apikey_chain)
    archived = len(self.archived_apikey_chain)
    if active == 0:
        logger.warning("No API keys are usable! %d keys in archive.", archived)
    elif archived == 0:
        logger.info("All %d API keys are usable.", active)
    else:
        logger.info(
            "%d usable, %d archived. Archived keys: %s",
            active, archived, list(self.archived_apikey_chain.keys()),
        )
```

**涉及文件**: `manager.py`
**优先级**: P1
**工作量**: ~20 行替换

---

### P1-4: 统一异常层级体系

**问题描述**: 
异常处理混乱：有些抛出 `RuntimeError("Proxy call failed")`，有些直接 re-raise 原始异常，`PoolExhaustedError` 只在一处使用。调用者难以区分不同类型的错误。

**方案概述**:
```python
# exceptions.py (新建)
class ApipoolError(Exception):
    """Base exception for all apipool errors."""

class ConnectionError(ApipoolError):
    """Network or server unreachable."""

class AuthenticationError(ApipoolError):
    """Token expired, invalid credentials, or auth failure."""

class RateLimitError(ApipoolError):
    """API rate limit exceeded (key-level)."""

class PoolExhaustedError(ApipoolError):
    """All keys in pool are exhausted or banned."""
    # 已有，移至此模块

class ProxyCallError(ApipoolError):
    """Server-side proxy execution failed."""
    def __init__(self, message, attr_path=None, original_error=None):
        super().__init__(message)
        self.attr_path = attr_path
        self.original_error = original_error

class ConfigSyncError(ApipoolError):
    """Failed to sync configuration from server."""

class KeyValidationError(ApipoolError):
    """API key failed validation or usability test."""
```

**涉及文件**: 新建 `exceptions.py`, 修改 `client.py`, `manager.py`, `__init__.py`
**优先级**: P1
**工作量**: ~80 行 + 全局替换

---

### P1-5: Context Manager 支持

**问题描述**: 
`ApiKeyManager`、`DynamicKeyManager`、以及 `connect()` 返回的对象都不支持上下文管理协议，用户必须手动记住关闭资源。

**方案概述**:
```python
class ApiKeyManager:
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()  # 或 close()
        return False

class DynamicKeyManager(ApiKeyManager):
    def shutdown(self):
        super().shutdown()
        # 额外关闭所有 key 的 client
        for apikey in list(self.apikey_chain.values()):
            apikey.close_client()
        for apikey in list(self.archived_apikey_chain.values()):
            apikey.close_client()

class AsyncDynamicKeyManager(ApiKeyManager):
    async def aexit__(self, exc_type, exc_val, exc_tb):
        await self.ashutdown()
        return False

# client.py 中也支持 context manager
def connect(...) -> ApiKeyManager:
    # ... existing code ...

async def aconnect(...) -> ApiKeyManager:
    # ... existing code ...
```

用法变为：
```python
# 之前
manager = DynamicKeyManager(...)
try:
    result = manager.dummyclient.ping()
finally:
    manager.shutdown()

# 之后
with DynamicKeyManager(...) as manager:
    result = manager.dummyclient.ping()

# async
async with AsyncDynamicKeyManager(...) as manager:
    result = await manager.adummyclient.ping()
```

**涉及文件**: `manager.py`, `client.py`
**优先级**: P1
**工作量**: ~40 行

---

### P1-6: 请求/响应拦截钩子（Middleware）

**问题描述**: 
用户无法在 API 调用前后插入自定义逻辑（如请求日志、指标采集、请求签名修改等）。

**方案概述**:
```python
from dataclasses import dataclass
from typing import Optional, Callable, Any
import time

@dataclass
class CallContext:
    """Context passed through the call chain."""
    attr_path: tuple[str, ...]
    args: tuple
    kwargs: dict
    apikey_primary_key: str
    start_time: float = 0.0
    end_time: float = 0.0
    result: Any = None
    error: Optional[Exception] = None

class Middleware:
    """Base class for call middleware/hooks."""
    
    def before_call(self, ctx: CallContext) -> None:
        """Called before executing the actual method."""
        pass
    
    def after_call(self, ctx: CallContext) -> Any:
        """Called after the method returns. Can modify result."""
        pass
    
    def on_error(self, ctx: CallContext) -> None:
        """Called when an exception occurs."""
        pass

# 示例：计时中间件
class TimingMiddleware(Middleware):
    def before_call(self, ctx):
        ctx.start_time = time.monotonic()
    
    def after_call(self, ctx):
        ctx.end_time = time.monotonic()
        logger.debug(
            "Call %s took %.3fs (key=%s)",
            ".".join(ctx.attr_path),
            ctx.end_time - ctx.start_time,
            ctx.apikey_primary_key,
        )

# 集成到 ApiCaller / AsyncApiCaller
class ApiCaller:
    def __call__(self, *args, **kwargs):
        ctx = CallContext(
            attr_path=tuple(self._attr_path),  # 需要传入
            args=args, kwargs=kwargs,
            apikey_primary_key=self.apikey.primary_key,
        )
        for mw in self._middlewares:
            mw.before_call(ctx)
        try:
            res = self.call_method(*args, **kwargs)
            ctx.result = res
            for mw in reversed(self._middlewares):
                mw.after_call(ctx)
            return res
        except Exception as e:
            ctx.error = e
            for mw in reversed(self._middlewares):
                mw.on_error(ctx)
            raise
```

**涉及文件**: 新建 `middleware.py`, 修改 `manager.py`
**优先级**: P1
**工作量**: ~100 行

---

### P1-7: batch_exec 流式结果支持

**问题描述**: 
`batch_exec` 必须等待全部任务完成后才返回 `BatchResult`，对于万级任务无法逐步获取结果。

**方案概述**:
添加 `batch_exec_iter` 生成器版本：
```python
from queue import Queue
import threading

def batch_exec_iter(
    self,
    method_name: str,
    items: List[Tuple[Any, tuple, dict]],
    **kwargs,
) -> Iterator[Tuple[Any, Any]]:
    """Yield (item_id, result) pairs as they complete.
    
    Raises: PoolExhaustedError when all keys are exhausted.
    """
    # 使用 Queue 作为结果通道
    result_q = Queue()
    error_event = threading.Event()
    
    def _worker(item_id, args, kw):
        try:
            result = self._execute_single_item(method_name, item_id, args, kw, **kwargs)
            result_q.put((item_id, result))
        except Exception as e:
            result_q.put((item_id, e))
    
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = [pool.submit(_worker, iid, a, k) for iid, a, k in items]
        completed = 0
        while completed < len(items):
            item_id, value = result_q.get()
            completed += 1
            if isinstance(value, Exception):
                raise value
            yield item_id, value
```

**涉及文件**: `manager.py`
**优先级**: P1
**工作量**: ~70 行

---

### P1-8: manager.py 模块拆分

**问题描述**: 
单个文件 1644 行包含 10+ 个类，维护困难。

**拆分方案**:

| 新文件 | 迁移的类 | 行数估算 |
|--------|---------|---------|
| `core.py` | ApiKeyManager, DummyClient, ApiCaller, PoolExhaustedError, NeverRaisesError, BatchResult | ~500 |
| `chain_proxy.py` | ChainProxy, AsyncChainProxy, AsyncApiCaller, AsyncDummyClient, AsyncDummyClient | ~300 |
| `batch.py` | `ApiKeyManager.batch_exec` 和 `abatch_exec` 方法（作为 mixin） | ~400 |
| `dynamic.py` | DynamicKeyManager, AsyncDynamicKeyManager | ~350 |
| `__init__.py` | 重导出所有公开符号 | ~30 |

保持向后兼容：`from apipool.manager import ApiKeyManager` 仍然有效（通过 `__init__.py` re-export）。

**涉及文件**: `core.py`, `chain_proxy.py`, `batch.py`, `dynamic.py` (新建); `manager.py` (保留为 re-export)
**优先级**: P1
**工作量**: 大型重构，建议单独 PR

---

## 三、P2 级 — 推荐的未来优化

### P2-1: 同步/异步代码去重（Protocol 适配层）

**问题**: ChainProxy vs AsyncChainProxy 约 70% 逻辑重复。

**方向**: 定义 `ChainProxyProtocol(Protocol)`，同步版直接实现，异步版通过适配器包装：
```python
class AsyncChainWrapper:
    """Wraps synchronous chain logic with async bridge."""
    def __init__(self, sync_proxy: ChainProxy): ...
    async def __call__(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: sync_proxy(*args, **kwargs))
```

注意：这适用于 I/O-bound 场景；CPU-bound 场景仍需要原生 async 实现。评估后决定是否值得引入复杂度。

---

### P2-2: Key 选择策略可插拔化

**当前**: 仅 `random.choice`（随机选择）

**扩展选项**:
- `RoundRobinStrategy` — 轮询分配
- `LeastRecentlyUsedStrategy` — 最久未使用优先
- `WeightedRandomStrategy` — 加权随机（权重来自健康评分）
- `AdaptiveStrategy` — 根据历史延迟/成功率动态调整

接口设计：
```python
class SelectionStrategy(ABC):
    @abstractmethod
    def select(self, available_keys: List[ApiKey]) -> Optional[ApiKey]: ...
```

---

### P2-3: Pydantic v2 配置管理

**方向**: 将 `PoolConfig` 改为继承 `pydantic.BaseModel`，获得：
- 自动校验
- JSON schema 生成
- `.env` 文件支持（配合 pydantic-settings）
- 序列化/反序列化零成本

```python
from pydantic import BaseModel, Field

class PoolConfig(BaseModel):
    concurrency: int = 0
    timeout: float = Field(default=30.0, gt=0)
    rate_limit: int = Field(default=0, ge=0)
    # ...
    
    model_config = {"extra": "forbid"}  # 拒绝未知字段
```

风险：引入 pydantic 作为核心依赖可能过重（对仅使用 library mode 的用户）。建议做成 optional dependency。

---

### P2-4: OpenTelemetry 集成

**方向**: 通过 Middleware 机制集成 OTel tracing：
```python
class OpenTelemetryMiddleware(Middleware):
    def before_call(self, ctx):
        tracer = trace.get_tracer(__name__)
        span = tracer.start_span(".".join(ctx.attr_path))
        ctx._otel_span = span
        span.set_attribute("apipool.key", ctx.apikey_primary_key)
    
    def after_call(self, ctx):
        if hasattr(ctx, '_otel_span'):
            ctx._otel_span.end()
    
    def on_error(self, ctx):
        if hasattr(ctx, '_otel_span'):
            ctx._otel_span.set_status(Status(StatusCode.ERROR))
            ctx._otel_span.end()
```

---

### P2-5: 进度回调系统

**方向**: 为长时间运行的 batch 操作提供进度通知：
```python
@dataclass  
class BatchProgress:
    total: int
    completed: int
    succeeded: int
    failed: int
    elapsed: float

# 用法
def on_progress(p: BatchProgress):
    print(f"[{p.completed}/{p.total}] {p.success_rate:.1%} done")

result = manager.batch_exec(
    method_name="...", items=items,
    on_progress=on_progress,
)
```

---

### P2-6: .pyi Stub 文件生成

**问题**: ChainProxy 的 `__getattr__` 拦截导致 IDE 无法推断可用属性。

**方向**: 提供 `.pyi` stub 文件让 IDE 可以做类型检查和补全：
```python
# stubs/apipool.pyi
class DummyClient:
    @property
    def _apikey_manager(self) -> ApiKeyManager: ...
    def __getattr__(self, name: str) -> ChainProxy: ...

class ChainProxy:
    def __getattr__(self, name: str) -> ChainProxy: ...
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
```

或者更进一步，研究是否可以为特定目标 SDK（如 CoinGecko, OpenAI）生成类型安全的 stub。

---

## 四、实施路线图

### Phase 1 — 稳定性与正确性（1-2 天）

| 任务 | 优先级 | 文件 | 工作量 |
|------|--------|------|--------|
| 删除 AsyncChainProxy 死代码 | P0 | manager.py | 5 min |
| 修复 SQLite 线程安全参数 | P0 | manager.py | 5 min |
| 替换 sys.stdout.write 为 logger | P1 | manager.py | 20 min |
| 统一异常层级体系 | P1 | 新建 exceptions.py | 2 hr |

### Phase 2 — 资源管理与认证（2-3 天）

| 任务 | 优先级 | 文件 | 工作量 |
|------|--------|------|--------|
| HTTP Client 资源释放机制 | P0 | apikey.py, client.py | 2 hr |
| ApiKeyManager 基础线程安全 | P0 | manager.py | 2 hr |
| ApipoolSession Token 自动刷新 | P0 | client.py | 4 hr |
| 服务端超时可配置化 | P0 | client.py | 30 min |
| Context Manager 支持 | P1 | manager.py, client.py | 1 hr |

### Phase 3 — 弹性与可观测性（3-4 天）

| 任务 | 优先级 | 文件 | 工作量 |
|------|--------|------|--------|
| CircuitBreaker 断路器 | P1 | circuit_breaker.py (新) | 3 hr |
| 可插拔重试策略 | P1 | retry.py (新) | 2 hr |
| Middleware/Hook 系统 | P1 | middleware.py (新) | 4 hr |
| batch_exec 流式结果 | P1 | manager.py | 1.5 hr |

### Phase 4 — 架构优化（后续迭代）

| 任务 | 优先级 | 工作量 |
|------|--------|--------|
| manager.py 模块拆分 | P1 | 1-2 天 |
| Sync/Async 去重 | P2 | 2-3 天 |
| Key 选择策略可插拔 | P2 | 1 天 |
| Pydantic v2 配置 | P2 | 1 天 |
| OTel 集成 | P2 | 1 天 |
| .pyi Stub 生成 | P2 | 2-3 天 |

---

## 五、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 线程安全改动破坏 DynamicKeyManager | 高 | 先跑完现有测试套件，再添加并发测试 |
| 异常层级重构改变 public API | 中 | 保留旧异常名作为 alias，deprecation cycle |
| Session 类改变 connect() 返回值签名 | 中 | 保持 connect() 返回 ApiKeyManager 不变；session 作为可选高级 API |
| 模块拆分的 import 兼容性 | 低 | manager.py 保留 re-export，加 deprecation warning |

---

## References

1. [Apipool README](../README.md) — 项目官方文档
2. [httpx Advanced Usage](https://www.python-httpx.org/advanced/) — HTTP 客户端最佳实践
3. [boto3 Retry Configuration](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html) — AWS SDK 重试参考
4. [Python Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html) — Martin Fowler 断路器模式定义
5. [Pydantic v2 Migration Guide](https://docs.pydantic.dev/latest/migration/) — 配置管理现代化
