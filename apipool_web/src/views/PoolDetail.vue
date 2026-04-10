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
            <t-button theme="primary" @click="showAddMemberDialog = true">
              <t-icon name="add" style="margin-right: 4px" /> 添加成员
            </t-button>
          </t-space>
        </div>
      </template>

      <t-loading :loading="loading">
        <t-descriptions v-if="pool" :column="3" bordered>
          <t-descriptions-item label="标识符">{{ pool.identifier }}</t-descriptions-item>
          <t-descriptions-item label="名称">{{ pool.name }}</t-descriptions-item>
          <t-descriptions-item label="客户端类型">{{ pool.client_type }}</t-descriptions-item>
          <t-descriptions-item label="状态">
            <t-tag :theme="pool.is_active ? 'success' : 'default'" variant="light">{{ pool.is_active ? '启用' : '停用' }}</t-tag>
          </t-descriptions-item>
          <t-descriptions-item label="Key 数量">{{ pool.active_keys }} / {{ pool.total_keys }}</t-descriptions-item>
          <t-descriptions-item label="描述">{{ pool.description || '-' }}</t-descriptions-item>
        </t-descriptions>

        <h3 style="margin: 24px 0 12px">成员 Key 列表</h3>
        <t-table :data="pool?.members || []" :columns="memberColumns" row-key="identifier" hover stripe>
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
          <template #op="{ row }">
            <t-link theme="danger" @click="onRemoveMember(row)">移除</t-link>
          </template>
        </t-table>

        <h3 style="margin: 24px 0 12px">SDK 调用示例</h3>
        <div class="code-block">
          <pre><code>from apipool import connect

manager = connect("http://localhost:8000", "{{ pool?.identifier || 'pool-id' }}", "your-jwt-token")
result = manager.client.some_method()</code></pre>
        </div>
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
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getPool, addMembers, removeMember, type PoolResponse, type PoolMemberResponse } from '@/api/pools'
import { listKeys, type ApiKeyResponse } from '@/api/keys'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { extractErrorMessage } from '@/api/errors'

const route = useRoute()
const poolIdentifier = route.params.id as string

const pool = ref<PoolResponse | null>(null)
const availableKeys = ref<ApiKeyResponse[]>([])
const loading = ref(false)
const showAddMemberDialog = ref(false)
const addMemberLoading = ref(false)
const selectedKeyIdentifiers = ref<string[]>([])

const memberColumns = [
  { colKey: 'identifier', title: '标识符', width: 180 },
  { colKey: 'alias', title: '别名', width: 140 },
  { colKey: 'client_type', title: '类型', width: 100 },
  { colKey: 'is_active', title: '状态', width: 80, cell: 'is_active' },
  { colKey: 'is_valid', title: '有效', width: 80, cell: 'is_valid' },
  { colKey: 'added_at', title: '添加时间', width: 170 },
  { colKey: 'op', title: '操作', width: 80, cell: 'op' },
]

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
    const memberIds = new Set((pool.value?.members || []).map((m: PoolMemberResponse) => m.identifier))
    availableKeys.value = res.data.items.filter((k) => !memberIds.has(k.identifier))
  } catch {
    // ignore
  }
}

function onRemoveMember(row: PoolMemberResponse) {
  const dialog = DialogPlugin.confirm({
    header: '确认移除',
    body: `确定要从池中移除 Key "${row.identifier}" 吗？`,
    confirmBtn: { theme: 'danger', content: '移除' },
    onConfirm: async () => {
      try {
        await removeMember(poolIdentifier, row.identifier)
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
  await loadPool()
  loadAvailableKeys()
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
</style>
