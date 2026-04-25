import http from './index'

// ── Types ────────────────────────────────────────────────────────────────

export interface KeySuccessRateItem {
  key_identifier: string
  alias: string | null
  total_calls: number
  success_count: number
  failed_count: number
  reach_limit_count: number
  success_rate: number
}

export interface SuccessRateResponse {
  pool_identifier: string
  period_seconds: number
  summary: KeySuccessRateItem
  by_key: KeySuccessRateItem[]
}

export interface CallLogItem {
  id: number
  key_identifier: string
  alias: string | null
  status: string
  finished_at: string
}

export interface CallLogResponse {
  pool_identifier: string
  period_seconds: number
  items: CallLogItem[]
  total: number
  page: number
  page_size: number
}

export interface KeyStatsResponse {
  key_identifier: string
  alias: string | null
  period_seconds: number
  total_calls: number
  success_count: number
  failed_count: number
  reach_limit_count: number
  success_rate: number
}

export interface SuccessRateParams {
  seconds?: number
}

export interface CallLogParams {
  seconds?: number
  key_identifier?: string
  status?: 'success' | 'failed' | 'reach_limit'
  page?: number
  page_size?: number
}

export interface KeyStatsParams {
  seconds?: number
}

// ── API Functions ────────────────────────────────────────────────────────

export function getSuccessRate(poolIdentifier: string, params?: SuccessRateParams) {
  return http.get<SuccessRateResponse>(`/stats/${poolIdentifier}/success-rate`, { params })
}

export function getCallLogs(poolIdentifier: string, params?: CallLogParams) {
  return http.get<CallLogResponse>(`/stats/${poolIdentifier}/logs`, { params })
}

export function getKeyStats(keyIdentifier: string, params?: KeyStatsParams) {
  return http.get<KeyStatsResponse>(`/keys/${keyIdentifier}/stats`, { params })
}
