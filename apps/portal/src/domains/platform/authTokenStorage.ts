import { apiAuthToken, configureApiAuthTokenProvider } from '../../shared/api/client'

const API_TOKEN_STORAGE_KEY = 'nasus_api_token'

export function storedApiAuthToken(): string {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(API_TOKEN_STORAGE_KEY) ?? ''
}

export function hasStoredApiAuthToken(): boolean {
  return Boolean(storedApiAuthToken().trim())
}

export function setApiAuthToken(token: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(API_TOKEN_STORAGE_KEY, token)
}

export function clearApiAuthToken(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(API_TOKEN_STORAGE_KEY)
}

export function platformApiAuthToken(): string {
  return apiAuthToken()
}

configureApiAuthTokenProvider(storedApiAuthToken)
