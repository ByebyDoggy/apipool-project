import http from './index'
import type { PageResponse, ApiKeyResponse } from './keys'

export interface PoolCreate {
  identifier: string
  name: string
  client_type: string
  description?: string
  key_identifiers: string[]
}

export interface PoolUpdate {
  name?: string
  description?: string
}

export interface PoolMemberAdd {
  key_identifiers: string[]
}

export interface PoolResponse {
  id: number
  identifier: string
  name: string
  client_type: string
  description: string | null
  is_active: boolean
  total_keys: number
  active_keys: number
  members?: PoolMemberResponse[]
  created_at: string
  updated_at: string
}

export interface PoolMemberResponse {
  id: number
  identifier: string
  alias: string | null
  client_type: string
  is_active: boolean
  is_valid: boolean
  added_at: string
}

export interface PoolStatusResponse {
  identifier: string
  available: number
  archived: number
  total: number
  is_active: boolean
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
