<template>
  <div>
    <t-row :gutter="[16, 16]">
      <t-col :span="3">
        <t-card class="stat-card" :bordered="false">
          <div class="stat-icon" style="background: #e8f5e9"><t-icon name="call" size="24px" style="color: #4caf50" /></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.total_calls }}</div>
            <div class="stat-label">总调用次数</div>
          </div>
        </t-card>
      </t-col>
      <t-col :span="3">
        <t-card class="stat-card" :bordered="false">
          <div class="stat-icon" style="background: #e3f2fd"><t-icon name="check-circle" size="24px" style="color: #2196f3" /></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.success_calls }}</div>
            <div class="stat-label">成功调用</div>
          </div>
        </t-card>
      </t-col>
      <t-col :span="3">
        <t-card class="stat-card" :bordered="false">
          <div class="stat-icon" style="background: #fce4ec"><t-icon name="lock-on" size="24px" style="color: #e91e63" /></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.active_keys }}</div>
            <div class="stat-label">活跃 Key</div>
          </div>
        </t-card>
      </t-col>
      <t-col :span="3">
        <t-card class="stat-card" :bordered="false">
          <div class="stat-icon" style="background: #fff3e0"><t-icon name="server" size="24px" style="color: #ff9800" /></div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.active_pools }}</div>
            <div class="stat-label">活跃池</div>
          </div>
        </t-card>
      </t-col>
    </t-row>

    <t-card title="快速操作" :bordered="false" style="margin-top: 16px">
      <t-row :gutter="[16, 16]">
        <t-col :span="4">
          <t-button block size="large" variant="outline" @click="$router.push('/keys')">
            <t-icon name="add" style="margin-right: 4px" /> 添加 API Key
          </t-button>
        </t-col>
        <t-col :span="4">
          <t-button block size="large" variant="outline" @click="$router.push('/pools')">
            <t-icon name="server" style="margin-right: 4px" /> 创建密钥池
          </t-button>
        </t-col>
        <t-col :span="4">
          <t-button block size="large" variant="outline" @click="loadStats">
            <t-icon name="refresh" style="margin-right: 4px" /> 刷新数据
          </t-button>
        </t-col>
      </t-row>
    </t-card>

    <t-card title="SDK 调用示例" :bordered="false" style="margin-top: 16px">
      <t-tabs>
        <t-tab-panel value="python" label="Python SDK">
          <div class="code-block">
            <pre><code>from apipool import connect, login

# 方式1: 已有 token
manager = connect("http://localhost:8000", "my-pool", "your-jwt-token")
result = manager.dummyclient.some_method()

# 方式2: 用户名密码登录
tokens = login("http://localhost:8000", "username", "password")
manager = connect("http://localhost:8000", "my-pool", tokens["access_token"])</code></pre>
          </div>
        </t-tab-panel>
        <t-tab-panel value="curl" label="cURL">
          <div class="code-block">
            <pre><code># 获取 Token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 代理调用 (invoke)
curl -X POST http://localhost:8000/api/v1/proxy/my-pool/invoke \
  -H "Authorization: Bearer &lt;token&gt;" \
  -H "Content-Type: application/json" \
  -d '{"attr_path":["some_method"],"args":[],"kwargs":{}}'

# 代理调用 (call)
curl -X POST http://localhost:8000/api/v1/proxy/my-pool/call \
  -H "Authorization: Bearer &lt;token&gt;" \
  -H "Content-Type: application/json" \
  -d '{"method_chain":"some_method","args":[],"kwargs":{}}'</code></pre>
          </div>
        </t-tab-panel>
      </t-tabs>
    </t-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listPools } from '@/api/pools'
import { getSuccessRate } from '@/api/stats'

const stats = ref({
  total_calls: 0,
  success_calls: 0,
  failed_calls: 0,
  active_keys: 0,
  active_pools: 0,
})

async function loadStats() {
  try {
    const poolsRes = await listPools({ page: 1, page_size: 100 })
    const pools = poolsRes.data.items
    stats.value.active_pools = pools.filter(p => p.is_active).length

    let totalCalls = 0
    let successCalls = 0
    let failedCalls = 0
    let activeKeys = 0

    for (const pool of pools) {
      try {
        const res = await getSuccessRate(pool.identifier, { seconds: 86400 })
        const summary = res.data.summary
        totalCalls += summary.total_calls
        successCalls += summary.success_count
        failedCalls += summary.failed_count
        activeKeys += res.data.by_key.length
      } catch {
        // Individual pool stats may fail, skip
      }
    }

    stats.value.total_calls = totalCalls
    stats.value.success_calls = successCalls
    stats.value.failed_calls = failedCalls
    stats.value.active_keys = activeKeys
  } catch {
    // Stats might not be available yet, use defaults
  }
}

onMounted(loadStats)
</script>

<style scoped>
.stat-card {
  display: flex;
  align-items: center;
  padding: 20px;
}

.stat-card :deep(.t-card__body) {
  display: flex;
  align-items: center;
  width: 100%;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 16px;
  flex-shrink: 0;
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--td-text-color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--td-text-color-secondary);
  margin-top: 4px;
}

.code-block {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
}

.code-block pre {
  margin: 0;
}

.code-block code {
  color: #d4d4d4;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
}
</style>
