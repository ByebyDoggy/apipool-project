<template>
  <div>
    <t-card :bordered="false">
      <template #header>
        <div class="card-header">
          <t-space>
            <t-button variant="outline" @click="$router.push('/pools')">
              <t-icon name="chevron-left" style="margin-right: 4px" /> 返回列表
            </t-button>
            <span style="font-size: 18px; font-weight: 600">{{ pool?.name || '密钥池详情' }}</span>
          </t-space>
          <t-space>
            <t-button
              v-if="activeTab === 'members'"
              theme="primary"
              @click="showAddMemberDialog = true"
            >
              <t-icon name="add" style="margin-right: 4px" /> 添加成员
            </t-button>
          </t-space>
        </div>
      </template>

      <t-loading :loading="loading">
        <t-tabs v-model="activeTab">
          <!-- Tab 1: Basic Info -->
          <t-tab-panel value="info" label="基本信息">
            <t-descriptions v-if="pool" :column="3" bordered style="margin-top: 16px">
              <t-descriptions-item label="标识符">{{ pool.identifier }}</t-descriptions-item>
              <t-descriptions-item label="名称">{{ pool.name }}</t-descriptions-item>
              <t-descriptions-item label="状态">
                <t-tag :theme="pool.is_active ? 'success' : 'default'" variant="light">{{ pool.is_active ? '启用' : '停用' }}</t-tag>
              </t-descriptions-item>
              <t-descriptions-item label="成员数">{{ pool.member_count }}</t-descriptions-item>
              <t-descriptions-item label="轮转策略">
                <t-tag variant="light">{{ strategyLabel(pool.rotation_strategy) }}</t-tag>
              </t-descriptions-item>
              <t-descriptions-item label="限速异常类">
                <t-tag v-if="pool.reach_limit_exception" variant="light">{{ pool.reach_limit_exception }}</t-tag>
                <t-tag v-else variant="outline">任意异常 (Exception)</t-tag>
              </t-descriptions-item>
              <t-descriptions-item label="描述" :span="2">{{ pool.description || '-' }}</t-descriptions-item>
            </t-descriptions>

            <h3 style="margin: 24px 0 12px">SDK 调用示例</h3>
            <div class="code-block">
              <pre><code>from apipool import connect

