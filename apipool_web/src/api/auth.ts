import http from './index'

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
}

export interface UserResponse {
  id: number
  username: string
  email: string
  role: string
  is_active: boolean
  created_at: string
}

export function login(data: LoginRequest) {
  return http.post<TokenResponse>('/auth/login', data)
}

export function register(data: RegisterRequest) {
  return http.post<TokenResponse>('/auth/register', data)
}

export function refreshToken(refresh_token: string) {
  return http.post<TokenResponse>('/auth/refresh', { refresh_token })
}

export function getProfile() {
  return http.get<UserResponse>('/auth/me')
}
