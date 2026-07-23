const TOKEN_KEY = 'lnxadmin_token'

/** Prefer sessionStorage so a stolen XSS token does not survive browser restart. */
function storage(): Storage {
  try {
    return sessionStorage
  } catch {
    return localStorage
  }
}

export function getToken(): string | null {
  try {
    return storage().getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    localStorage.setItem(TOKEN_KEY, token)
  }
}

export function clearToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
  localStorage.removeItem(TOKEN_KEY)
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(path, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    if (!path.includes('/api/auth/login')) {
      window.location.href = '/login'
    }
    throw new Error('Unauthorized')
  }
  if (res.status === 429) {
    const text = await res.text()
    throw new Error(text || 'Too many requests — try again later')
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** WebSocket URL without secrets in the query string. */
export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

/** Open metrics WS and authenticate with the first message (not URL). */
export function connectAuthedWs(path: string): WebSocket {
  const ws = new WebSocket(wsUrl(path))
  ws.addEventListener('open', () => {
    const token = getToken() || ''
    ws.send(JSON.stringify({ type: 'auth', token }))
  })
  return ws
}
