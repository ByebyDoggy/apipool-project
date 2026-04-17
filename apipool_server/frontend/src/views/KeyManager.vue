<template>
  <div>
    <t-card :bordered="false">
      <template #header>
        <div class="card-header">
          <span>API Key 管理</span>
          <t-space>
            <t-button theme="primary" @click="openCreate">
              <t-icon name="add" style="margin-right: 4px" /> 新增 Key
            </t-button>
          </t-space>
        </div>
      </template>

      <!-- Search & Filter Bar -->
      <div class="filter-bar">
        <t-space align="center" wrap>
          <t-input
            v-model="searchKeyword"
            placeholder="搜索标识符/别名..."
            clearable
            style="width: 240px"
            @enter="loadKeys"
            @clear="loadKeys"
          >
            <template #prefixIcon><t-icon name="search" /></template>
          </t-input>
          <t-select
            v-model="filterStatus"
            placeholder="状态"
            clearable
            style="width: 120px"
            @change="onFilterChange"
          >
            <t-option value="true" label="启用" />
            <t-option value="false" label="停用" />
          </t-select>
          <t-select
            v-model="filterVerification"
            placeholder="验证状态"
            clearable
            style="width: 140px"
            @change="onFilterChange"
          >
            <t-option value="verified" label="已验证" />
            <t-option value="unverified" label="未验证" />
            <t-option value="invalid" label="失败" />
          </t-select>
          <t-button variant="outline" @click="resetFilters">重置</t-button>
        </t-space>
      </div>

      <t-table
        v-if="mounted"
        :data="keys"
        :columns="columns"
        :loading="loading"
        row-key="identifier"
        hover
        stripe
        :pagination="{ total, current: currentPage, pageSize }"
        @page-change="onPageChange"
      >
        <template #is_active="{ row }">
          <t-switch
            :value="row.is_active"
            size="small"
            @change="(val: boolean) => onToggleActive(row, val)"
          />
        </template>
        <template #verification_status="{ row }">
          <t-tag :theme="row.verification_status === 'verified' ? 'success' : row.verification_status === 'unverified' ? 'warning' : 'danger'" variant="light" size="small">
            {{ row.verification_status === 'verified' ? '已验证' : row.verification_status === 'unverified' ? '未验证' : '失败' }}
          </t-tag>
        </template>
        <template #tags="{ row }">
          <t-tag v-for="tag in (row.tags || [])" :key="tag" size="small" variant="light" style="margin-right: 4px">{{ tag }}</t-tag>
        </template>
        <template #op="{ row }">
          <t-space size="small">
            <t-link theme="primary" @click="onViewRaw(row)">明文</t-link>
            <t-link theme="primary" @click="onVerify(row)">验证</t-link>
            <t-link theme="primary" @click="onEdit(row)">编辑</t-link>
            <t-link theme="danger" @click="onDelete(row)">删除</t-link>
          </t-space>
        </template>
      </t-table>

      <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
        <t-pagination
          v-model:current="currentPage"
          :total="total"
          :page-size="pageSize"
          show-jumper
          @change="loadKeys"
        />
      </div>
    </t-card>
    <t-dialog
      v-model:visible="showDialog"
      :header="editingKey ? '编辑 Key' : '新增 Key'"
      :confirm-btn="{ loading: dialogLoading }"
      @confirm="onSubmit"
      @close="resetForm"
    >
      <t-form ref="formRef" :data="formData" :rules="formRules" label-width="80px">
        <t-form-item label="标识符" name="identifier" v-if="!editingKey">
          <t-input v-model="formData.identifier" placeholder="唯一标识符，如 my-openai-key" />
        </t-form-item>
        <t-form-item label="别名" name="alias">
          <t-input v-model="formData.alias" placeholder="可读别名" />
        </t-form-item>
        <t-form-item label="Key 值" name="raw_key" v-if="!editingKey">
          <t-input v-model="formData.raw_key" type="password" placeholder="API Key 明文（加密存储）" />
        </t-form-item>
        <t-form-item label="标签" name="tags">
          <t-tag-input v-model="formData.tags" placeholder="输入标签后回车" />
        </t-form-item>
        <t-form-item label="描述" name="description">
          <t-textarea v-model="formData.description" placeholder="描述信息" :maxlength="200" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <!-- View Raw Key Dialog -->
    <t-dialog
      v-model:visible="showRawDialog"
      header="查看 Key 明文"
      :footer="false"
    >
      <t-space direction="vertical" :size="12" style="width: 100%" v-if="!rawRawLoading">
        <div>
          <span style="color: var(--td-text-color-secondary)">标识符：</span>
          <span style="font-weight: 600">{{ rawKeyData?.identifier }}</span>
        </div>
        <div v-if="rawKeyData?.alias">
          <span style="color: var(--td-text-color-secondary)">别名：</span>
          <span>{{ rawKeyData.alias }}</span>
        </div>
        <div>
          <span style="color: var(--td-text-color-secondary); display: block; margin-bottom: 6px">Key 明文（点击复制）：</span>
          <t-input
            :value="rawKeyData?.raw_key || ''"
            readonly
            @click="copyToClipboard(rawKeyData?.raw_key || '')"
          >
            <template #suffixIcon>
              <t-icon name="file-copy" style="cursor: pointer" />
            </template>
          </t-input>
        </div>
        <t-alert theme="warning" title="安全提示">
          请妥善保管明文 Key，避免在公共场所展示。
        </t-alert>
      </t-space>
      <div v-else style="text-align: center; padding: 24px 0">
        <t-loading size="small" /> 正在解密...
      </div>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { listKeys, createKey, updateKey, deleteKey, verifyKey, getRawKey, type ApiKeyResponse, type ApiKeyCreate, type ApiKeyUpdate } from '@/api/keys'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { extractErrorMessage } from '@/api/errors'