manager = connect("http://localhost:8000", "{{ pool?.identifier || 'pool-id' }}", "your-jwt-token")
result = manager.dummyclient.some_method()</code></pre>
            </div>
          </t-tab-panel>

          <!-- Tab 2: Members -->
          <t-tab-panel value="members" label="成员列表">
            <t-table
              v-if="mounted"
              :data="pool?.members || []"
              :columns="memberColumns"
              row-key="key_identifier"
              hover
              stripe
              style="margin-top: 16px"
            >
              <template #verification_status="{ row }">
                <t-tag
                  :theme="verificationTheme(row.verification_status)"
                  variant="light"
                  size="small"
                >
                  {{ verificationLabel(row.verification_status) }}
                </t-tag>
              </template>
              <template #op="{ row }">
                <t-link theme="danger" @click="onRemoveMember(row)">移除</t-link>
              </template>
            </t-table>
          </t-tab-panel>

          <!-- Tab 3: Config -->
          <t-tab-panel value="config" label="配置管理">
            <t-loading :loading="configLoading">
              <div v-if="configData" style="margin-top: 16px">
                <!-- Pool-level settings (not in pool_config) -->
                <h4 class="section-title">池级别设置</h4>
                <t-form :data="configForm" label-width="140px" layout="inline" class="config-form">
                  <t-form-item label="轮转策略">
                    <t-select v-model="configForm.rotation_strategy" style="width: 220px">
                      <t-option value="random" label="随机 (random)" />
                      <t-option value="round_robin" label="轮询 (round_robin)" />
                      <t-option value="least_used" label="最少使用 (least_used)" />
                    </t-select>
                  </t-form-item>
                  <t-form-item label="限速异常类">
                    <t-input
                      v-model="configForm.reach_limit_exception"
                      placeholder="留空则任意异常都触发轮转（默认）"
                      style="width: 320px"
                    />
                  </t-form-item>
                </t-form>

                <t-divider />

                <!-- pool_config: Request settings -->
                <h4 class="section-title">请求配置</h4>
                <t-form ref="configFormRef" :data="configForm" :rules="configRules" label-width="140px" class="config-form">
                  <t-row :gutter="24">
                    <t-col :span="6">
                      <t-form-item label="并发数" name="concurrency">
                        <t-input-number
                          v-model="configForm.concurrency"
                          :min="0"
                          :max="1000"
                          theme="normal"
                          style="width: 100%"
                        />
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="超时时间(秒)" name="timeout">
                        <t-input-number
                          v-model="configForm.timeout"
                          :min="1"
                          :max="600"
                          :decimal-places="1"
                          theme="normal"
                          style="width: 100%"
                        />
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="速率限制" name="rate_limit">
                        <t-input-number
                          v-model="configForm.rate_limit"
                          :min="0"
                          :max="100000"
                          theme="normal"
                          style="width: 100%"
                        />
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="限制间隔(秒)" name="rate_limit_interval">
                        <t-input-number
                          v-model="configForm.rate_limit_interval"
                          :min="1"
                          :max="86400"
                          theme="normal"
                          style="width: 100%"
                        />
                      </t-form-item>
                    </t-col>
                  </t-row>

                  <t-row :gutter="24">
                    <t-col :span="6">
                      <t-form-item label="失败重试" name="retry_on_failure">
                        <t-switch v-model="configForm.retry_on_failure" />
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="最大重试次数" name="max_retries">
                        <t-input-number
                          v-model="configForm.max_retries"
                          :min="0"
                          :max="50"
                          theme="normal"
                          style="width: 100%"
                          :disabled="!configForm.retry_on_failure"
                        />
                      </t-form-item>
                    </t-col>
                  </t-row>
                </t-form>

                <t-divider />

                <!-- pool_config: Batch execution settings -->
                <h4 class="section-title">批量执行配置</h4>
                <t-form :data="configForm" :rules="configRules" label-width="140px" class="config-form">
                  <t-row :gutter="24">
                    <t-col :span="6">
                      <t-form-item label="批量失败重试" name="batch_retry_on_failure">
                        <t-select v-model="configForm.batch_retry_on_failure" style="width: 100%">
                          <t-option :value="true" label="启用" />
                          <t-option :value="false" label="禁用" />
                          <t-option :value="null" label="跟随「失败重试」" />
                        </t-select>
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="批量最大重试" name="batch_max_retries">
                        <t-select v-model="configForm.batch_max_retries" style="width: 100%">
                          <t-option
                            v-for="n in [0, 1, 2, 3, 5, 10, 20]"
                            :key="'bmr-' + n"
                            :value="n"
                            :label="String(n)"
                          />
                          <t-option :value="null" label="跟随「最大重试次数」" />
                        </t-select>
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="封禁阈值" name="ban_threshold">
                        <t-input-number
                          v-model="configForm.ban_threshold"
                          :min="1"
                          :max="100"
                          theme="normal"
                          style="width: 100%"
                        />
                      </t-form-item>
                    </t-col>
                    <t-col :span="6">
                      <t-form-item label="封禁时长(秒)" name="ban_duration">
                        <t-input-number
                          v-model="configForm.ban_duration"
                          :min="10"
                          :max="86400"
                          :decimal-places="0"
                          theme="normal"
                          style="width: 100%"
                        />
                      </t-form-item>
                    </t-col>
                  </t-row>
                </t-form>

                <t-divider />

                <!-- Custom config (JSON editor) -->
                <h4 class="section-title">自定义配置</h4>
                <t-form label-width="140px" class="config-form">
                  <t-form-item label="扩展参数 (JSON)">
                    <t-textarea
                      v-model="customJsonStr"
                      placeholder='{"custom_header": "X-Custom: value"}'
                      :autosize="{ minRows: 3, maxRows: 10 }"
                    />
                  </t-form-item>
                </t-form>

                <!-- Action buttons -->
                <div class="config-actions">
                  <t-space>
                    <t-button theme="primary" :loading="saving" @click="onSaveConfig">
                      <t-icon name="check" style="margin-right: 4px" /> 保存配置
                    </t-button>
                    <t-button variant="outline" @click="onResetConfig">
                      <t-icon name="rollback" style="margin-right: 4px" /> 重置
                    </t-button>
                  </t-space>
                </div>
              </div>

              <t-empty v-else description="暂无配置数据" />
            </t-loading>
          </t-tab-panel>

          <!-- Tab 4: Success Rate -->
          <t-tab-panel value="stats" label="调用统计">
            <div style="margin-top: 16px">
              <div class="stats-toolbar">
                <t-select v-model="statsPeriod" style="width: 160px" @change="loadSuccessRate">
                  <t-option :value="3600" label="最近 1 小时" />
                  <t-option :value="21600" label="最近 6 小时" />
                  <t-option :value="86400" label="最近 24 小时" />
                  <t-option :value="604800" label="最近 7 天" />
                  <t-option :value="2592000" label="最近 30 天" />
                </t-select>
                <t-button variant="outline" @click="loadSuccessRate">
                  <t-icon name="refresh" style="margin-right: 4px" /> 刷新
                </t-button>
              </div>

              <t-loading :loading="statsLoading">
                <template v-if="successRateData">
                  <!-- Overview cards -->
                  <t-row :gutter="16" style="margin-bottom: 24px">
                    <t-col :span="3">
                      <div class="stat-card">
                        <div class="stat-card-title">总调用</div>
                        <div class="stat-card-value">{{ successRateData.summary.total_calls }}</div>
                      </div>
                    </t-col>
                    <t-col :span="3">
                      <div class="stat-card stat-card-success">
                        <div class="stat-card-title">成功</div>
                        <div class="stat-card-value">{{ successRateData.summary.success_count }}</div>
                      </div>
                    </t-col>
                    <t-col :span="3">
                      <div class="stat-card stat-card-danger">
                        <div class="stat-card-title">失败</div>
                        <div class="stat-card-value">{{ successRateData.summary.failed_count }}</div>
                      </div>
                    </t-col>
                    <t-col :span="3">
                      <div class="stat-card stat-card-warning">
                        <div class="stat-card-title">限速</div>
                        <div class="stat-card-value">{{ successRateData.summary.reach_limit_count }}</div>
                      </div>
                    </t-col>
                  </t-row>

                  <!-- Pool success rate progress -->
                  <div style="margin-bottom: 24px">
                    <div style="display: flex; align-items: center; margin-bottom: 8px">
                      <span style="font-weight: 600; margin-right: 12px">池整体成功率</span>
                      <t-progress
                        :percentage="successRateData.summary.success_rate"
                        :status="successRateData.summary.success_rate >= 80 ? 'success' : successRateData.summary.success_rate >= 50 ? 'warning' : 'error'"
                        :label="`${successRateData.summary.success_rate}%`"
                        style="flex: 1"
                      />
                    </div>
                  </div>

                  <!-- Per-key breakdown -->
                  <h4 class="section-title">Key 成功率明细</h4>
                  <t-table
                    :data="successRateData.by_key"
                    :columns="statsColumns"
                    row-key="key_identifier"
                    hover
                    stripe
                    size="small"
                  >
                    <template #success_rate="{ row }">
                      <t-progress
                        :percentage="row.success_rate"
                        :status="row.success_rate >= 80 ? 'success' : row.success_rate >= 50 ? 'warning' : 'error'"
                        :label="`${row.success_rate}%`"
                        size="small"
                        style="width: 120px"
                      />
                    </template>
                  </t-table>
                </template>
                <t-empty v-else description="暂无调用统计数据" />
              </t-loading>
            </div>
          </t-tab-panel>

          <!-- Tab 5: Call Logs -->
          <t-tab-panel value="logs" label="调用日志">
            <div style="margin-top: 16px">
              <div class="stats-toolbar">
                <t-select v-model="logsPeriod" style="width: 140px" @change="loadCallLogs">
                  <t-option :value="3600" label="1 小时" />
                  <t-option :value="21600" label="6 小时" />
                  <t-option :value="86400" label="24 小时" />
                  <t-option :value="604800" label="7 天" />
                  <t-option :value="2592000" label="30 天" />
                </t-select>
                <t-select
                  v-model="logsKeyFilter"
                  placeholder="筛选 Key"
                  clearable
                  filterable
                  style="width: 200px"
                  @change="loadCallLogs"
                >
                  <t-option v-for="m in (pool?.members || [])" :key="m.key_identifier" :value="m.key_identifier" :label="m.key_identifier" />
                </t-select>
                <t-select v-model="logsStatusFilter" placeholder="状态" clearable style="width: 120px" @change="loadCallLogs">
                  <t-option value="success" label="成功" />
                  <t-option value="failed" label="失败" />
                  <t-option value="reach_limit" label="限速" />
                </t-select>
                <t-button variant="outline" @click="loadCallLogs">
                  <t-icon name="refresh" style="margin-right: 4px" /> 刷新
                </t-button>
              </div>

              <t-loading :loading="logsLoading">
                <t-table
                  v-if="callLogData"
                  :data="callLogData.items"
                  :columns="logColumns"
                  row-key="id"
                  hover
                  stripe
                  size="small"
                >
                  <template #status="{ row }">
                    <t-tag
                      :theme="logStatusTheme(row.status)"
                      variant="light"
                      size="small"
                    >
                      {{ logStatusLabel(row.status) }}
                    </t-tag>
                  </template>
                </t-table>
                <t-empty v-else description="暂无调用日志" />
                <div v-if="callLogData && callLogData.total > 0" style="margin-top: 12px; display: flex; justify-content: flex-end">
                  <t-pagination
                    v-model:current="logsPage"
                    :total="callLogData.total"
                    :page-size="logsPageSize"
                    show-jumper
                    @change="loadCallLogs"
                  />
                </div>
              </t-loading>
            </div>
          </t-tab-panel>
        </t-tabs>
      </t-loading>
    </t-card>

    <!-- Add Member Dialog -->
    <t-dialog
      v-model:visible="showAddMemberDialog"
      header="添加成员 Key"
      :confirm-btn="{ loading: addMemberLoading }"
      @confirm="onAddMembers"
      @close="selectedKeyIdentifiers = []"
    >
      <t-select v-model="selectedKeyIdentifiers" multiple placeholder="选择要添加的 Key">
        <t-option v-for="k in availableKeys" :key="k.identifier" :value="k.identifier" :label="`${k.identifier} (${k.client_type})`" />
      </t-select>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getPool, addMembers, removeMember, getPoolConfig, updatePool,
  type PoolResponse, type PoolMemberResponse, type PoolConfigResponse,
} from '@/api/pools'
import { listKeys, type ApiKeyResponse } from '@/api/keys'
import { getSuccessRate, getCallLogs, type SuccessRateResponse, type CallLogResponse } from '@/api/stats'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { extractErrorMessage } from '@/api/errors'

