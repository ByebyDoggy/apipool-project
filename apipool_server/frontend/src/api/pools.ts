import http from './index'
import type { PageResponse } from './keys'

export interface PoolCreate {
  identifier: string
  name: string
  client_type: string
  description?: string | null
  reach_limit_exception?: string | null
  rotation_strategy?: string
  pool_config?: Record<string, any> | null
  key_identifiers?: string[] | null
}

export interface PoolUpdate {
  name?: string | null
  description?: string | null
  reach_limit_exception?: string | null
  rotation_strategy?: string | null
  pool_config?: Record<string, any> | null
}

export interface PoolMemberAdd {
  key_identifiers: string[]
  priority?: number
  weight?: number
}

export interface PoolResponse {
  id: number
  identifier: string
  name: string
  description: string | null
  client_type: string
  reach_limit_exception: string | null
  rotation_strategy: string
  pool_config: Record<string, any> | null
  is_active: boolean
  member_count: number
  members: PoolMemberResponse[] | null
  created_at: string | null
  updated_at: string | null
}

export interface PoolMemberResponse {
  key_identifier: string
  alias: string | null
  priority: number
  weight: number
  verification_status: string
}

export interface PoolStatusResponse {
  pool_identifier: string
  available_keys: number
  archived_keys: number
  total_keys: number
  recent_stats: Record<string, number> | null
}

export interface PoolConfigResponse {
  pool_identifier: string
  client_type: string
  reach_limit_exception: string | null
  rotation_strategy: string
  pool_config: Record<string, any> | null
}

export function listPools(params?: { page?: number; page_size?: number }) {
  return http.get<PageResponse<PoolResponse>>('/pools', { params })
}

export function getPool(identifier: string) {
  return http.get<PoolResponse>(`/pools/${identifier}`)
}

export function createPool(data: PoolCreate) {
  return http.post<PoolResponse>('/pools', data)
}

export function updatePool(identifier: string, data: PoolUpdate) {
  return http.put<PoolResponse>(`/pools/${identifier}`, data)
}

export function deletePool(identifier: string) {
  return http.delete(`/pools/${identifier}`)
}

export function addMembers(poolIdentifier: string, data: PoolMemberAdd) {
  return http.post<PoolResponse>(`/pools/${poolIdentifier}/members`, data)
}

export function removeMember(poolIdentifier: string, keyIdentifier: string) {
  return http.delete(`/pools/${poolIdentifier}/members/${keyIdentifier}`)
}

export function getPoolStatus(identifier: string) {
  return http.get<PoolStatusResponse>(`/pools/${identifier}/status`)
}

export function getPoolConfig(identifier: string) {
  return http.get<PoolConfigResponse>(`/pools/${identifier}/config`)
}
