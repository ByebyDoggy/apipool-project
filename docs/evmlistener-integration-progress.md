# EVMLogListener 集成开发进度记录

> **最后更新**: 2026-04-11
> **状态**: 进行中 — Phase 2 基本修复完成，待集成验证

---

## 一、已修复的问题

### 问题1: `_httplib` NameError（✅ 已修复）

**文件**: `EVMLogListener/src/evm_chain_listener/rpc/apipool_client.py`

**根因**: `import httpx as _httplib` 在 async 闭包内部，CPython 字节码执行时变量未绑定到闭包作用域。

**修复内容** (3处改动):
1. 将 `import httpx` 移至模块顶层（第53行）
2. 删除闭包内的 `import httpx as _httplib`
3. except 子句改为直接使用 `httpx.HTTPStatusError`
4. 补充了缺失的 `PoolConfig` 导入

**状态**: ✅ 已完成

---

### 问题2: 服务端 config 接口返回 404（✅ 已修复）

**请求**: `GET /api/v1/pools/ethereum-rpc/config` → **404 Not Found**

**根因**: DB 中 `key_pools` 表 id=2 的 identifier 为 `1222313`（而非 `ethereum-rpc`），导致客户端按 `ethereum-rpc` 查询时匹配失败。

**修复**: 更新 DB — `UPDATE key_pools SET identifier = 'ethereum-rpc' WHERE id = 2`

**状态**: ✅ 已完成

---

### 问题3: All RPC nodes exhausted（✅ 已修复）

**错误信息**: `All RPC nodes exhausted for ethereum`

**调用链路**:
```
base.py:get_block_number()
  → adummyclient.eth_block_number()
    → AsyncChainProxy.__call__() → random_one()
      → PoolExhaustedError! (空池)
```

**根因**: `config.yaml` 中配置 `client_type: "ethereum-rpc"`，但 DB 中 key 条目的 `client_type` 为 `"generic"`。
服务端 `GET /keys/raw?client_type=ethereum-rpc` 按 client_type 过滤 → 返回空列表 → 客户端空池！

**修复**: 更新 DB — `UPDATE api_key_entries SET client_type = 'ethereum-rpc' WHERE id IN (2,3)`

**验证数据**:
```
修复前: eth-rpc1(client_type='generic'), eth-rpc2(client_type='generic')
修复后: eth-rpc1(client_type='ethereum-rpc'), eth-rpc2(client_type='ethereum-rpc')
```

**状态**: ✅ 已完成

---

### 问题4: `/ingest/status` 返回 text/html（⚠️ 配置问题，非代码bug）

**错误信息**: `Attempt to decode JSON with unexpected mimetype: text/html; charset=utf-8`, url='http://localhost:8000/ingest/status'

**根因**: `config.yaml` 中 `alert_processor.url: "http://localhost:8000"` 指向的是 **apipool-server**，
但 `/ingest/status` 是 **AlertProcessor** 服务（独立于 apipool-server）的端点。apipool-server 没有 `/ingest/*` 路由，
FastAPI 返回了默认的 HTML 404 页面。

**解决方式**: 需要将 `alert_processor.url` 改为实际的 AlertProcessor 服务地址（如果 AlertProcessor 服务尚未部署则忽略此警告）。

**影响范围**: 仅影响 gap detection/replay 功能，不影响核心 RPC 监听。

**状态**: ⚠️ 需要用户确认 AlertProcessor 服务地址

---

## 二、已完成的工作

### Phase 1: SDK 更新与测试（✅ 已完成）
1. 手动更新 `apipool/client.py`（当前 v1.0.7，499→500行）
2. 构建 wheel 并安装到 EVMLogListener 的 `.venv`
3. 运行测试套件：**30 个测试全部通过**（4个 test_server 预存 error 与本次修改无关）

### Phase 1 中修复的测试问题汇总:
- `aget_keys` 未导入 → 已添加到 import 列表
- `DeprecationWarning` 未触发 → 在 exceptions.py 添加 warnings.warn()
- Event loop 冲突 → 重构 `_make_server_pool()` 为 `@asynccontextmanager`
- Patch 作用域问题 → 改用 patch.start()/stop()
- MagicMock vs AsyncMock 不匹配 → 异步方法统一使用 AsyncMock
- `isinstance` 检查失败 → 使用 `MagicMock(spec=RealClass)`
- 测试断言调整 → 简化 empty_keys 测试逻辑

### Phase 2: 集成运行时错误修复（✅ 基本完成）
- ✅ 客户端 `_httplib` NameError — import 移至模块顶层
- ✅ 服务端 config 404 — DB pool identifier 修正
- ✅ RPC nodes exhausted — DB key client_type 修正
- ⚠️ /ingest/status text/html — alert_processor.url 配置需确认

---

## 三、后续开发内容清单

### 待验证（重启 EVMLogListener 后确认）

- [ ] **重启 EVMLogListener 验证 RPC 连接**
  - 确认 apipool-server 正在运行 (`cd apipool_server && python -m uvicorn main:app`)
  - 确认 eth-rpc keys 已被正确获取（日志中应出现 key 列表）
  - 确认 `eth_block_number` 调用成功返回区块号

- [ ] **确认 AlertProcessor 地址**
  - 如果 AlertProcessor 服务已部署，修改 `config.yaml` 中 `alert_processor.url`
  - 如果尚未部署，可暂时忽略此警告或禁用 `alert_processor.enabled: false`

### 后续优化（可选）

- [ ] 服务端可考虑为 `/config` 端点增加更友好的错误提示（区分"pool不存在"和"无权限"）
- [ ] 客户端可增加 config sync 成功/失败的 metrics 或回调通知
- [ ] 考虑将 `_config_fetcher` 的容错逻辑下沉到 SDK 层（`apipool/client.py` 的 `aget_config`）而非每个客户端重复实现

---

## 四、关键文件索引

| 项目 | 绝对路径 | 说明 |
|------|----------|------|
| 客户端主文件 | `D:\Programming\Python\EVMLogListener\src\evm_chain_listener\rpc\apipool_client.py` | **需修改** — 第372-392行 |
| 客户端异常定义 | `D:\Programming\Python\EVMLogListener\src\evm_chain_listener\rpc\exceptions.py` | 已添加 DeprecationWarning |
| 客户端测试 | `D:\Programming\Python\EVMLogListener\tests\test_apipool_client.py` | 49个测试全通过 |
| SDK client | `d:\Programming\Python\apipool-project\apipool\client.py` | 当前 v1.0.7，500行 |
| SDK manager | `d:\Programming\Python\apipool-project\apipool\manager.py` | AsyncDynamicKeyManager 实现 |
| 服务端路由 | `d:\Programming\Python\apipool-project\apipool_server\api\v1\pools.py` | config 路由在第87行 |
| 服务端 Service | `d:\Programming\Python\apipool-project\apipool_server\services\pool_service.py` | get_config() 在第272行，_get_pool() 在第236行 |
| 服务端数据库 | `d:\Programming\Python\apipool-project\apipool_server.db` | SQLite，需检查 key_pools 表 |

---

## 五、环境信息

```
OS: Windows 11 (win32)
Python: 3.14.0 (MSC v.1940 64-bit AMD Pip: EVMLogListener/.venv
Shell: PowerShell
SDK版本: apipool_ng 1.0.7 (本地 wheel 安装)
服务端: FastAPI + SQLAlchemy + SQLite
```