const route = useRoute()
const router = useRouter()
const poolIdentifier = route.params.id as string

const pool = ref<PoolResponse | null>(null)
const availableKeys = ref<ApiKeyResponse[]>([])
const loading = ref(false)
const mounted = ref(false)
const showAddMemberDialog = ref(false)
const addMemberLoading = ref(false)
const selectedKeyIdentifiers = ref<string[]>([])

// Config tab state
const configData = ref<PoolConfigResponse | null>(null)
const configLoading = ref(false)
const saving = ref(false)
const customJsonStr = ref('{}')

const configForm = ref({
  // Pool-level
  rotation_strategy: 'random' as string,
  reach_limit_exception: '' as string,
  // pool_config fields
  concurrency: 0,
  timeout: 30.0,
  rate_limit: 0,
  rate_limit_interval: 60,
  retry_on_failure: false,
  max_retries: 0,
  batch_retry_on_failure: null as boolean | null,
  batch_max_retries: null as number | null,
  ban_threshold: 3,
  ban_duration: 300,
})

const configRules = {
  concurrency: [{ validator: (val: number) => val >= 0, message: '并发数不能为负数' }],
  timeout: [{ validator: (val: number) => val >= 1, message: '超时时间至少 1 秒' }],
  rate_limit: [{ validator: (val: number) => val >= 0, message: '速率限制不能为负数' }],
  rate_limit_interval: [{ validator: (val: number) => val >= 1, message: '限制间隔至少 1 秒' }],
  ban_threshold: [{ validator: (val: number) => val >= 1, message: '封禁阈值至少为 1' }],
  ban_duration: [{ validator: (val: number) => val >= 10, message: '封禁时长至少 10 秒' }],
}

