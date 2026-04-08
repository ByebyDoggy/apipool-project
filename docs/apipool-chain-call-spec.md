# apipool-ng 需求文档：支持多层属性链兼容调用

> **版本**: v1.0  
> **日期**: 2026-04-08  
> **提出方**: MarketDataBase 项目组  
> **接收方**: apipool-ng 开发团队  
> **优先级**: P0（阻塞集成）  
> **关联 Issue**: （待创建）

---

## 1. 问题背景

### 1.1 当前行为

apipool-ng 的 `DummyClient` 通过 `__getattr__` 拦截属性访问，返回 `ApiCaller` 可调用包装器，实现透明代理：

```python
# manager.py:49-61 (当前实现)
class DummyClient(object):
    def __getattr__(self, item):
        apikey = self._apikey_manager.random_one()
        call_method = getattr(apikey._client, item)
        return ApiCaller(apikey, self._apikey_manager, call_method, ...)

class ApiCaller(object):
    def __call__(self, *args, **kwargs):  # 只能被调用，不能继续访问属性
        res = self.call_method(*args, **kwargs)
        ...
```

### 1.2 触发场景

当底层 API 客户端使用**多层嵌套属性链**时，调用失败：

```
用户代码                          内部流转
─────────                        ──────────

dummyclient.coins                → ApiCaller(call_method=coins_resource)    ✓ OK
dummyclient.coins.simple         → AttributeError: 'ApiCaller' has no 'simple'   ✗ FAIL
dummyclient.coins.simple.price   → (同上)                                      ✗ FAIL
dummyclient.coins.simple.price.get(...)  → (无法到达)                           ✗ FAIL
```

**根因**: `ApiCaller` 没有 `__getattr__` 方法，只能做 1 层属性访问后的最终调用。

### 1.3 实际影响案例

| API SDK | 属性链深度 | 调用示例 | 是否可用 |
|---------|-----------|---------|---------|
| geopy GoogleV3 | 1 层 | `dummyclient.geocode(...)` | ✅ 可用 |
| **CoinGecko SDK** | **4 层** | `dummyclient.coins.simple.price.get(...)` | ❌ 不可用 |
| Stripe Python | 3+ 层 | `dummyclient.v1.customers.list()` | ❌ 不可用 |
| OpenAI Python | 3 层 | `dummyclient.chat.completions.create()` | ❌ 不可用 |
| Boto3 / AWS | 4+ 层 | `dummyclient.ec2.describe_instances()` | ❌ 不可用 |

---

## 2. 需求定义

### 2.1 目标

使 `DummyClient` 支持任意深度的属性链访问，在**到达可调用对象时自动包装为 `ApiCaller`**：

```python
# 期望效果 — 所有以下调用均正常工作：

# 1 层（当前已支持）
result = await dummyclient.ping()

# 4 层 — 新增支持
result = await dummyclient.coins.simple.price.get(
    ids="bitcoin", vs_currencies="usd"
)

# 3 层 — 新增支持
result = dummyclient.v1.users.list(limit=10)

# 混合路径 — 新增支持
result = dummyclient.api.account.balance()
```

### 2.2 核心约束

| 约束项 | 要求 |
|--------|------|
| **向后兼容** | 1 层调用的现有用户代码零修改 |
| **性能开销** | 属性链解析不应引入显著延迟 |
| **Key 选择时机** | 仅在**最终调用 (`__call__`)** 时才执行 `random_one()`，而非每次属性访问都选 key |
| **异常处理不变** | 成功/失败/达限的三种事件记录逻辑完全保留 |
| **无新依赖** | 不引入第三方库 |

---

## 3. 技术方案建议

### 3.1 推荐方案：中间代理模式 (Intermediate Proxy)

**核心思路**: 引入一个中间代理类 `ChainProxy`，在属性链的"中间节点"返回 `ChainProxy`，在"叶子节点"（可调用对象）返回 `ApiCaller`。

#### 3.1.1 类关系图

