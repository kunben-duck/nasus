type ApiAuthTokenProvider = () => string

let authTokenProvider: ApiAuthTokenProvider = () => ''

export function configureApiAuthTokenProvider(provider: ApiAuthTokenProvider): void {
  authTokenProvider = provider
}

export function apiAuthToken(): string {
  const tokenFromEnv = import.meta.env.VITE_NASUS_API_TOKEN as string | undefined
  const tokenFromStorage = authTokenProvider()
  return (tokenFromEnv || tokenFromStorage).trim()
}

function authHeaders(): Record<string, string> {
  const token = apiAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (!(options?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  Object.entries(authHeaders()).forEach(([key, value]) => headers.set(key, value))
  const response = await fetch(path, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let message = `Request failed for ${path}`
    const contentType = response.headers.get('content-type') ?? ''

    if (contentType.includes('application/json')) {
      const payload = await response.json().catch(() => null) as
        | { detail?: { error?: { message?: string } }; error?: { message?: string }; message?: string }
        | null
      message = payload?.detail?.error?.message ?? payload?.error?.message ?? payload?.message ?? message
    } else {
      const text = await response.text().catch(() => '')
      if (text.trim()) {
        message = text.trim()
      }
    }

    throw new Error(message)
  }

  return response.json() as Promise<T>
}