const keys = ref<ApiKeyResponse[]>([])
const loading = ref(false)
const mounted = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

// Search & filter state
const searchKeyword = ref('')
const filterStatus = ref<string | null>(null)
const filterVerification = ref<string | null>(null)

const showDialog = ref(false)
const dialogLoading = ref(false)
const editingKey = ref<ApiKeyResponse | null>(null)

const showRawDialog = ref(false)
const rawRawLoading = ref(false)
const rawKeyData = ref<{ identifier: string; alias: string | null; raw_key: string } | null>(null)

const formData = ref<{
  identifier: string
  alias: string
  raw_key: string
  tags: string[]
  description: string
}>({
  identifier: '',
  alias: '',
  raw_key: '',
  tags: [],
  description: '',
})

const formRules = {
  identifier: [{ required: true, message: '请输入标识符' }],
  raw_key: [{ required: true, message: '请输入 Key 值' }],
}

const columns = [
  { colKey: 'identifier', title: '标识符', width: 180, ellipsis: true },
  { colKey: 'alias', title: '别名', width: 140, ellipsis: true },
  { colKey: 'tags', title: '标签', width: 160, cell: 'tags' },
  { colKey: 'is_active', title: '状态', width: 80, cell: 'is_active' },
  { colKey: 'verification_status', title: '验证状态', width: 100, cell: 'verification_status' },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'op', title: '操作', width: 160, cell: 'op' },
]