```
                    DummyClient
                    ___________
                   |           |
        .coins ───►│ ChainProxy │◄──── .simple
                   |  _attr_path:|
                   │  ["coins"]  │
                   |_____________|
                         │
              .price ───►│ ChainProxy │
                        |  _attr_path:|
                        │  ["coins",  │
                        │   "simple", │
                        │   "price"]  │
                        |_____________|
                              │
                    .get() ──►│  ApiCaller   │  ← 最终调用点
                              |  __call__()  │
                              |  random_one()│  ← 在此选择 key
                              |  stats.record│
                              |_____________|
```

#### 3.1.2 伪代码实现

```python
# ==================== 方案：manager.py 改动 ====================

class ChainProxy:
    """属性链中间节点代理。
    
    在属性链中传递，直到遇到 callable 时转为 ApiCaller。
    
    特性：
    - 延迟选择 key：只在最终 __call__ 时才 random_one()
    - 记录完整属性路径：用于调试和日志
    - 透明代理：对上层代码完全无感知
    """
    
    def __init__(self, client_getter, attr_path, reach_limit_exc):
        """
        Args:
            client_getter: 返回真实 client 的 callable (如 lambda: random_key._client)
            attr_path: 已遍历的属性名列表，如 ["coins", "simple", "price"]
            reach_limit_exc: 触发限额的异常类型
        """
        self._get_client = client_getter
        self._attr_path = list(attr_path)  # 复制，避免共享引用
        self._reach_limit_exc = reach_limit_exc
    
    def __getattr__(self, item):
        """继续沿属性链向下导航"""
        # 将新属性追加到路径中，返回新的 ChainProxy
        return ChainProxy(
            client_getter=self._get_client,
            attr_path=self._attr_path + [item],
            reach_limit_exc=self._reach_limit_exc,
        )
    
    def __call__(self, *args, **kwargs):
        """到达链末端 —— 执行实际调用
        
        这是整个方案的关键：
        1. 此时才从 Manager 随机选取一个 key
        2. 沿着记录的属性路径逐层 getattr 到达真实方法
        3. 包装为 ApiCaller 的逻辑执行并记录统计
        """
        # 步骤 1：获取真实 client 和对应的 apikey 对象
        # client_getter 应该返回 (apikey, client) 元组
        apikey, real_client = self._get_client()
        
        # 步骤 2：沿着 attr_path 导航到最终的 callable
        target = real_client
        for attr in self._attr_path:
            target = getattr(target, attr)
        
        # 步骤 3：复用现有 ApiCaller 逻辑执行调用
        caller = ApiCaller(
            apikey=apikey,
            apikey_manager=apikey._apikey_manager,
            call_method=target,
            reach_limit_exc=self._reach_limit_exc,
        )
        return caller(*args, **kwargs)


class DummyClient(object):
    def __init__(self):
        self._apikey_manager = None
    
    def __getattr__(self, item):
        """第一层拦截 —— 返回 ChainProxy（而非直接返回 ApiCaller）"""
        manager = self._apikey_manager
        
        # 定义延迟获取 client 的闭包
        def client_getter():
            apikey = manager.random_one()
            return apikey, apikey._client
        
        return ChainProxy(
            client_getter=client_getter,
            attr_path=[item],
            reach_limit_exc=manager.reach_limit_exc,
        )


# ApiCaller 类保持不变 —— 完全向后兼容
class ApiCaller(object):
    # ... 现有代码无需任何修改 ...
```

### 3.2 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Key 选择时机 | **仅在 `__call__` 时** | 避免属性访问期间频繁随机选择；保证一次完整调用只消耗一个 key |
| 中间状态是否缓存 | **不缓存** | 每次 `.a.b.c` 都重新构建 ChainProxy，开销极低且避免状态不一致 |
| `_attr_path` 数据结构 | **列表 `list[str]`** | 轻量、可序列化、易于调试；最大深度通常 < 10 |
| `client_getter` 闭包 | **捕获 manager 引用** | 保证每次调用获取最新状态（key 可能已被移除） |
| 向后兼容 | **ApiCaller 不变** | 现有测试全部通过，无需改动 |

### 3.3 调用流程对比

