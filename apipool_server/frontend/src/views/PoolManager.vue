<template>
  <div>
    <t-card :bordered="false">
      <template #header>
        <div class="card-header">
          <span>密钥池管理</span>
          <t-button theme="primary" @click="openCreate">
            <t-icon name="add" style="margin-right: 4px" /> 创建池
          </t-button>
        </div>
      </template>

      <t-table v-if="mounted" :data="pools" :columns="columns" :loading="loading" row-key="identifier" hover stripe>
        <template #is_active="{ row }">
          <t-tag :theme="row.is_active ? 'success' : 'default'" variant="light" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </t-tag>
        </template>
        <template #member_count="{ row }">
          <span>{{ row.member_count }}</span>
        </template>
        <template #op="{ row }">
          <t-space size="small">
            <t-link theme="primary" @click="$router.push(`/pools/${row.identifier}`)">详情</t-link>
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
          @change="loadPools"
        />
      </div>
    </t-card>

    <!-- Create / Edit Dialog -->
    <t-dialog
      v-model:visible="showDialog"
      :header="editingPool ? '编辑池' : '创建池'"
      :confirm-btn="{ loading: dialogLoading }"
      @confirm="onSubmit"
      @close="resetForm"
    >
      <t-form ref="formRef" :data="formData" :rules="formRules" label-width="100px">
        <t-form-item label="标识符" name="identifier" v-if="!editingPool">
          <t-input v-model="formData.identifier" placeholder="唯一标识符，如 my-pool-1" />
        </t-form-item>
        <t-form-item label="名称" name="name">
          <t-input v-model="formData.name" placeholder="池名称" />
        </t-form-item>
        <t-form-item label="描述" name="description">
          <t-textarea v-model="formData.description" placeholder="描述信息" :maxlength="200" />
        </t-form-item>
        <t-form-item label="限速异常类" name="reach_limit_exception" v-if="!editingPool">
          <t-input v-model="formData.reach_limit_exception" placeholder="留空则任意异常都触发轮转（默认）" />
        </t-form-item>
        <t-form-item label="轮转策略" name="rotation_strategy" v-if="!editingPool">
          <t-select v-model="formData.rotation_strategy" placeholder="Key 轮转策略">
            <t-option value="random" label="随机 (random)" />
            <t-option value="round_robin" label="轮询 (round_robin)" />
            <t-option value="least_used" label="最少使用 (least_used)" />
          </t-select>
        </t-form-item>
        <t-form-item label="选择 Key" name="key_identifiers" v-if="!editingPool">
          <t-select v-model="formData.key_identifiers" multiple placeholder="选择要加入池的 Key">
            <t-option v-for="k in availableKeys" :key="k.identifier" :value="k.identifier" :label="`${k.identifier} (${k.client_type})`" />
          </t-select>
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { listPools, createPool, updatePool, deletePool, type PoolResponse, type PoolCreate, type PoolUpdate } from '@/api/pools'
import { listKeys, type ApiKeyResponse } from '@/api/keys'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { extractErrorMessage } from '@/api/errors'

const pools = ref<PoolResponse[]>([])
const availableKeys = ref<ApiKeyResponse[]>([])
const loading = ref(false)
const mounted = ref(false)
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

const showDialog = ref(false)
const dialogLoading = ref(false)
const editingPool = ref<PoolResponse | null>(null)

const formData = ref<{
  identifier: string
  name: string
  description: string
  reach_limit_exception: string
  rotation_strategy: string
  key_identifiers: string[]
}>({
  identifier: '',
  name: '',
  description: '',
  reach_limit_exception: '',
  rotation_strategy: 'random',
  key_identifiers: [],
})

const formRules = {
  identifier: [{ required: true, message: '请输入标识符' }],
  name: [{ required: true, message: '请输入名称' }],
}

const columns = [
  { colKey: 'identifier', title: '标识符', width: 180, ellipsis: true },
  { colKey: 'name', title: '名称', width: 160 },
  { colKey: 'member_count', title: '成员数', width: 100, cell: 'member_count' },
  { colKey: 'is_active', title: '状态', width: 80, cell: 'is_active' },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'op', title: '操作', width: 160, cell: 'op' },
]

async function loadPools() {
  loading.value = true
  try {
    const res = await listPools({ page: currentPage.value, page_size: pageSize.value })
    pools.value = res.data.items
    total.value = res.data.total
  } catch {
    MessagePlugin.error('加载池列表失败')
  } finally {
    loading.value = false
  }
}

async function loadAvailableKeys() {
  try {
    const res = await listKeys({ page_size: 100 })
    availableKeys.value = res.data.items
  } catch {
    // ignore
  }
}

function openCreate() {
  editingPool.value = null
  resetForm()
  loadAvailableKeys()
  showDialog.value = true
}

function onEdit(row: PoolResponse) {
  editingPool.value = row
  formData.value = {
    identifier: row.identifier,
    name: row.name,
    description: row.description || '',
    reach_limit_exception: row.reach_limit_exception || '',
    rotation_strategy: row.rotation_strategy || 'random',
    key_identifiers: [],
  }
  showDialog.value = true
}

function onDelete(row: PoolResponse) {
  const dialog = DialogPlugin.confirm({
    header: '确认删除',
    body: `确定要删除池 "${row.name}" 吗？此操作不可恢复。`,
    confirmBtn: { theme: 'danger', content: '删除' },
    onConfirm: async () => {
      try {
        await deletePool(row.identifier)
        MessagePlugin.success('已删除')
        loadPools()
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
    if (editingPool.value) {
      const data: PoolUpdate = {
        name: formData.value.name || undefined,
        description: formData.value.description || undefined,
        reach_limit_exception: formData.value.reach_limit_exception || undefined,
        rotation_strategy: formData.value.rotation_strategy || undefined,
      }
      await updatePool(editingPool.value.identifier, data)
      MessagePlugin.success('更新成功')
    } else {
      const data: PoolCreate = {
        identifier: formData.value.identifier,
        name: formData.value.name,
        client_type: 'generic',
        description: formData.value.description || undefined,
        reach_limit_exception: formData.value.reach_limit_exception || undefined,
        rotation_strategy: formData.value.rotation_strategy || undefined,
        key_identifiers: formData.value.key_identifiers.length > 0 ? formData.value.key_identifiers : undefined,
      }
      await createPool(data)
      MessagePlugin.success('创建成功')
    }
    showDialog.value = false
    resetForm()
    loadPools()
  } catch (err: any) {
    MessagePlugin.error(extractErrorMessage(err, '操作失败'))
  } finally {
    dialogLoading.value = false
  }
}

function resetForm() {
  editingPool.value = null
  formData.value = {
    identifier: '',
    name: '',
    description: '',
    reach_limit_exception: '',
    rotation_strategy: 'random',
    key_identifiers: [],
  }
}

onMounted(async () => {
  await nextTick()
  mounted.value = true
  loadPools()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
</style>