async function loadKeys() {
  loading.value = true
  try {
    const params: any = { page: currentPage.value, page_size: pageSize.value }
    // Apply search keyword
    if (searchKeyword.value) params.search = searchKeyword.value
    // Apply status filter
    if (filterStatus.value !== null && filterStatus.value !== undefined)
      params.is_active = filterStatus.value === 'true'
    // Apply verification filter
    if (filterVerification.value) params.verification_status = filterVerification.value
    const res = await listKeys(params)
    keys.value = res.data.items
    total.value = res.data.total
  } catch {
    MessagePlugin.error('加载 Key 列表失败')
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  currentPage.value = 1
  loadKeys()
}

function resetFilters() {
  searchKeyword.value = ''
  filterStatus.value = null
  filterVerification.value = null
  currentPage.value = 1
  loadKeys()
}

function onPageChange(pageInfo: { current: number; pageSize: number }) {
  currentPage.value = pageInfo.current
  pageSize.value = pageInfo.pageSize
  loadKeys()
}

function openCreate() {
  editingKey.value = null
  resetForm()
  showDialog.value = true
}

async function onToggleActive(row: ApiKeyResponse, isActive: boolean) {
  try {
    await updateKey(row.identifier, { is_active: isActive })
    row.is_active = isActive
    MessagePlugin.success(isActive ? '已启用' : '已停用')
  } catch {
    MessagePlugin.error('状态切换失败')
    loadKeys()
  }
}

async function onViewRaw(row: ApiKeyResponse) {
  rawRawLoading.value = true
  showRawDialog.value = true
  rawKeyData.value = null
  try {
    const res = await getRawKey(row.identifier)
    rawKeyData.value = res.data
  } catch {
    MessagePlugin.error('获取 Key 明文失败')
    showRawDialog.value = false
  } finally {
    rawRawLoading.value = false
  }
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    MessagePlugin.success('已复制到剪贴板')
  } catch {
    MessagePlugin.error('复制失败，请手动选择复制')
  }
}

function onEdit(row: ApiKeyResponse) {
  editingKey.value = row
  formData.value = {
    identifier: row.identifier,
    alias: row.alias || '',
    raw_key: '',
    tags: row.tags || [],
    description: row.description || '',
  }
  showDialog.value = true
}

async function onVerify(row: ApiKeyResponse) {
  try {
    const res = await verifyKey(row.identifier)
    MessagePlugin.success(res.data.verification_status === 'verified' ? 'Key 验证通过' : `Key 验证状态: ${res.data.verification_status}`)
    loadKeys()
  } catch {
    MessagePlugin.error('验证请求失败')
  }
}

function onDelete(row: ApiKeyResponse) {
  const dialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除 Key "${row.identifier}" 吗？此操作不可恢复。`,
    confirmBtn: { theme: 'danger', content: '删除' },
    onConfirm: async () => {
      try {
        await deleteKey(row.identifier)
        MessagePlugin.success('已删除')
        loadKeys()
      } catch {
        MessagePlugin.error('删除失败')
      }
      dialog.destroy()
    },
  })
}

async function onSubmit() {
  dialogLoading.value = true
  try {
    if (editingKey.value) {
      const data: ApiKeyUpdate = {
        alias: formData.value.alias || undefined,
        tags: formData.value.tags,
        description: formData.value.description || undefined,
      }
      await updateKey(editingKey.value.identifier, data)
      MessagePlugin.success('更新成功')
    } else {
      const data: ApiKeyCreate = {
        identifier: formData.value.identifier,
        alias: formData.value.alias || undefined,
        raw_key: formData.value.raw_key,
        tags: formData.value.tags,
        description: formData.value.description || undefined,
      }
      await createKey(data)
      MessagePlugin.success('创建成功 — 请前往「密钥池」页面将此 Key 添加到池子中')
    }
    showDialog.value = false
    resetForm()
    loadKeys()
  } catch (err: any) {
    MessagePlugin.error(extractErrorMessage(err, '操作失败'))
  } finally {
    dialogLoading.value = false
  }
}

function resetForm() {
  editingKey.value = null
  formData.value = {
    identifier: '',
    alias: '',
    raw_key: '',
    tags: [],
    description: '',
  }
}

onMounted(async () => {
  // Wait for full DOM render before showing table (fixes lazy-load route #op slot issue)
  await nextTick()
  mounted.value = true
  loadKeys()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.filter-bar {
  margin-bottom: 16px;
}
</style>
