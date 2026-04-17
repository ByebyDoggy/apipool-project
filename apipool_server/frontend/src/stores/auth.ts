import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin, register as apiRegister, refreshToken as apiRefresh, getProfile, logout as apiLogout, type TokenResponse, type UserResponse } from '@/api/auth'

const TOKEN_KEY = 'apipool_token'
const REFRESH_KEY = 'apipool_refresh'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const refreshTokenVal = ref(localStorage.getItem(REFRESH_KEY) || '')
  const user = ref<UserResponse | null>(null)
  const isLoggedIn = computed(() => !!token.value)

  function setTokens(data: TokenResponse) {
    token.value = data.access_token
    refreshTokenVal.value = data.refresh_token
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(REFRESH_KEY, data.refresh_token)
  }

  async function login(username: string, password: string) {
    const res = await apiLogin({ username, password })
    setTokens(res.data)
    await fetchProfile()
  }

  async function register(username: string, email: string, password: string) {
    const res = await apiRegister({ username, email, password })
    setTokens(res.data)
    await fetchProfile()
  }

  async function fetchProfile() {
    try {
      const res = await getProfile()
      user.value = res.data
    } catch {
      user.value = null
    }
  }

  async function refresh() {
    if (!refreshTokenVal.value) return
    try {
      const res = await apiRefresh(refreshTokenVal.value)
      setTokens(res.data)
    } catch {
      logout()
    }
  }

  function logout() {
    // Best-effort: notify server to revoke refresh token
    if (refreshTokenVal.value) {
      apiLogout(refreshTokenVal.value).catch(() => {
        // Ignore errors — local cleanup always proceeds
      })
    }
    token.value = ''
    refreshTokenVal.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  }

  // Auto-fetch profile on init if token exists
  if (token.value) {
    fetchProfile()
  }

  return { token, user, isLoggedIn, login, register, fetchProfile, refresh, logout }
})
