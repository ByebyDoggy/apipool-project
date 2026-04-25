# 客户端 API 调用统计上报 — 设计开发文档

## 1. 背景与问题

当前 apipool 系统的架构中存在统计盲区：

- **代理模式**（`connect()` / `async_connect()`）：客户端通过 `_ServiceClient` 将所有 API 调用透传至服务端，服务端的 `proxy` 路由可以直接记录统计到 per-pool SQLite 数据库。此模式下服务端拥有完整的调用数据。
- **SDK 模式**（`DynamicKeyManager` / `AsyncDynamicKeyManager`）：客户端从服务端拉取密钥列表后，在本地直接调用第三方 API。统计数据仅写入客户端本地内存 SQLite（`StatsCollector`），**服务端完全无法感知这些调用**。

这导致服务端 Dashboard 上看到的统计只有代理模式的数据，而 SDK 模式下的大量调用成为"暗数据"。

## 2. 设计目标

1. 客户端 SDK 模式下的 API 调用事件能自动、定时上报至服务端
2. 上报后本地事件清除，避免重复上报和无限增长
3. 增强数据模型，在现有 (key, 时间, 状态) 基础上增加 latency（延迟）和 method（调用方法名）
4. 对现有代码的侵入性最小，保持向后兼容
5. 同步 `DynamicKeyManager` 和异步 `AsyncDynamicKeyManager` 均需支持

## 3. 数据模型设计

### 3.1 客户端 Event 表变更（`apipool/stats.py`）

现有 Event 表：

```python
class Event(Base):
    __tablename__ = "event"
    apikey_id = Column(Integer, ForeignKey("apikey.id"), primary_key=True)
    finished_at = Column(DateTime, primary_key=True)
    status_id = Column(Integer, ForeignKey("status.id"))
```

新增两个字段：

```python
class Event(Base):
    __tablename__ = "event"
    apikey_id = Column(Integer, ForeignKey("apikey.id"), primary_key=True)
    finished_at = Column(DateTime, primary_key=True)
    status_id = Column(Integer, ForeignKey("status.id"))
    latency = Column(Float, nullable=True)       # 请求延迟（秒）
    method = Column(String(128), nullable=True)   # 调用方法名，如 "coins.simple.price.get"
```

`latency` 和 `method` 均为 nullable，保证与旧数据兼容。

### 3.2 StatsCollector.add_event 变更

```python
# 旧签名
def add_event(self, primary_key, status_id):

# 新签名
def add_event(self, primary_key, status_id, latency=None, method=None):
```

增加可选参数，现有调用无需修改。

### 3.3 服务端上报数据模型（新增）

服务端需要一个专门的表来存储客户端上报的统计数据，不与现有的 per-pool SQLite 混用（因为上报数据来自多个客户端，需要集中存储）。

#### 方案：在主数据库中新增 `client_call_logs` 表

```python
class ClientCallLog(Base):
    __tablename__ = "client_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pool_identifier = Column(String(64), nullable=False, index=True)
    key_identifier = Column(String(128), nullable=False)      # 客户端的 primary_key 哈希或 key_id
    status = Column(String(16), nullable=False)                # "success" / "failed" / "reach_limit"
    latency = Column(Float, nullable=True)
    method = Column(String(128), nullable=True)
    finished_at = Column(DateTime, nullable=False, index=True)
    reported_at = Column(DateTime, default=func.now())         # 上报时间
    client_id = Column(String(64), nullable=True)              # 客户端标识，用于去重
```

> **设计说明**：`key_identifier` 不存储原始密钥，而是使用 primary_key 的哈希值（与服务端现有做法一致，参考 `stats_service.py` 中的 `mapping` 逻辑）。`client_id` 用于多客户端场景下的去重，格式为 `{hostname}:{process_id}` 或用户自定义。

### 3.4 上报 API 请求/响应 Schema

```python
# apipool_server/schemas/stats.py 新增

class ClientCallEvent(BaseModel):
    """单个调用事件（客户端上报）"""
    key_identifier: str           # primary_key 的哈希
    status: str                   # "success" / "failed" / "reach_limit"
    latency: float | None = None
    method: str | None = None
    finished_at: datetime

class StatsReportRequest(BaseModel):
    """客户端统计上报请求"""
    pool_identifier: str
    client_id: str | None = None  # 客户端标识
    events: list[ClientCallEvent]

class StatsReportResponse(BaseModel):
    """上报响应"""
    accepted: int            # 接受的事件数
    duplicates: int = 0      # 重复事件数（基于去重逻辑）
```