// Active tab
const activeTab = ref((route.query.tab as string) || 'info')

watch(activeTab, (val) => {
  router.replace({ query: { tab: val } })
  if (val === 'config' && !configData.value) {
    loadConfig()
  }
  if (val === 'stats') {
    loadSuccessRate()
  }
  if (val === 'logs') {
    loadCallLogs()
  }
})

// ── Stats state ──────────────────────────────────────────────────────────
const statsLoading = ref(false)
const successRateData = ref<SuccessRateResponse | null>(null)
const statsPeriod = ref(86400)

const statsColumns = [
  { colKey: 'key_identifier', title: '标识符', width: 180, ellipsis: true },
  { colKey: 'alias', title: '别名', width: 120, ellipsis: true },
  { colKey: 'total_calls', title: '总调用', width: 80 },
  { colKey: 'success_count', title: '成功', width: 80 },
  { colKey: 'failed_count', title: '失败', width: 80 },
  { colKey: 'reach_limit_count', title: '限速', width: 80 },
  { colKey: 'success_rate', title: '成功率', width: 160, cell: 'success_rate' },
]

async function loadSuccessRate() {
  statsLoading.value = true
  try {
    const res = await getSuccessRate(poolIdentifier, { seconds: statsPeriod.value })
    successRateData.value = res.data
  } catch {
    MessagePlugin.error('加载调用统计失败')
  } finally {
    statsLoading.value = false
  }
}

