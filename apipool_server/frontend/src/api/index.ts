import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// ── Token refresh state machine ───────────────────────────────────────
let isRefreshing = false
let pendingRequests: Array<{ resolve: (v: any) => void; reject: (e: any) => void; config: any }> = []

function processPendingQueue(token: string | null, error?: Error) {
  pendingRequests.forEach(({ resolve, reject }) => {
    if (error || !token) reject(error)
    else resolve(token)
  })
  pendingRequests = []
}

async function attemptTokenRefresh(): Promise<string | null> {
  const auth = useAuthStore()
  try {
    const res = await axios.post('/api/v1/auth/refresh', {
      refresh_token: auth.refreshTokenVal,
    })
    auth.setTokens(res.data)
    return res.data.access_token
  } catch {
    auth.logout()
    window.location.href = '/login'
    return null
  }
}

// Request interceptor — attach JWT token
http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// Response interceptor — handle 401 with auto-refresh
http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Only handle 401 on non-auth endpoints to avoid infinite loops
    if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url.includes('/auth/')) {
      if (!isRefreshing) {
        isRefreshing = true
        originalRequest._retry = true

        const newToken = await attemptTokenRefresh()
        isRefreshing = false

        processPendingQueue(newToken)

        if (newToken) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          return http(originalRequest)
        }

        // If refresh failed, the queue was already rejected + redirect happened
        return Promise.reject(error)
      }

      // Queue this request while refresh is in-flight
      return new Promise((resolve, reject) => {
        pendingRequests.push({
          resolve: (token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(http(originalRequest))
          },
          reject,
          config: originalRequest,
        })
      })
    }

    // Non-401 or auth endpoint errors pass through normally
    return Promise.reject(error)
  },
)

export default http