## 4. 客户端改造

### 4.1 ApiCaller / AsyncApiCaller 增加延迟和 method 记录

```python
# apipool/manager.py — ApiCaller 改造

class ApiCaller(object):
    def __init__(self, apikey, apikey_manager, call_method, reach_limit_exc, attr_path=None):
        self.apikey = apikey
        self.apikey_manager = apikey_manager
        self.call_method = call_method
        self.reach_limit_exc = reach_limit_exc
        self._attr_path = attr_path or []  # 新增：记录方法路径

    def __call__(self, *args, **kwargs):
        method_name = ".".join(self._attr_path) if self._attr_path else None
        start = time.monotonic()
        try:
            res = self.call_method(*args, **kwargs)
            latency = time.monotonic() - start
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c1_Success.id,
                latency=latency, method=method_name,
            )
            return res
        except self.reach_limit_exc as e:
            latency = time.monotonic() - start
            self.apikey_manager.remove_one(self.apikey.primary_key)
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c9_ReachLimit.id,
                latency=latency, method=method_name,
            )
            raise e
        except Exception as e:
            latency = time.monotonic() - start
            self.apikey_manager.stats.add_event(
                self.apikey.primary_key, StatusCollection.c5_Failed.id,
                latency=latency, method=method_name,
            )
            raise e
```

同理，`AsyncApiCaller` 做相同改造（使用 `await` 版本的计时逻辑）。

### 4.2 ChainProxy / AsyncChainProxy 传递 attr_path

```python
# ChainProxy.__call__ 改造
def __call__(self, *args, **kwargs):
    apikey = self._manager.random_one()
    real_client = apikey._client
    target = real_client
    for attr in self._attr_path:
        target = getattr(target, attr)
    ...
    return ApiCaller(
        apikey=apikey,
        apikey_manager=self._manager,
        call_method=target,
        reach_limit_exc=self._reach_limit_exc,
        attr_path=self._attr_path,  # 新增
    )(*args, **kwargs)
```

### 4.3 StatsCollector 增加批量查询和删除方法

```python
# apipool/stats.py 新增方法

class StatsCollector(object):
    # ... 现有代码 ...

    def fetch_events_batch(self, limit=500):
        """获取一批事件用于上报，返回 list[dict]"""
        ses = self.create_session()
        events = ses.query(Event).order_by(Event.finished_at.asc()).limit(limit).all()
        result = []
        for evt in events:
            pk = self._apikey_id_to_key.get(evt.apikey_id, "")
            result.append({
                "key_identifier": pk,
                "status_id": evt.status_id,
                "latency": evt.latency,
                "method": evt.method,
                "finished_at": evt.finished_at,
                # 以下字段用于去重和删除
                "_apikey_id": evt.apikey_id,
                "_finished_at": evt.finished_at,
            })
        ses.close()
        return result

    def delete_events(self, events_to_delete):
        """删除已上报的事件，参数为 fetch_events_batch 返回的列表"""
        if not events_to_delete:
            return
        ses = self.create_session()
        for evt in events_to_delete:
            ses.query(Event).filter(
                Event.apikey_id == evt["_apikey_id"],
                Event.finished_at == evt["_finished_at"],
            ).delete()
        ses.commit()
        ses.close()
```

> **注意**：因为 Event 的主键是 `(apikey_id, finished_at)` 的复合主键，所以需要同时用这两个字段定位要删除的行。

### 4.4 DynamicKeyManager 增加上报功能

在构造函数中新增参数：

```python
class DynamicKeyManager(ApiKeyManager):
    def __init__(
        self,
        key_fetcher: Callable[[], List[str]],
        api_key_factory: Callable[[str], ApiKey],
        refresh_interval: float = 60.0,
        reach_limit_exc=None,
        db_engine=None,
        on_keys_added=None,
        on_keys_removed=None,
        config_fetcher=None,
        # ── 新增参数 ──
        stats_report_url: Optional[str] = None,      # 上报目标 URL
        stats_report_token: Optional[str] = None,     # 认证 token
        stats_report_interval: float = 30.0,          # 上报间隔（秒）
        stats_report_batch_size: int = 500,            # 每批最大事件数
    ):
```

新增上报线程：

