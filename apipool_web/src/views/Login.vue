<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <h1>ApiPool</h1>
        <p>API Key 管理平台</p>
      </div>
      <t-tabs v-model="tabValue">
        <t-tab-panel value="login" label="登录">
          <t-form ref="loginFormRef" :data="loginForm" :rules="loginRules" @submit="onLogin" label-width="0">
            <t-form-item name="username">
              <t-input v-model="loginForm.username" placeholder="用户名" prefix-icon="user" size="large" />
            </t-form-item>
            <t-form-item name="password">
              <t-input v-model="loginForm.password" type="password" placeholder="密码" prefix-icon="lock-on" size="large" />
            </t-form-item>
            <t-form-item>
              <t-button theme="primary" type="submit" block size="large" :loading="loading">登 录</t-button>
            </t-form-item>
          </t-form>
        </t-tab-panel>
        <t-tab-panel value="register" label="注册">
          <t-form ref="registerFormRef" :data="registerForm" :rules="registerRules" @submit="onRegister" label-width="0">
            <t-form-item name="username">
              <t-input v-model="registerForm.username" placeholder="用户名" prefix-icon="user" size="large" />
            </t-form-item>
            <t-form-item name="email">
              <t-input v-model="registerForm.email" placeholder="邮箱" prefix-icon="mail" size="large" />
            </t-form-item>
            <t-form-item name="password">
              <t-input v-model="registerForm.password" type="password" placeholder="密码" prefix-icon="lock-on" size="large" />
            </t-form-item>
            <t-form-item>
              <t-button theme="primary" type="submit" block size="large" :loading="loading">注 册</t-button>
            </t-form-item>
          </t-form>
        </t-tab-panel>
      </t-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { MessagePlugin } from 'tdesign-vue-next'
import { extractErrorMessage } from '@/api/errors'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const tabValue = ref('login')
const loading = ref(false)

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', email: '', password: '' })

const loginRules = {
  username: [{ required: true, message: '请输入用户名' }],
  password: [{ required: true, message: '请输入密码' }],
}
const registerRules = {
  username: [{ required: true, message: '请输入用户名' }],
  email: [
    { required: true, message: '请输入邮箱' },
    { email: true, message: '邮箱格式不正确' },
  ],
  password: [
    { required: true, message: '请输入密码' },
    { min: 8, message: '密码至少8位' },
  ],
}

async function onLogin({ validateResult }: any) {
  if (validateResult !== true) return
  loading.value = true
  try {
    await auth.login(loginForm.username, loginForm.password)
    MessagePlugin.success('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (err: any) {
    MessagePlugin.error(extractErrorMessage(err, '登录失败'))
  } finally {
    loading.value = false
  }
}

async function onRegister({ validateResult }: any) {
  if (validateResult !== true) return
  loading.value = true
  try {
    await auth.register(registerForm.username, registerForm.email, registerForm.password)
    MessagePlugin.success('注册成功')
    router.push('/')
  } catch (err: any) {
    MessagePlugin.error(extractErrorMessage(err, '注册失败'))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-header h1 {
  font-size: 28px;
  color: #333;
  margin: 0 0 8px;
}

.login-header p {
  color: #888;
  margin: 0;
}
</style>
