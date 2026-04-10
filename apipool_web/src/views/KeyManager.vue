<template>
  <div>
    <t-card :bordered="false">
      <template #header>
        <div class="card-header">
          <span>API Key 管理</span>
          <t-space>
            <t-select v-model="filterType" placeholder="类型筛选" clearable style="width: 160px" @change="loadKeys" filterable>
              <t-option value="generic" label="generic" />
              <t-option value="openai" label="openai" />
              <t-option value="anthropic" label="anthropic" />
              <t-option value="googlemaps" label="googlemaps" />
            </t-select>
            <t-button theme="primary" @click="openCreate">
              <t-icon name="add" style="margin-right: 4px" /> 新增 Key
            </t-button>
          </t-space>
        </div>
      </template>

      <t-table
        :data="keys"
        :columns="columns"
        :loading="loading"
        row-key="identifier"
        hover
        stripe
      >
        <template #is_active="{ row }">
          <t-tag :theme="row.is_active ? 'success' : 'default'" variant="light" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </t-tag>
        </template>
        <template #is_valid="{ row }">
          <t-tag :theme="row.is_valid ? 'success' : 'danger'" variant="light" size="small">
            {{ row.is_valid ? '有效' : '无效' }}
          </t-tag>
        </template>
        <template #tags="{ row }">
          <t-tag v-for="tag in (row.tags || [])" :key="tag" size="small" variant="light" style="margin-right: 4px">{{ tag }}</t-tag>
        </template>
        <template #op="{ row }">
          <t-space size="small">
            <t-link theme="primary" @click="onVerify(row)">验证</t-link>
            <t-link theme="primary" @click="onEdit(row)">编辑</t-link>
            <t-link theme="danger" @click="onDelete(row)">删除</t-link>
          </t-space>
        </template>
      </t-table>

      <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
        <t-pagination
          v-model="currentPage"
          :total="total"
          :page-size="pageSize"
          show-jumper
          @change="loadKeys"
        />
      </div>
    </t-card>

    <!-- Create / Edit Dialog -->
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
        <t-form-item label="服务类型" name="client_type" v-if="!editingKey">
          <t-select v-model="formData.client_type" creatable filterable placeholder="如 openai / anthropic / 自定义">
            <t-option value="generic" label="generic (通用 HTTP)" />
            <t-option value="openai" label="openai" />
            <t-option value="anthropic" label="anthropic" />
            <t-option value="googlemaps" label="googlemaps" />
          </t-select>
        </t-form-item>
        <t-form-item label="标签" name="tags">
          <t-tag-input v-model="formData.tags" placeholder="输入标签后回车" />
        </t-form-item>
        <t-form-item label="描述" name="description">
          <t-textarea v-model="formData.description" placeholder="描述信息" :maxlength="200" />
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listKeys, createKey, updateKey, deleteKey, verifyKey, type ApiKeyResponse, type ApiKeyCreate, type ApiKeyUpdate } from '@/api/keys'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { extractErrorMessage } from '@/api/errors'

const keys = ref<ApiKeyResponse[]>([])
const loading = ref(false)
const filterType = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

const showDialog = ref(false)
const dialogLoading = ref(false)
const editingKey = ref<ApiKeyResponse | null>(null)

const formData = ref<{
  identifier: string
  alias: string
  raw_key: string
  client_type: string
  tags: string[]
  description: string
}>({
  identifier: '',
  alias: '',
  raw_key: '',
  client_type: 'generic',
  tags: [],
  description: '',
})

const formRules = {
  identifier: [{ required: true, message: '请输入标识符' }],
  raw_key: [{ required: true, message: '请输入 Key 值' }],
  client_type: [{ required: true, message: '请输入服务类型' }],
}

const columns = [
  { colKey: 'identifier', title: '标识符', width: 180, ellipsis: true },
  { colKey: 'alias', title: '别名', width: 140, ellipsis: true },
  { colKey: 'client_type', title: '服务类型', width: 120 },
  { colKey: 'tags', title: '标签', width: 160, cell: 'tags' },
  { colKey: 'is_active', title: '状态', width: 80, cell: 'is_active' },
  { colKey: 'is_valid', title: '有效', width: 80, cell: 'is_valid' },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'op', title: '操作', width: 160, cell: 'op' },
]

async function loadKeys() {
  loading.value = true
  try {
    const params: any = { page: currentPage.value, page_size: pageSize.value }
    if (filterType.value) params.client_type = filterType.value
    const res = await listKeys(params)
    keys.value = res.data.items
    total.value = res.data.total
  } catch {
    MessagePlugin.error('加载 Key 列表失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingKey.value = null
  resetForm()
  showDialog.value = true
}

function onEdit(row: ApiKeyResponse) {
  editingKey.value = row
  formData.value = {
    identifier: row.identifier,
    alias: row.alias || '',
    raw_key: '',
    client_type: row.client_type,
    tags: row.tags || [],
    description: row.description || '',
  }
  showDialog.value = true
}

async function onVerify(row: ApiKeyResponse) {
  try {
    const res = await verifyKey(row.identifier)
    MessagePlugin.success(res.data.is_valid ? 'Key 验证通过' : 'Key 验证失败，可能已失效')
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
        client_type: formData.value.client_type,
        tags: formData.value.tags,
        description: formData.value.description || undefined,
      }
      await createKey(data)
      MessagePlugin.success('创建成功')
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
    client_type: 'generic',
    tags: [],
    description: '',
  }
}

onMounted(loadKeys)
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
</style>