```python
def _report_loop(self):
    """后台线程：定时上报统计数据"""
    while not self._shutdown_event.wait(timeout=self._stats_report_interval):
        try:
            self._do_report()
        except Exception:
            logger.exception("DynamicKeyManager: stats report failed")

def _do_report(self):
    """从本地 SQLite 取出事件，HTTP POST 到服务端，成功后删除"""
    events = self.stats.fetch_events_batch(limit=self._stats_report_batch_size)
    if not events:
        return

    # 转换为上报格式
    status_map = StatusCollection.get_mapper_id_to_description()
    report_events = []
    for evt in events:
        report_events.append({
            "key_identifier": evt["key_identifier"],
            "status": status_map.get(evt["status_id"], "unknown"),
            "latency": evt["latency"],
            "method": evt["method"],
            "finished_at": evt["finished_at"].isoformat() if evt["finished_at"] else None,
        })

    try:
        resp = httpx.post(
            f"{self._stats_report_url}/api/v1/stats/report",
            json={
                "pool_identifier": self._pool_identifier,
                "client_id": self._client_id,
                "events": report_events,
            },
            headers={"Authorization": f"Bearer {self._stats_report_token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()

        # 上报成功，删除本地事件
        if result.get("accepted", 0) > 0:
            self.stats.delete_events(events)
            logger.info(
                "DynamicKeyManager: reported %d events, deleted from local DB",
                result["accepted"],
            )
    except Exception:
        logger.warning("DynamicKeyManager: stats report HTTP request failed", exc_info=True)
```

`shutdown()` 方法需要同时停止上报线程：

```python
def shutdown(self):
    """Stop the background refresh and report threads gracefully."""
    self._shutdown_event.set()
    self._refresh_thread.join(timeout=5.0)
    if hasattr(self, '_report_thread') and self._report_thread:
        self._report_thread.join(timeout=5.0)
    logger.info("DynamicKeyManager: shutdown complete")
```

### 4.5 AsyncDynamicKeyManager 增加上报功能

异步版本使用 `asyncio` 任务代替线程：

```python
async def _areport_loop(self):
    """后台 asyncio 任务：定时上报统计数据"""
    while not self._async_shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                self._async_shutdown_event.wait(),
                timeout=self._stats_report_interval,
            )
            return
        except asyncio.TimeoutError:
            pass

        try:
            await self._ado_report()
        except Exception:
            logger.exception("AsyncDynamicKeyManager: stats report failed")

async def _ado_report(self):
    """异步上报：使用 httpx.AsyncClient"""
    events = self.stats.fetch_events_batch(limit=self._stats_report_batch_size)
    if not events:
        return

    status_map = StatusCollection.get_mapper_id_to_description()
    report_events = [... ]  # 同步版本相同的转换逻辑

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{self._stats_report_url}/api/v1/stats/report",
            json={...},
            headers={"Authorization": f"Bearer {self._stats_report_token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("accepted", 0) > 0:
            self.stats.delete_events(events)
```

### 4.6 client.py 便捷函数

为 `DynamicKeyManager` 使用者提供更便捷的初始化方式，在现有 `get_keys()` / `get_config()` 旁边增加 `report_stats_url` 的自动推导：

```python
def connect_with_stats(
    service_url: str,
    pool_identifier: str,
    auth_token: str,
    refresh_interval: float = 60.0,
    stats_report_interval: float = 30.0,
) -> DynamicKeyManager:
    """连接到 apipool 服务并启用统计上报。

    自动配置 key_fetcher、config_fetcher 和 stats_report_url。
    """
    return DynamicKeyManager(
        key_fetcher=lambda: get_keys(service_url, pool_identifier, auth_token),
        api_key_factory=lambda raw_key: ...,
        refresh_interval=refresh_interval,
        config_fetcher=lambda: get_config(service_url, pool_identifier, auth_token),
        stats_report_url=service_url,
        stats_report_token=auth_token,
        stats_report_interval=stats_report_interval,
    )
```

## 5. 服务端改造

### 5.1 数据库模型（`apipool_server/models/`）

新增 `client_call_log.py`：

```python
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, func
from ..database import Base

class ClientCallLog(Base):
    __tablename__ = "client_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pool_identifier = Column(String(64), nullable=False, index=True)
    key_identifier = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False)
    latency = Column(Float, nullable=True)
    method = Column(String(128), nullable=True)
    finished_at = Column(DateTime, nullable=False, index=True)
    reported_at = Column(DateTime, server_default=func.now())
    client_id = Column(String(64), nullable=True)
```

