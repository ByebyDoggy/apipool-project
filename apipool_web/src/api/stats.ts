import http from './index'

export interface UsageStats {
  total_calls: number
  success_calls: number
  failed_calls: number
  active_keys: number
  active_pools: number
}

export function getUsageStats() {
  return http.get<UsageStats>('/stats/usage')
}

export function getTimeline(params?: { days?: number; pool_id?: number }) {
  return http.get('/stats/timeline', { params })
}