// ── Call logs state ──────────────────────────────────────────────────────
const logsLoading = ref(false)
const callLogData = ref<CallLogResponse | null>(null)
const logsPeriod = ref(86400)
const logsKeyFilter = ref<string | undefined>(undefined)
const logsStatusFilter = ref<string | undefined>(undefined)
const logsPage = ref(1)
const logsPageSize = ref(20)

const logColumns = [
  { colKey: 'finished_at', title: '时间', width: 180 },
  { colKey: 'key_identifier', title: 'Key 标识符', width: 180, ellipsis: true },
  { colKey: 'alias', title: '别名', width: 120, ellipsis: true },
  { colKey: 'status', title: '状态', width: 100, cell: 'status' },
]

function logStatusTheme(s: string) {
  if (s === 'success') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'reach_limit') return 'warning'
  return 'default'
}

function logStatusLabel(s: string) {
  const map: Record<string, string> = { success: '成功', failed: '失败', reach_limit: '限速' }
  return map[s] || s
}

async function loadCallLogs() {
  logsLoading.value = true
  try {
    const params: Record<string, any> = {
      seconds: logsPeriod.value,
      page: logsPage.value,
      page_size: logsPageSize.value,
    }
    if (logsKeyFilter.value) params.key_identifier = logsKeyFilter.value
    if (logsStatusFilter.value) params.status = logsStatusFilter.value
    const res = await getCallLogs(poolIdentifier, params)
    callLogData.value = res.data
  } catch {
    MessagePlugin.error('加载调用日志失败')
  } finally {
    logsLoading.value = false
  }
}

const memberColumns = [
  { colKey: 'key_identifier', title: '标识符', width: 180 },
  { colKey: 'alias', title: '别名', width: 140 },
  { colKey: 'priority', title: '优先级', width: 80 },
  { colKey: 'weight', title: '权重', width: 80 },
  { colKey: 'verification_status', title: '验证状态', width: 100, cell: 'verification_status' },
  { colKey: 'op', title: '操作', width: 80, cell: 'op' },
]

function strategyLabel(s: string) {
  const map: Record<string, string> = { random: '随机', round_robin: '轮询', least_used: '最少使用' }
  return map[s] || s
}

function verificationTheme(s: string) {
  if (s === 'valid' || s === 'verified') return 'success'
  if (s === 'unknown' || s === 'unverified') return 'warning'
  return 'danger'
}

function verificationLabel(s: string) {
  const map: Record<string, string> = { valid: '已验证', verified: '已验证', unknown: '未知', unverified: '未验证', invalid: '无效', rate_limited: '限速' }
  return map[s] || s
}

async function loadPool() {
  loading.value = true
  try {
    const res = await getPool(poolIdentifier)
    pool.value = res.data
  } catch {
    MessagePlugin.error('加载池详情失败')
  } finally {
    loading.value = false
  }
}

async function loadAvailableKeys() {
  try {
    const res = await listKeys({ page_size: 100 })
    const memberIds = new Set((pool.value?.members || []).map((m: PoolMemberResponse) => m.key_identifier))
    availableKeys.value = res.data.items.filter((k) => !memberIds.has(k.identifier))
  } catch {
    // ignore
  }
}

async function loadConfig() {
  configLoading.value = true
  try {
    const res = await getPoolConfig(poolIdentifier)
    configData.value = res.data
    applyConfigToForm(res.data)
  } catch {
    MessagePlugin.error('加载配置失败')
  } finally {
    configLoading.value = false
  }
}

function applyConfigToForm(data: PoolConfigResponse) {
  const pc = data.pool_config || {}
  configForm.value = {
    rotation_strategy: data.rotation_strategy || 'random',
    reach_limit_exception: data.reach_limit_exception || '',
    concurrency: pc.concurrency ?? 0,
    timeout: pc.timeout ?? 30.0,
    rate_limit: pc.rate_limit ?? 0,
    rate_limit_interval: pc.rate_limit_interval ?? 60,
    retry_on_failure: pc.retry_on_failure ?? false,
    max_retries: pc.max_retries ?? 0,
    batch_retry_on_failure: pc.batch_retry_on_failure ?? null,
    batch_max_retries: pc.batch_max_retries ?? null,
    ban_threshold: pc.ban_threshold ?? 3,
    ban_duration: pc.ban_duration ?? 300,
  }
  try {
    customJsonStr.value = JSON.stringify(pc.custom || {}, null, 2)
  } catch {
    customJsonStr.value = '{}'
  }
}

