import http from './index'

export interface ApiKeyCreate {
  identifier: string
  alias?: string
  raw_key: string
  client_config?: Record<string, any> | null
  tags?: string[] | null
  description?: string | null
}

export interface ApiKeyUpdate {
  alias?: string | null
  tags?: string[] | null
  description?: string | null
  client_config?: Record<string, any> | null
  is_active?: boolean | null
}

export interface ApiKeyRotateRequest {
  new_raw_key: string
}

export interface ApiKeyResponse {
  id: number
  identifier: string
  alias: string | null
  client_config: Record<string, any> | null
  is_active: boolean
  is_archived: boolean
  verification_status: string
  last_verified_at: string | null
  tags: string[] | null
  description: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ApiKeyVerifyResponse {
  identifier: string
  verification_status: string
  verified_at: string
}

export interface BatchImportRequest {
  client_type: string
  keys: { identifier: string; raw_key: string; alias?: string }[]
}

export interface BatchImportResponse {
  task_id: string
  status: string
  total: number
}

export interface KeyExportItem {
  identifier: string
  alias: string | null
  raw_key: string
  tags: string[] | null
  description: string | null
  is_active: boolean
}

export interface KeyExportResponse {
  exported_at: string
  total: number
  keys: KeyExportItem[]
}

export interface KeyImportItem {
  identifier: string
  alias?: string
  raw_key: string
  tags?: string[]
  description?: string
  is_active?: boolean
}

export interface KeyImportRequest {
  keys: KeyImportItem[]
}

export interface KeyImportResponse {
  task_id: string
  status: string
  total: number
  imported: number
  skipped: number
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
  pool_id?: number
  is_active?: boolean
  tag?: string
  search?: string
  verification_status?: string
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

export interface SingleRawKeyResponse {
  id: number
  identifier: string
  raw_key: string
  alias: string | null
  is_active: boolean
  verification_status: string
  tags: string[] | null
  created_at: string | null
}

export function getRawKey(identifier: string) {
  return http.get<SingleRawKeyResponse>(`/keys/${identifier}/raw`)
}

export function batchImport(data: BatchImportRequest) {
  return http.post<BatchImportResponse>('/keys/batch-import', data)
}

export interface KeyExportParams {
  pool_id?: number
  is_active?: boolean
  tag?: string
  search?: string
  verification_status?: string
}

export function exportKeys(params?: KeyExportParams) {
  return http.get<Blob>('/keys/export', { params, responseType: 'blob' })
}

export function importKeys(data: KeyImportRequest) {
  return http.post<KeyImportResponse>('/keys/import', data)
}