```
=== 修改前（1 层限制）===
dummyclient.coins.simple.price.get(ids="btc")
       │
       ▼
DummyClient.__getattr__("coins")
  → ApiCaller(call_method=client.coins)     ← 返回的是 coins 资源对象，不是方法
       │
       ▼
ApiCaller.__getattr__("simple")             ← AttributeError! 💥


=== 修改后（无限层支持）===
dummyclient.coins.simple.price.get(ids="btc")
       │
       ▼
DummyClient.__getattr__("coins")
  → ChainProxy(path=["coins"])              ← 中间节点，继续导航
       │
       ▼
ChainProxy.__getattr__("simple")
  → ChainProxy(path=["coins","simple"])
       │
       ▼
ChainProxy.__getattr__("price")
  → ChainProxy(path=["coins","simple","price"])
       │
       ▼
ChainProxy.__call__(ids="btc")             ← 到达终点！开始执行
  ├── random_one() → 选出 key_A
  ├── 沿 path 导航: client.coins.simple.price → 得到 price 方法
  └── ApiCaller(key_A, price_method)(ids="btc") → 执行 + 统计 ✅
```

---

## 4. 需要改动的文件清单

| 文件 | 改动范围 | 说明 |
|------|---------|------|
| `apipool/manager.py` | **新增** `ChainProxy` 类 (~30 行) | 属性链中间代理 |
| `apipool/manager.py` | **修改** `DummyClient.__getattr__` (~5 行) | 改为返回 `ChainProxy` |
| `apipool/manager.py` | **不改动** `ApiCaller` | 保持原样，100% 兼容 |
| `tests/test_apipool.py` | **新增** 多层属性链测试用例 | 验证 2/3/4 层调用 |
| `examples/` | **新增** `coingecko_example.py` | 展示 CoinGecko SDK 集成 |

**预估工作量**: 核心 ~40 行代码 + ~80 行测试 = 半个工作日

---

## 5. 测试用例要求

### 5.1 必须通过的测试矩阵

```python
class TestChainCallSupport:
    '''新增测试类：验证多层属性链兼容性'''
    
    def test_single_level_still_works(self):
        """回归测试：1 层调用仍然正常（向后兼容）"""
        result = dummyclient.get_lat_lng_by_address("New York")
        assert result == {"lat": 40.762882, "lng": -73.973700}
    
    def test_two_level_chain(self):
        """2 层属性链：resource.method()"""
        # 假设 mock client 有 nested.get_data()
        result = dummyclient.nested.get_data(id="abc")
        assert result is not None
    
    def test_three_level_chain(self):
        """3 层属性链：group.resource.method()"""
        result = dummyclient.api.v1.users_list()
        assert result is not None
    
    def test_four_level_chain_coin_gecko_style(self):
        """4 层属性链（模拟 CoinGecko SDK）"""
        result = dummyclient.coins.simple.price.get(
            ids="bitcoin", vs_currencies="usd"
        )
        assert "bitcoin" in result
    
    def test_deep_chain_rotation(self):
        """深层链调用中 key 正确轮换"""
        keys_used = set()
        for _ in range(20):
            dummyclient.a.b.c.d.e.call()
            # 验证多次调用使用了不同的 key
        
        assert len(keys_used) > 1  # 至少有 2 个 key 参与了轮换
    
    def test_deep_chain_error_handling(self):
        """深层链中的异常正确处理"""
        # 普通异常不移除 key
        with pytest.raises(ValueError):
            dummyclient.a.b.c.raise_error()
        assert len(manager.apikey_chain) == original_count
        
        # 限额异常移除 key
        with pytest.raises(ReachLimitError):
            dummyclient.a.b.c.raise_reach_limit_error()
        assert len(manager.apikey_chain) == original_count - 1
    
    def test_chain_proxy_repr(self):
        """ChainProxy 有良好的 repr 用于调试"""
        proxy = dummyclient.coins
        assert "coins" in repr(proxy)
        proxy2 = proxy.simple
        assert "coins" in repr(proxy2) and "simple" in repr(proxy2)
```

### 5.2 边界条件测试

