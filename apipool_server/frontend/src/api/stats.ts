import http from './index'

export interface StatsUsageResponse {
  pool_identifier: string
  period_seconds: number
  summary: Record<string, number>
  by_key: Record<string, Record<string, number>> | null
}

export interface StatsTimelineResponse {
  pool_identifier: string
  period_seconds: number
  interval: string
  data: Record<string, any>[]
}

export interface UsageParams {
  seconds?: number
  group_by?: string  // 'key' | 'status' | 'hour'
  status?: string    // 'success' | 'failed' | 'reach_limit'
}

export interface TimelineParams {
  seconds?: number
  interval?: string  // 'minute' | 'hour' | 'day'
}

/**
 * Get usage statistics for a pool.
 * Backend: GET /api/v1/stats/{pool_identifier}/usage
 */
export function getUsageStats(poolIdentifier: string, params?: UsageParams) {
  return http.get<StatsUsageResponse>(`/stats/${poolIdentifier}/usage`, { params })
}

/**
 * Get usage timeline for a pool.
 * Backend: GET /api/v1/stats/{pool_identifier}/timeline
 */
export function getTimeline(poolIdentifier: string, params?: TimelineParams) {
  return http.get<StatsTimelineResponse>(`/stats/${poolIdentifier}/timeline`, { params })
}
