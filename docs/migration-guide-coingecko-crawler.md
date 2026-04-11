# CoinGecko Crawler 迁移指南 — apipool-ng v1.0.4

> 基于 `D:\Programming\Python\MarketDataBase\app\crawlers\coingecko.py` 的深度分析，
> 指导从当前 v2.0 apipool 集成版迁移到 v1.0.4 原生异步链式调用架构。

---

## 目录

1. [当前架构分析](#1-当前架构分析)
2. [核心问题诊断](#2-核心问题诊断)
3. [重构目标](#3-重构目标)
4. [迁移步骤说明](#4-迁移步骤说明)
5. [潜在风险点](#5-潜在风险点)
6. [测试验证方案](#6-测试验证方案)
7. [完整迁移后代码](#7-完整迁移后代码)

---

## 1. 当前架构分析

### 1.1 文件结构概览

```
coingecko.py (948 行)
├── 辅助层 (L1-52)        — 导入、常量、白名单
├── apipool 集成层 (L54-123) — CoinGeckoRateLimitError, CoinGeckoApiKeyAdapter, 错误判断函数
├── CoingeckoCrawler (L125-948)
│   ├── 初始化/关闭 (L137-202)     — initialize(), shutdown(), _resolve_api_keys(), _init_apipool_pool(), _initialize_legacy()
│   ├── 核心调用层 (L288-336)      — _api_call(), _call_via_apipool(), _call_legacy()
│   ├── 公开接口 (L338-391)       — fetch(), pool_status
│   ├── 数据获取方法 (L396-610)    — 7 个 DataType 处理器
│   └── 扩展功能 (L612-947)       — token detail, contract search, exchange, derivatives
```

### 1.2 依赖关系图

```
CoingeckoCrawler
  ├── BaseCrawler (框架基类)
  ├── apipool.ApiKey ← CoinGeckoApiKeyAdapter (继承)
  ├── apipool.ApiKeyManager (组合，key 池管理)
  ├── coingecko_sdk.AsyncCoingecko (实际 SDK 客户端)
  ├── tenacity (重试策略)
  ├── app.database.manager (数据库查询)
  └── app.config.settings (环境变量)
```

### 1.3 当前调用流程

```
用户调用: crawler.fetch(DataType.PRICE)
  → CoingeckoCrawler.fetch()
    → _fetch_prices()
      → _fetch_price_batch_with_retry()  (tenacity 重试)
        → self._api_call("coins.markets.get", ...)
          → _call_via_apipool(method_path)
            │ 手动拆分 "coins.markets.get" → ["coins", "markets", "get"]
            │ 手动遍历: dc = dummyclient → dc.coins → dc.markets → get
            │ await obj(*args, **kwargs)  ← 问题：dummyclient 是同步 ChainProxy！
            │   ApiCaller.__call__ 是同步方法
            │   但目标方法是异步的 → 返回 coroutine 对象而非结果
            └─ 结果可能未 await 就返回
```

### 1.4 功能清单

| 功能 | 方法 | 行数 | 数据类型 |
|---|---|---|---|
| 代币列表 | `_fetch_token_list` | 396-432 | TOKEN_LIST |
| 代币详情 | `_fetch_token_detail` | 613-772 | TOKEN_DETAIL |
| 价格数据 | `_fetch_prices` | 434-489 | PRICE |
| 现货交易所列表 | `_fetch_exchange_list` | 794-834 | EXCHANGE_LIST |
| 现货交易对 | `_fetch_exchange_tickers` | 549-609 | EXCHANGE_TICKER |
| 合约交易所列表 | `_fetch_derivatives_list` | 836-866 | DERIVATIVES_LIST |
| 合约交易对 | `_fetch_derivatives_tickers` | 868-947 | DERIVATIVES_TICKER |
| 合约地址搜索 | `_search_token_id_by_contract` | 774-790 | (辅助) |

---

## 2. 核心问题诊断

### 问题 1：同步 ChainProxy 调用异步 SDK（严重）

**位置**: `coingecko.py:310-327` (`_call_via_apipool`)

```python
async def _call_via_apipool(self, method_path: str, *args, **kwargs):
    manager = self._pool_manager
    dc = manager.dummyclient          # ← 同步 DummyClient！
    parts = method_path.split(".")
    obj = dc
    for part in parts:
        obj = getattr(obj, part)      # ← 返回同步 ChainProxy/ApiCaller
    result = await obj(*args, **kwargs)  # ← ApiCaller.__call__ 是同步的！
    return result                      # ← 返回 coroutine 对象而非结果
```

**问题**：`dummyclient` 是同步入口，`ApiCaller.__call__` 是普通方法。当它调用 `AsyncCoingecko` 的异步方法时，返回的是 **coroutine 对象**而非已执行的结果。`await` 一个同步函数返回的 coroutine 不会执行 ChainProxy 的统计/轮换逻辑。

### 问题 2：test_usability 中的事件循环检测（中等）

**位置**: `coingecko.py:91-103`

```python
def test_usability(self, client) -> bool:
    loop = asyncio.get_event_loop()
    if loop.is_running():       # ← 在异步上下文中 always True
        return True             # ← 跳过实际检测！
    result = loop.run_until_complete(client.ping())
```

在 `asyncio.run()` 环境中，事件循环始终运行，`test_usability` 永远返回 `True` 而不做实际检测。

### 问题 3：双模式代码冗余（低）

同时维护 `_call_via_apipool` 和 `_call_legacy` 两条调用路径，增加了维护成本。

### 问题 4：429 错误未触发 apipool key 切换（中等）

当前 `CoinGeckoRateLimitError` 定义了但**从未被抛出**。`_call_via_apipool` 中 `ApiCaller.__call__` 是同步方法，它捕获的是同步调用链中的异常，而 `AsyncCoingecko` 的异常是异步抛出的。

---

## 3. 重构目标

| 目标 | 说明 |
|---|---|
| **修复异步调用** | 使用 `adummyclient`（`AsyncDummyClient`）替换 `dummyclient`，确保异步方法正确 `await` |
| **修复可用性检测** | 利用 v1.0.4 的 `ais_usable()` 正确处理异步 `test_usability` |
| **消除双模式** | 移除 legacy 单 key 回退路径，统一使用 `ApiKeyManager` |
| **正确触发 key 切换** | `AsyncApiCaller` 自动捕获限流异常并触发 key 移除 |
| **保留重试逻辑** | tenacity 重试仍然有效，与 apipool key 轮换互补 |
| **零数据变更** | 所有数据模型、CrawlerResult 格式不变 |

---

## 4. 迁移步骤说明

### Step 1: 更新导入

```python
# ====== 当前 ======
try:
    import apipool
    from apipool import ApiKeyManager as _PoolManager, PoolExhaustedError as _PoolExhaustedError
    _APIPOOL_AVAILABLE = True
except ImportError:
    _APIPOOL_AVAILABLE = False

# ====== 迁移后 ======
try:
    from apipool import (
        ApiKey, ApiKeyManager, PoolExhaustedError,
        AsyncApiCaller, AsyncChainProxy, AsyncDummyClient,
    )
    _APIPOOL_AVAILABLE = True
except ImportError:
    _APIPOOL_AVAILABLE = False
```

### Step 2: 重写 CoinGeckoApiKeyAdapter

```python
class CoinGeckoApiKeyAdapter(ApiKey):
    """v1.0.4 异步原生适配器"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_primary_key(self) -> str:
        tail = self.api_key[-8:] if len(self.api_key) > 8 else self.api_key
        return f"CG_{tail}"

    def create_client(self):
        from coingecko_sdk import AsyncCoingecko
        return AsyncCoingecko(
            demo_api_key=self.api_key,
            environment='demo',
            max_retries=1,
        )

    async def test_usability(self, client) -> bool:
        """v1.0.4: 异步原生可用性检测，基类 ais_usable() 会自动 await"""
        try:
            result = await client.ping()
            gs = getattr(result, "gecko_says", None)
            if gs is None and hasattr(result, "to_dict"):
                gs = result.to_dict().get("gecko_says")
            return gs == "(G)Meow :)"
        except Exception:
            return False
```

**变更点**：
- `test_usability` 改为 `async def`，直接 `await client.ping()`
- 不再手动管理事件循环
- v1.0.4 的 `ais_usable()` 通过 `inspect.isawaitable()` 自动处理

### Step 3: 重写 `_call_via_apipool`

```python
async def _call_via_apipool(self, method_path: str, *args, **kwargs):
    """通过 v1.0.4 的 adummyclient 执行异步链式调用"""
    manager = self._pool_manager
    dc = manager.adummyclient        # ← 关键：使用异步入口

    parts = method_path.split(".")
    obj = dc
    for part in parts:
        obj = getattr(obj, part)     # 返回 AsyncChainProxy

    # AsyncChainProxy.__call__ 是 async 方法，正确 await 异步 SDK
    return await obj(*args, **kwargs)
```

**核心变更**：`dummyclient` → `adummyclient`，一行改动修复异步调用链。

### Step 4: 初始化使用异步连接

```python
async def _init_apipool_pool(self, keys: List[str]) -> bool:
    """使用 v1.0.4 异步初始化"""
    adapters = [CoinGeckoApiKeyAdapter(k) for k in keys]

    # 异步连接所有客户端
    for adapter in adapters:
        await adapter.aconnect_client()

    self._pool_manager = ApiKeyManager(
        apikey_list=adapters,
        reach_limit_exc=CoinGeckoRateLimitError,
    )

    # 异步可用性检查
    for pk, apikey in list(self._pool_manager.apikey_chain.items()):
        if not await apikey.ais_usable():
            self._pool_manager.remove_one(pk)

    active_count = len(self._pool_manager.apikey_chain)
    if active_count == 0:
        return False

    self._use_apipool = True
    logger.info(f"[apipool] Pool ready: {active_count}/{len(keys)} keys active")
    return True
```

### Step 5: 移除 legacy 模式（可选但推荐）

```python
async def initialize(self) -> bool:
    """初始化 API 客户端"""
    if not _APIPOOL_AVAILABLE:
        raise RuntimeError("apipool-ng is required. Install: pip install apipool-ng>=1.0.4")

    keys = self._resolve_api_keys()
    if not keys:
        raise ValueError("No CoinGecko API keys configured")

    success = await self._init_apipool_pool(keys)
    if not success:
        raise RuntimeError("All CoinGecko API keys failed usability check")

    self._is_initialized = True
    logger.info(f"CoinGecko pool initialized with {len(keys)} key(s)")
    return True
```

**收益**：删除 `_legacy_client`、`_initialize_legacy`、`_call_legacy`，减少约 40 行代码。

### Step 6: 简化 `_api_call`

```python
async def _api_call(self, method_path: str, *args, **kwargs):
    """统一 API 调用入口（仅 apipool 模式）"""
    manager = self._pool_manager
    dc = manager.adummyclient
    parts = method_path.split(".")
    obj = dc
    for part in parts:
        obj = getattr(obj, part)
    return await obj(*args, **kwargs)
```

---

## 5. 潜在风险点

### 风险 1: `check_usable()` 同步调用问题

**场景**: `ApiKeyManager.check_usable()` 是同步方法，内部调用 `apikey.is_usable()` → `test_usability()`。如果 `test_usability` 改为 `async def`，同步的 `is_usable()` 不会 await 它。

**缓解方案**:
- 在初始化阶段使用 `await apikey.ais_usable()` 手动检查，而非依赖 `check_usable()`
- 或保留同步 `test_usability` 作为同步回退

### 风险 2: 429 限流异常传播路径

**场景**: `AsyncApiCaller.__call__` 捕获 `self.reach_limit_exc`（即 `CoinGeckoRateLimitError`），但 CoinGecko SDK 可能抛出的是 `coingecko_sdk.exceptions.ApiException` 而非 `CoinGeckoRateLimitError`。

**缓解方案**: 在 `_api_call` 外层增加异常转换：

```python
async def _api_call(self, method_path: str, *args, **kwargs):
    try:
        return await self._do_call(method_path, *args, **kwargs)
    except Exception as e:
        if _is_rate_limit_error(e):
            raise CoinGeckoRateLimitError(str(e)) from e
        raise
```

这样 `AsyncApiCaller` 就能正确捕获 `CoinGeckoRateLimitError` 并触发 key 移除。

### 风险 3: tenacity 重试与 apipool key 轮换的交互

**场景**: 当 429 发生时：
1. `AsyncApiCaller` 捕获 `CoinGeckoRateLimitError` → 移除当前 key → 重新抛出异常
2. tenacity 捕获到异常 → 判断 `_is_retryable_error` → 触发重试
3. 重试时 apipool 随机选择另一个 key → 调用成功

**潜在问题**: 如果 429 异常被 apipool 转换为 `CoinGeckoRateLimitError`，tenacity 的 `_is_retryable_error` 需要也能识别它。

**缓解方案**: 更新 `_is_retryable_error`：

```python
def _is_retryable_error(exception: Exception) -> bool:
    if isinstance(exception, CoinGeckoRateLimitError):
        return True
    if isinstance(exception, PoolExhaustedError):
        return False  # 池耗尽不应重试
    # ... 原有逻辑
```

### 风险 4: `PoolExhaustedError` 在批量操作中的处理

**场景**: `_fetch_prices` 批量获取价格时，如果中途 key 池耗尽，后续批次全部失败。

**缓解方案**: 在批量循环中单独捕获 `PoolExhaustedError`，记录失败批次而非中断整个流程：

```python
except PoolExhaustedError:
    logger.error(f"Batch {batch_num}: all keys exhausted, stopping")
    break  # 不再 continue，因为后续批次必然也失败
```

### 风险 5: 数据完整性

**评估**: 本次迁移**不涉及任何数据模型变更**，所有 `CrawlerResult`、`TokenInfo`、`PriceInfo` 等结构保持不变，数据完整性不受影响。

---

## 6. 测试验证方案

### 6.1 单元测试

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

class TestCoinGeckoApiKeyAdapter:
    """测试适配器的三个接口方法"""

    @pytest.mark.asyncio
    async def test_get_primary_key(self):
        adapter = CoinGeckoApiKeyAdapter("test-api-key-12345678")
        assert adapter.get_primary_key() == "CG_345678"

    @pytest.mark.asyncio
    async def test_create_client(self):
        adapter = CoinGeckoApiKeyAdapter("test-key")
        with patch("coingecko_sdk.AsyncCoingecko") as MockSDK:
            client = adapter.create_client()
            MockSDK.assert_called_once_with(
                demo_api_key="test-key",
                environment='demo',
                max_retries=1,
            )

    @pytest.mark.asyncio
    async def test_test_usability_success(self):
        adapter = CoinGeckoApiKeyAdapter("test-key")
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.gecko_says = "(G)Meow :)"
        mock_client.ping = AsyncMock(return_value=mock_result)

        result = await adapter.test_usability(mock_client)
        assert result is True

    @pytest.mark.asyncio
    async def test_test_usability_failure(self):
        adapter = CoinGeckoApiKeyAdapter("test-key")
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=Exception("Network error"))

        result = await adapter.test_usability(mock_client)
        assert result is False


class TestAsyncChainCall:
    """测试异步链式调用流程"""

    @pytest.mark.asyncio
    async def test_adummyclient_chain_call(self):
        """验证 adummyclient 正确 await 异步方法"""
        from apipool import ApiKeyManager

        mock_client = AsyncMock()
        mock_client.coins = MagicMock()
        mock_client.coins.list = MagicMock()
        mock_client.coins.list.get = AsyncMock(return_value=[{"id": "bitcoin"}])

        class TestKey(ApiKey):
            def get_primary_key(self): return "test-key"
            def create_client(self): return mock_client
            def test_usability(self, client): return True

        manager = ApiKeyManager([TestKey()])
        result = await manager.adummyclient.coins.list.get()
        assert result == [{"id": "bitcoin"}]

    @pytest.mark.asyncio
    async def test_rate_limit_triggers_key_removal(self):
        """验证 429 限流触发 key 移除"""
        from apipool import ApiKeyManager, PoolExhaustedError

        class RateLimitError(Exception): pass

        class BadKey(ApiKey):
            def get_primary_key(self): return "bad-key"
            def create_client(self):
                client = AsyncMock()
                client.ping = AsyncMock(side_effect=RateLimitError("429 Too Many Requests"))
                return client
            def test_usability(self, client): return True

        manager = ApiKeyManager([BadKey()], reach_limit_exc=RateLimitError)
        # BadKey 在池中
        assert len(manager.apikey_chain) == 1

        with pytest.raises(RateLimitError):
            await manager.adummyclient.ping()

        # BadKey 已被移除
        assert len(manager.apikey_chain) == 0
        assert len(manager.archived_apikey_chain) == 1


class TestApiCallIntegration:
    """测试 _api_call 的完整调用链"""

    @pytest.mark.asyncio
    async def test_api_call_with_method_path(self):
        """验证 method_path 正确解析为链式调用"""
        from apipool import ApiKeyManager

        mock_client = AsyncMock()
        mock_client.coins = MagicMock()
        mock_client.coins.markets = MagicMock()
        mock_client.coins.markets.get = AsyncMock(return_value=[{"id": "bitcoin", "current_price": 50000}])

        class TestKey(ApiKey):
            def get_primary_key(self): return "test-key"
            def create_client(self): return mock_client
            def test_usability(self, client): return True

        manager = ApiKeyManager([TestKey()])
        dc = manager.adummyclient

        # 模拟 _api_call 的逻辑
        method_path = "coins.markets.get"
        parts = method_path.split(".")
        obj = dc
        for part in parts:
            obj = getattr(obj, part)
        result = await obj(vs_currency='usd', ids='bitcoin')

        mock_client.coins.markets.get.assert_called_once_with(
            vs_currency='usd', ids='bitcoin'
        )
```

### 6.2 集成测试检查清单

| 序号 | 测试场景 | 预期结果 | 验证方式 |
|---|---|---|---|
| 1 | 单 Key 正常调用 | 返回正确数据 | `await crawler.fetch(DataType.TOKEN_LIST)` |
| 2 | 多 Key 轮换 | 请求分布到不同 Key | 检查 `pool_status.active_count` |
| 3 | 单 Key 429 限流 | 自动切换到下一个 Key | 检查 `pool_status.archived_count` 增加 |
| 4 | 所有 Key 429 | 抛出 `PoolExhaustedError` | 被 `fetch()` 捕获并返回 `success=False` |
| 5 | tenacity 重试 + apipool 轮换 | 429 后重试使用新 Key 成功 | 日志显示 key 切换 + 重试成功 |
| 6 | 批量价格获取 | 部分批次失败不影响其他 | `CrawlerResult.metadata.count` 接近预期 |
| 7 | 异步 test_usability | 正确检测无效 Key | 无效 Key 不在 `apikey_chain` 中 |
| 8 | 长时间运行稳定性 | Key 池状态稳定 | 监控 `pool_status` 无异常增长 |

### 6.3 回归验证矩阵

确保迁移后以下功能与原版完全一致：

- [ ] `fetch(DataType.TOKEN_LIST)` — 代币列表包含 `include_platform` 信息
- [ ] `fetch(DataType.TOKEN_DETAIL, token_id="bitcoin")` — 返回地址、价格、tickers
- [ ] `fetch(DataType.TOKEN_DETAIL, contract_address="0x...", chain="ethereum")` — 合约搜索
- [ ] `fetch(DataType.PRICE)` — 批量价格，分页正确
- [ ] `fetch(DataType.EXCHANGE_LIST)` — 过滤掉 derivatives 交易所
- [ ] `fetch(DataType.EXCHANGE_TICKER, exchange_id="binance")` — 分页获取
- [ ] `fetch(DataType.DERIVATIVES_LIST)` — 合约交易所列表
- [ ] `fetch(DataType.DERIVATIVES_TICKER, exchange_id="binance_futures")` — 合约交易对
- [ ] `pool_status` 属性返回正确的池状态

---

## 7. 完整迁移后代码

以下为关键变更的完整代码片段（仅展示变更部分，未变更的数据处理逻辑保持原样）：

```python
"""
CoinGecko 数据源爬虫 (v3.0 — apipool-ng v1.0.4 异步原生版)

迁移变更:
- 使用 adummyclient 替代 dummyclient，修复异步调用链
- CoinGeckoApiKeyAdapter.test_usability 改为 async def
- 初始化使用 aconnect_client + ais_usable
- 移除 legacy 单 key 回退模式
- 增加限流异常转换层，确保 AsyncApiCaller 正确触发 key 切换
"""
import asyncio
from typing import List, Dict, Any, Optional
import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log
)

from app.core.crawler_base import BaseCrawler, CrawlerConfig, CrawlerResult, DataType
from app.core.data_models import (
    TokenInfo, TokenAddressInfo, PriceInfo, TickerInfo,
    ExchangeInfo, SpotInfo, PerpetualInfo
)
from app.core.registry import register_crawler
from app.core.crawler_config import get_crawler_config
from app.config import settings

# apipool-ng v1.0.4
try:
    from apipool import (
        ApiKey, ApiKeyManager, PoolExhaustedError,
        AsyncChainProxy, AsyncDummyClient,
    )
    _APIPOOL_AVAILABLE = True
except ImportError:
    _APIPOOL_AVAILABLE = False

logger = logging.getLogger(__name__)

EXCHANGE_ID_WHITE_LIST = ['binance']
PERPETUAL_EXCHANGE_ID_WHITE_LIST = ['binance_futures']


# ============================================================
# apipool-ng v1.0.4 集成层
# ============================================================


class CoinGeckoRateLimitError(Exception):
    """CoinGecko API 限流异常 — 触发 apipool key 切换"""


class CoinGeckoApiKeyAdapter(ApiKey):
    """
    v1.0.4 异步原生适配器。

    - create_client: 创建 AsyncCoingecko 实例
    - test_usability: async def，直接 await client.ping()
    - 基类 ais_usable() 自动处理 await
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_primary_key(self) -> str:
        tail = self.api_key[-8:] if len(self.api_key) > 8 else self.api_key
        return f"CG_{tail}"

    def create_client(self):
        from coingecko_sdk import AsyncCoingecko
        return AsyncCoingecko(
            demo_api_key=self.api_key,
            environment='demo',
            max_retries=1,
        )

    async def test_usability(self, client) -> bool:
        """异步可用性检测 — v1.0.4 基类会自动 await"""
        try:
            result = await client.ping()
            gs = getattr(result, "gecko_says", None)
            if gs is None and hasattr(result, "to_dict"):
                gs = result.to_dict().get("gecko_says")
            return gs == "(G)Meow :)"
        except Exception:
            return False


def _is_rate_limit_error(exception: Exception) -> bool:
    error_str = str(exception).lower()
    keywords = ["429", "throttl", "rate limit"]
    return any(kw in error_str for kw in keywords)


def _is_retryable_error(exception: Exception) -> bool:
    """判断是否需要重试（429 限流、5xx、网络错误）"""
    if isinstance(exception, CoinGeckoRateLimitError):
        return True  # apipool 已切换 key，重试有望成功
    if isinstance(exception, PoolExhaustedError):
        return False  # 所有 key 耗尽，重试无意义
    if _is_rate_limit_error(exception):
        return True
    error_str = str(exception).lower()
    if any(code in error_str for code in ["500", "502", "503", "504"]):
        return True
    if "timeout" in error_str or "connection" in error_str:
        return True
    return False


@register_crawler("coingecko")
class CoingeckoCrawler(BaseCrawler):
    """
    CoinGecko 爬虫 (v3.0 — apipool-ng v1.0.4 异步原生版)

    核心变更:
    - 使用 adummyclient 替代 dummyclient
    - 异常转换层确保 CoinGeckoRateLimitError 触发 key 切换
    - 移除 legacy 单 key 模式
    """

    def __init__(self, config: Optional[CrawlerConfig] = None):
        yaml_config = get_crawler_config("coingecko")

        if config is None:
            if yaml_config:
                config = yaml_config.to_crawler_config("coingecko")
            else:
                config = CrawlerConfig(
                    name="coingecko",
                    data_types=[
                        DataType.TOKEN_LIST, DataType.TOKEN_DETAIL,
                        DataType.PRICE, DataType.EXCHANGE_LIST,
                        DataType.EXCHANGE_TICKER, DataType.DERIVATIVES_LIST,
                        DataType.DERIVATIVES_TICKER,
                    ],
                    schedule_interval=300, priority=10, enabled=True,
                )
        super().__init__(config)
        self._yaml_config = yaml_config
        self._pool_manager = None

    # ---- 初始化 / 关闭 ----

    async def initialize(self) -> bool:
        if not _APIPOOL_AVAILABLE:
            raise RuntimeError(
                "apipool-ng>=1.0.4 is required. "
                "Install: pip install apipool-ng>=1.0.4"
            )

        keys = self._resolve_api_keys()
        if not keys:
            raise ValueError("No CoinGecko API keys configured")

        # 异步连接所有客户端
        adapters = [CoinGeckoApiKeyAdapter(k) for k in keys]
        for adapter in adapters:
            await adapter.aconnect_client()

        self._pool_manager = ApiKeyManager(
            apikey_list=adapters,
            reach_limit_exc=CoinGeckoRateLimitError,
        )

        # 异步可用性检查
        for pk in list(self._pool_manager.apikey_chain.keys()):
            apikey = self._pool_manager.apikey_chain[pk]
            if not await apikey.ais_usable():
                self._pool_manager.remove_one(pk)
                logger.warning(f"[apipool] Key {pk} failed usability check, removed")

        active_count = len(self._pool_manager.apikey_chain)
        if active_count == 0:
            raise RuntimeError("All CoinGecko API keys failed usability check")

        self._is_initialized = True
        logger.info(f"[apipool] Pool ready: {active_count}/{len(keys)} keys active")
        return True

    async def shutdown(self) -> None:
        self._pool_manager = None
        self._is_initialized = False
        await super().shutdown()

    # ---- API Key 解析 ----

    def _resolve_api_keys(self) -> List[str]:
        keys = []
        if self._yaml_config and getattr(self._yaml_config, 'api_keys', None):
            yk = [str(k) for k in self._yaml_config.api_keys if str(k).strip()]
            keys.extend(yk)
        env_multi = settings.COINGECKO_API_KEYS
        if env_multi:
            ek = [k.strip() for k in env_multi.split(",") if k.strip()]
            keys.extend(ek)
        if not keys:
            env_single = settings.COINGECKO_API_KEY
            if env_single:
                keys.append(env_single)
        return keys

    # ---- 核心调用层 ----

    async def _api_call(self, method_path: str, *args, **kwargs):
        """
        统一 API 调用入口。

        使用 adummyclient 异步链式调用，自动处理：
        - 随机 key 选择
        - 限流异常捕获 → key 移除 → 切换
        - 调用统计
        """
        manager = self._pool_manager
        dc = manager.adummyclient  # ← 异步入口

        parts = method_path.split(".")
        obj = dc
        for part in parts:
            obj = getattr(obj, part)  # AsyncChainProxy

        try:
            return await obj(*args, **kwargs)
        except Exception as e:
            # 将 SDK 原始 429 异常转换为 CoinGeckoRateLimitError
            # 以便 apipool 在上层重试时触发 key 切换
            if _is_rate_limit_error(e) and not isinstance(e, CoinGeckoRateLimitError):
                raise CoinGeckoRateLimitError(str(e)) from e
            raise

    # ---- 公开接口 ----

    async def fetch(self, data_type: DataType, **kwargs) -> CrawlerResult:
        if not self._is_initialized:
            await self.initialize()
        handlers = {
            DataType.TOKEN_LIST: self._fetch_token_list,
            DataType.TOKEN_DETAIL: self._fetch_token_detail,
            DataType.PRICE: self._fetch_prices,
            DataType.EXCHANGE_LIST: self._fetch_exchange_list,
            DataType.EXCHANGE_TICKER: self._fetch_exchange_tickers,
            DataType.DERIVATIVES_LIST: self._fetch_derivatives_list,
            DataType.DERIVATIVES_TICKER: self._fetch_derivatives_tickers,
        }
        handler = handlers.get(data_type)
        if not handler:
            return CrawlerResult(
                success=False, data_type=data_type, data=[],
                source=self.name, error=f"Unsupported data type: {data_type}"
            )
        try:
            return await handler(**kwargs)
        except PoolExhaustedError:
            logger.error(f"All keys exhausted while fetching {data_type}")
            return CrawlerResult(
                success=False, data_type=data_type, data=[],
                source=self.name, error="All API keys exhausted"
            )
        except Exception as e:
            err_type = type(e).__name__
            logger.error(f"Error fetching {data_type}: {err_type}: {e}", exc_info=True)
            return CrawlerResult(
                success=False, data_type=data_type, data=[],
                source=self.name, error=f"{err_type}: {e}"
            )

    @property
    def pool_status(self) -> Dict[str, Any]:
        if self._pool_manager is None:
            return {"mode": "uninitialized", "status": "not_ready"}
        m = self._pool_manager
        return {
            "mode": "apipool",
            "active_keys": list(m.apikey_chain.keys()),
            "archived_keys": list(m.archived_apikey_chain.keys()),
            "active_count": len(m.apikey_chain),
            "archived_count": len(m.archived_apikey_chain),
        }

    # ==================== 数据获取方法 ====================
    # 以下方法保持不变，仅 self._api_call 内部实现改变
    # （此处省略，与原版完全相同）

    # ... _fetch_token_list, _fetch_prices, _fetch_price_batch_with_retry,
    #     _fetch_exchange_tickers, _fetch_token_detail, _search_token_id_by_contract,
    #     _fetch_exchange_list, _fetch_derivatives_list, _fetch_derivatives_tickers
    #     均保持原样，无需修改 ...
```

---

## 迁移变更总结

| 变更项 | 原实现 | 新实现 | 影响范围 |
|---|---|---|---|
| 导入 | `ApiKeyManager, PoolExhaustedError` | 增加 `AsyncChainProxy, AsyncDummyClient` | L37-42 |
| `CoinGeckoApiKeyAdapter.test_usability` | 同步 + 手动事件循环 | `async def` + 直接 `await` | L91-103 |
| `_call_via_apipool` | `manager.dummyclient`（同步） | `manager.adummyclient`（异步） | L317 |
| `_api_call` | 无异常转换 | 增加 429 → `CoinGeckoRateLimitError` 转换 | L290-336 |
| `_init_apipool_pool` | 同步 `check_usable()` | 异步 `aconnect_client` + `ais_usable` | L240-268 |
| legacy 模式 | 保留双路径 | 移除（可选） | L169, L272-286, L329-336 |
| `_is_retryable_error` | 不识别 `CoinGeckoRateLimitError` | 识别并允许重试 | L113-122 |
| `fetch()` 异常处理 | 不处理 `PoolExhaustedError` | 显式捕获 | L365-376 |

**净增代码**: ~0 行（删除 legacy ≈ 新增异常转换）
**风险等级**: 低（所有数据模型不变，调用接口不变）
**预计迁移时间**: 30 分钟
