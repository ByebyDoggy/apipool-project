<template>
  <t-layout style="height: 100vh">
    <t-aside width="220px" :collapsed="collapsed">
      <div class="logo" @click="collapsed = !collapsed">
        <span v-if="!collapsed" class="logo-text">ApiPool</span>
        <span v-else class="logo-icon">A</span>
      </div>
      <t-menu :value="activeMenu" :collapsed="collapsed" @change="onMenuChange">
        <t-menu-item value="dashboard">
          <template #icon><t-icon name="dashboard" /></template>
          概览
        </t-menu-item>
        <t-menu-item value="keys">
          <template #icon><t-icon name="lock-on" /></template>
          Key 管理
        </t-menu-item>
        <t-menu-item value="pools">
          <template #icon><t-icon name="server" /></template>
          密钥池
        </t-menu-item>
      </t-menu>
    </t-aside>
    <t-layout>
      <t-header class="main-header">
        <div class="header-left">
          <t-breadcrumb>
            <t-breadcrumb-item>ApiPool</t-breadcrumb-item>
            <t-breadcrumb-item>{{ currentTitle }}</t-breadcrumb-item>
          </t-breadcrumb>
        </div>
        <div class="header-right">
          <t-dropdown :options="userMenuOptions" @click="onUserMenuClick">
            <t-button variant="text">
              <t-icon name="user-circle" style="margin-right: 4px" />
              {{ auth.user?.username || '用户' }}
            </t-button>
          </t-dropdown>
        </div>
      </t-header>
      <t-content class="main-content">
        <router-view />
      </t-content>
    </t-layout>
  </t-layout>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { MessagePlugin } from 'tdesign-vue-next'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const collapsed = ref(false)

const activeMenu = computed(() => {
  const path = route.path
  if (path.includes('/keys')) return 'keys'
  if (path.includes('/pools')) return 'pools'
  return 'dashboard'
})

const currentTitle = computed(() => {
  const map: Record<string, string> = {
    dashboard: '概览',
    keys: 'Key 管理',
    pools: '密钥池',
  }
  return map[activeMenu.value] || '概览'
})

const userMenuOptions = [
  { content: '个人信息', value: 'profile' },
  { content: '退出登录', value: 'logout', theme: 'error' },
]

function onMenuChange(value: string) {
  router.push(`/${value}`)
}

function onUserMenuClick(data: { value: string }) {
  if (data.value === 'logout') {
    auth.logout()
    router.push('/login')
    MessagePlugin.success('已退出登录')
  }
}
</script>

<style scoped>
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-bottom: 1px solid var(--td-border-level-1-color);
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: var(--td-brand-color);
  letter-spacing: 2px;
}

.logo-icon {
  font-size: 24px;
  font-weight: 700;
  color: var(--td-brand-color);
}

.main-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--td-bg-color-container);
  border-bottom: 1px solid var(--td-border-level-1-color);
}

.header-left {
  display: flex;
  align-items: center;
}

.header-right {
  display: flex;
  align-items: center;
}

.main-content {
  padding: 24px;
  background: var(--td-bg-color-page);
  overflow-y: auto;
}
</style>