### 5.2 Schema（`apipool_server/schemas/stats.py`）

新增上报相关 Schema（见 3.4 节）。

### 5.3 上报 API 端点（`apipool_server/api/v1/stats.py`）

```python
@router.post("/report", response_model=StatsReportResponse)
def report_stats(
    req: StatsReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """接收客户端上报的 API 调用统计数据。"""
    service = StatsService(db)
    return service.receive_report(user, req)
```

### 5.4 StatsService 新增 receive_report（`apipool_server/services/stats_service.py`）

```python
def receive_report(self, user: User, req: StatsReportRequest) -> StatsReportResponse:
    """接收客户端上报的统计数据，写入 client_call_logs 表。"""
    accepted = 0
    for event in req.events:
        log = ClientCallLog(
            user_id=user.id,
            pool_identifier=req.pool_identifier,
            key_identifier=event.key_identifier,
            status=event.status,
            latency=event.latency,
            method=event.method,
            finished_at=event.finished_at,
            client_id=req.client_id,
        )
        self.db.add(log)
        accepted += 1

    self.db.commit()
    return StatsReportResponse(accepted=accepted)
```

### 5.5 统计查询整合

现有的 `get_success_rate`、`get_call_logs` 等方法从 per-pool SQLite 读取数据。新增客户端上报数据后，需要决定如何整合：

**方案：新增性质相同的查询方法，合并两处数据源**

在 `StatsService` 中，对 `get_success_rate` 和 `get_call_logs` 进行增强：

```python
def get_success_rate(self, user, pool_identifier, seconds):
    # 1. 从 per-pool SQLite 读取代理模式数据（现有逻辑）
    proxy_stats = self._get_proxy_success_rate(user, pool_identifier, seconds)

    # 2. 从 client_call_logs 读取 SDK 模式上报数据
    client_stats = self._get_client_reported_success_rate(user, pool_identifier, seconds)

    # 3. 合并两处结果
    return self._merge_success_rate(proxy_stats, client_stats)
```

也可以提供一个 `source` 参数让用户选择查看哪个数据源：`source="all" | "proxy" | "client"`。

### 5.6 数据库迁移

在 `apipool_server/database.py` 的 `_MIGRATIONS` 列表中无需添加（因为是新表），在 `_NEW_TABLES` 中添加建表 SQL 即可。

同时需要对 `apipool/stats.py` 中的 Event 表进行列迁移（增加 latency 和 method 列），此迁移在客户端库的 `StatsCollector.__init__` 中处理：

```python
class StatsCollector(object):
    def __init__(self, engine):
        Base.metadata.create_all(engine)
        self.engine = engine
        self.ses = self.create_session()
        self._add_all_status()
        self._migrate_event_table()  # 新增
        ...

    def _migrate_event_table(self):
        """为现有 Event 表增加 latency 和 method 列"""
        from sqlalchemy import inspect
        inspector = inspect(self.engine)
        if "event" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("event")}
            if "latency" not in columns:
                with self.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE event ADD COLUMN latency FLOAT"))
            if "method" not in columns:
                with self.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE event ADD COLUMN method VARCHAR(128)"))
```

## 6. 客户端本地 SQLite 持久化

当前 `DynamicKeyManager` 默认使用内存 SQLite（`sqlite:///:memory:`），这意味着进程重启后统计数据丢失。要支持统计上报，需要将本地 SQLite 改为文件持久化。

### 方案

在 `DynamicKeyManager.__init__` 中，如果未提供 `db_engine`，自动创建文件型 SQLite：

```python
import tempfile
import os

# 在 DynamicKeyManager.__init__ 中
if db_engine is None:
    stats_dir = os.path.join(tempfile.gettempdir(), "apipool_stats")
    os.makedirs(stats_dir, exist_ok=True)
    db_path = os.path.join(stats_dir, f"{pool_identifier}.db")
    db_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
```

> **注意**：这需要 `pool_identifier` 在构造时可获取。当前 `DynamicKeyManager` 不存储 `pool_identifier`，需要新增该属性。一种方案是通过 `key_fetcher` 闭包隐式传递，另一种是显式增加参数。推荐显式增加 `pool_identifier` 参数。

## 7. 时序图