function onResetConfig() {
  if (configData.value) {
    applyConfigToForm(configData.value)
    MessagePlugin.info('配置已重置')
  }
}

async function onSaveConfig() {
  // Validate custom JSON
  let customObj: Record<string, any> = {}
  if (customJsonStr.value.trim()) {
    try {
      customObj = JSON.parse(customJsonStr.value.trim())
      if (typeof customObj !== 'object' || Array.isArray(customObj) || customObj === null) {
        MessagePlugin.warning('自定义配置必须是有效的 JSON 对象')
        return
      }
    } catch {
      MessagePlugin.warning('自定义配置 JSON 格式错误，请检查')
      return
    }
  }

  saving.value = true
  try {
    const poolConfig: Record<string, any> = {
      concurrency: configForm.value.concurrency,
      timeout: configForm.value.timeout,
      rate_limit: configForm.value.rate_limit,
      rate_limit_interval: configForm.value.rate_limit_interval,
      retry_on_failure: configForm.value.retry_on_failure,
      max_retries: configForm.value.max_retries,
      ban_threshold: configForm.value.ban_threshold,
      ban_duration: configForm.value.ban_duration,
    }
    if (configForm.value.batch_retry_on_failure !== null) {
      poolConfig.batch_retry_on_failure = configForm.value.batch_retry_on_failure
    }
    if (configForm.value.batch_max_retries !== null) {
      poolConfig.batch_max_retries = configForm.value.batch_max_retries
    }
    if (Object.keys(customObj).length > 0) {
      poolConfig.custom = customObj
    }

    await updatePool(poolIdentifier, {
      rotation_strategy: configForm.value.rotation_strategy,
      reach_limit_exception: configForm.value.reach_limit_exception || null,
      pool_config: poolConfig,
    })

    MessagePlugin.success('配置保存成功')
    // Reload both pool info and config
    await loadPool()
    await loadConfig()
  } catch (err: any) {
    MessagePlugin.error(extractErrorMessage(err, '保存配置失败'))
  } finally {
    saving.value = false
  }
}

function onRemoveMember(row: PoolMemberResponse) {
  const dialog = DialogPlugin.confirm({
    header: '确认移除',
    body: `确定要从池中移除 Key "${row.key_identifier}" 吗？`,
    confirmBtn: { theme: 'danger', content: '移除' },
    onConfirm: async () => {
      try {
        await removeMember(poolIdentifier, row.key_identifier)
        MessagePlugin.success('已移除')
        loadPool()
      } catch {
        MessagePlugin.error('移除失败')
      }
      dialog.destroy()
    },
  })
}

async function onAddMembers() {
  if (selectedKeyIdentifiers.value.length === 0) {
    MessagePlugin.warning('请选择要添加的 Key')
    return
  }
  addMemberLoading.value = true
  try {
    await addMembers(poolIdentifier, { key_identifiers: selectedKeyIdentifiers.value })
    MessagePlugin.success('添加成功')
    showAddMemberDialog.value = false
    selectedKeyIdentifiers.value = []
    loadPool()
  } catch (err: any) {
    MessagePlugin.error(extractErrorMessage(err, '添加失败'))
  } finally {
    addMemberLoading.value = false
  }
}

onMounted(async () => {
  await nextTick()
  mounted.value = true
  await loadPool()
  loadAvailableKeys()
  if (activeTab.value === 'config') {
    loadConfig()
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
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

.section-title {
  margin: 0 0 16px;
  font-size: 15px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.config-form {
  max-width: 960px;
}

.config-actions {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--td-border-level-1-color);
}

.stats-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}

.stat-card {
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-border-level-1-color);
  border-radius: 6px;
  padding: 12px 16px;
  text-align: center;
}

.stat-card-title {
  font-size: 12px;
  color: var(--td-text-color-secondary);
  margin-bottom: 4px;
}

.stat-card-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.stat-card-success .stat-card-value {
  color: var(--td-success-color);
}

.stat-card-danger .stat-card-value {
  color: var(--td-error-color);
}

.stat-card-warning .stat-card-value {
  color: var(--td-warning-color);
}
</style>
