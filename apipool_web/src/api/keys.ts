import http from './index'

export interface ApiKeyCreate {
  identifier: string
  alias?: string
  raw_key: string
  client_type: string
  tags?: string[]
  description?: string
}

export interface ApiKeyUpdate {
  alias?: string
  tags?: string[]
  description?: string
  is_active?: boolean
}

export interface ApiKeyRotateRequest {
  new_raw_key: string
}

export interface ApiKeyResponse {
  id: number
  identifier: string
  alias: string | null
  client_type: string
  tags: string[]
  description: string | null
  is_active: boolean
  is_valid: boolean
  last_verified_at: string | null
  created_at: string
  updated_at: string
}

export interface ApiKeyVerifyResponse {
  identifier: string
  is_valid: boolean
  message: string
}

export interface PageResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface KeyListParams {
  page?: number
  page_size?: number
  client_type?: string
  is_active?: boolean
  tag?: string
}

export function listKeys(params?: KeyListParams) {
  return http.get<PageResponse<ApiKeyResponse>>('/keys', { params })
}

export function getKey(identifier: string) {
  return http.get<ApiKeyResponse>(`/keys/${identifier}`)
}

export function createKey(data: ApiKeyCreate) {
  return http.post<ApiKeyResponse>('/keys', data)
}

export function updateKey(identifier: string, data: ApiKeyUpdate) {
  return http.put<ApiKeyResponse>(`/keys/${identifier}`, data)
}

export function deleteKey(identifier: string) {
  return http.delete(`/keys/${identifier}`)
}

export function verifyKey(identifier: string) {
  return http.post<ApiKeyVerifyResponse>(`/keys/${identifier}/verify`)
}

export function rotateKey(identifier: string, new_raw_key: string) {
  return http.patch<ApiKeyResponse>(`/keys/${identifier}/rotate`, { new_raw_key })
}

export function batchImport(keys: ApiKeyCreate[]) {
  return http.post<{ imported: number }>('/keys/batch-import', { keys })
}