```
客户端 (DynamicKeyManager)                服务端 (apipool-server)
        │                                        │
        │  1. API 调用 (通过 ApiCaller)           │
        │  → stats.add_event(key, status,        │
        │     latency, method)                   │
        │  → 写入本地 SQLite                      │
        │                                        │
        │  ══════════ 后台线程 ══════════         │
        │                                        │
        │  2. 定时触发 (每 30s)                    │
        │  → stats.fetch_events_batch()          │
        │  → 取出待上报事件                        │
        │                                        │
        │  3. POST /api/v1/stats/report          │
        │  ──────────────────────────────────────>│
        │     {pool_identifier, client_id,        │
        │      events: [{key, status, latency,    │
        │      method, finished_at}]}             │
        │                                        │  4. 写入 client_call_logs 表
        │                                        │
        │  5. 200 {accepted: N}                  │
        │ <──────────────────────────────────────│
        │                                        │
        │  6. stats.delete_events(reported)      │
        │  → 从本地 SQLite 删除已上报事件          │
        │                                        │
```

## 8. 文件变更清单

### 客户端库 (`apipool/`)

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `stats.py` | 修改 | Event 表增加 latency、method 列；StatsCollector.add_event 增加参数；新增 fetch_events_batch、delete_events、_migrate_event_table 方法 |
| `manager.py` | 修改 | ApiCaller/AsyncApiCaller 增加延迟计时和 method 记录；ChainProxy/AsyncChainProxy 传递 attr_path；DynamicKeyManager 增加上报线程和配置参数；AsyncDynamicKeyManager 增加上报任务 |
| `client.py` | 新增 | 新增 `connect_with_stats()` 便捷函数 |
| `__init__.py` | 修改 | 导出 `connect_with_stats` |

### 服务端 (`apipool_server/`)

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `models/client_call_log.py` | 新增 | ClientCallLog ORM 模型 |
| `schemas/stats.py` | 修改 | 新增 ClientCallEvent、StatsReportRequest、StatsReportResponse |
| `services/stats_service.py` | 修改 | 新增 receive_report 方法；增强 get_success_rate/get_call_logs 整合上报数据 |
| `api/v1/stats.py` | 修改 | 新增 POST /stats/report 端点 |
| `database.py` | 修改 | _NEW_TABLES 增加建表 SQL |

## 9. 配置参数汇总

### 客户端参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `stats_report_url` | `None`（不上报） | 上报目标服务端 URL |
| `stats_report_token` | `None` | 认证 JWT token |
| `stats_report_interval` | 30.0 | 上报间隔（秒） |
| `stats_report_batch_size` | 500 | 每批最大事件数 |

### 服务端参数

无需新增配置项。上报 API 复用现有的 JWT 认证机制。

## 10. 错误处理与容错

1. **上报失败**：HTTP 请求失败时不删除本地事件，下次定时触发时重试。仅记录 warning 日志。
2. **服务端不可达**：本地 SQLite 持续积累事件。建议设置本地事件保留上限（如最多 10000 条），超出后丢弃最旧的事件。
3. **去重**：当前方案基于"上报后删除"避免重复。极端情况下（如 HTTP 200 但客户端未收到响应）可能产生少量重复，服务端可容忍，因为统计数据允许近似。
4. **时钟偏移**：`finished_at` 使用客户端本地时间，不同客户端间可能存在时钟偏移。对统计聚合影响极小。

## 11. 向后兼容性

1. `StatsCollector.add_event` 新参数均有默认值，现有代码无需修改
2. Event 表新增列均为 nullable，旧数据自动为 NULL
3. `DynamicKeyManager` 新增参数均有默认值，不传 `stats_report_url` 时行为与旧版完全一致
4. 服务端新增 API 端点和表，不影响现有功能
5. 统计查询接口可选择是否整合客户端上报数据（通过 `source` 参数）

## 12. 测试要点

1. **单元测试**：`StatsCollector.add_event` 带 latency/method 参数
2. **单元测试**：`StatsCollector.fetch_events_batch` 和 `delete_events` 的正确性
3. **集成测试**：客户端上报 → 服务端接收 → 数据写入完整链路
4. **集成测试**：上报后本地事件确实被删除
5. **容错测试**：服务端不可达时，本地事件不丢失
6. **并发测试**：多线程下 stats 读写不冲突
7. **迁移测试**：旧版 Event 表增加新列后数据完整