| 场景 | 预期行为 |
|------|---------|
| 空属性链（直接 `dummyclient()`） | TypeError 或合理错误提示 |
| 属性链指向非 callable 的普通属性 | 返回该属性值或抛出 AttributeError |
| 属性链中间某环节不存在 | 正常抛出 AttributeError，附带路径信息 |
| 并发多协程同时调用不同链路 | 各自独立选择 key，互不影响 |
| `ChainProxy` 被 pickle/深拷贝 | 不需要支持（代理对象通常不需要序列化） |

---

## 6. 版本与发布建议

### 6.1 版本号

| 版本 | 内容 | 兼容性 |
|------|------|--------|
| **1.1.0** | 新增 `ChainProxy`，`DummyClient` 支持多层属性链 | **100% 向后兼容** |
| 1.2.0（未来） | 可选：增加 `max_depth` 配置、属性链缓存优化 | - |

### 6.2 更新日志模板

```markdown
## [1.1.0] - 2026-04-XX

### Added
- `ChainProxy`: 新增属性链中间代理类，支持任意深度嵌套属性访问 (#XX)
- `DummyClient.__getattr__`: 改为返回 ChainProxy 以支持多层属性链 (#XX)

### Changed
- `DummyClient` 现在可以正确代理具有深层嵌套结构的 API 客户端
  （如 coingecko-sdk, stripe, openai 等）

### Tested
- 新增 TestChainCallSupport 测试类，覆盖 1~4 层属性链
- 全部现有测试用例 100% 通过（向后兼容验证）
```

---

## 7. 集成方视角（MarketDataBase）

### 7.1 修复前（当前 workaround）

修复前我们被迫绕过 `dummyclient`，手动管理轮换：

```python
# 当前 workaround — 丑陋且易错
async def _call_with_rotation(manager, method_name, *args, **kwargs):
    picked = manager.random_one()          # 手动选 key
    key_name = picked.primary_key
    client = picked._client
    
    parts = method_name.split(".")
    obj = client
    for part in parts[:-1]:                # 手动导航属性链
        obj = getattr(obj, part)
    method = getattr(obj, parts[-1])
    
    try:
        result = await method(*args, **kwargs)
        manager.stats.add_event(key_name, 1)  # 手动记统计
        return result, key_name
    except Exception as e:                  # 手动处理异常和淘汰
        if "429" in str(e).lower():
            manager.remove_one(key_name)
        raise

# 使用方式：
result, key = await _call_with_rotation(manager, "coins.simple.price.get", ids="btc")
```

### 7.2 修复后（期望用法）

```python
# 修复后 — 自然优雅，符合直觉
result = await manager.dummyclient.coins.simple.price.get(ids="bitcoin", vs_currencies="usd")
# 自动完成：key 轮换 → 统计记录 → 达限淘汰
```

### 7.3 影响范围

此需求影响所有使用 **嵌套式 SDK 设计** 的 apipool-ng 用户，包括但不限于：
- 加密货币数据服务（CoinGecko SDK, DeFi SDK）
- 云服务 AWS/GCP/Azure SDK（Boto3 等）
- 支付网关（Stripe, PayPal SDK）
- AI 服务（OpenAI, Anthropic SDK）
- 社交媒体 API（Twitter API v2, Slack SDK）

---

## 附录 A：完整的 CoinGecko SDK 属性树参考

```
AsyncCoingecko (client)
├── ping                          → AsyncPingResource
│   └── get()                     → {"gecko_says": "(V3) To the Moon!"}
├── search                        → AsyncSearchResource
│   └── get(query="...")          
├── coins                         
│   ├── list                      → AsyncCoinsListResource
│   │   └── get(include_platform=False) → List[Coin]
│   └── simple                   
│       └── price                 → AsyncPriceResource
│           └── get(ids=..., vs_currencies=...) → Dict
├── contract                     
│   └── get(contract_address=...) → TokenDetail
├── simple                       
│   ├── price                     → AsyncSimplePriceResource
│   │   └── get(ids=..., vs_currencies=...)
│   └── token_price               
│       └── get(...)
└── ...
```

**最大属性深度 = 4** (`dummyclient.coins.simple.price.get(...)`)
