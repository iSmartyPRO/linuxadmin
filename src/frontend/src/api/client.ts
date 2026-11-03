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
  if (!headers.has('Content-Type') && options.body && !(options.body instanceof FormData)) {
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

function authHeader(): string | null {
  const token = getToken()
  return token ? `Bearer ${token}` : null
}

function failStatus(status: number, body: string): Error {
  if (status === 401) {
    clearToken()
    if (!window.location.pathname.startsWith('/login')) window.location.href = '/login'
    return new Error('Unauthorized')
  }
  return new Error(body || `Request failed (${status})`)
}

/** Multipart upload with real byte progress (fetch cannot report upload progress). */
export function apiUpload(
  path: string,
  body: FormData,
  onProgress?: (loaded: number, total: number) => void,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    const auth = authHeader()
    if (auth) xhr.setRequestHeader('Authorization', auth)
    xhr.upload.onprogress = (event) => {
      if (!onProgress) return
      const total = event.lengthComputable ? event.total : 0
      onProgress(event.loaded, total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (!xhr.responseText) {
          resolve(undefined)
          return
        }
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          resolve(undefined)
        }
        return
      }
      reject(failStatus(xhr.status, xhr.responseText))
    }
    xhr.onerror = () => reject(new Error('Failed to fetch'))
    xhr.send(body)
  })
}

export type StreamProgress = {
  type: string
  pct?: number
  done?: number
  total?: number
  label?: string
  detail?: string
  name?: string
  rel?: string
  skipped?: number
}

/** POST JSON and read newline-delimited progress events. Resolves with the done event. */
export async function apiNdjson<T>(
  path: string,
  body: unknown,
  onProgress: (event: StreamProgress) => void,
): Promise<T> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const auth = authHeader()
  if (auth) headers.set('Authorization', auth)
  const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) })
  if (res.status === 401) {
    clearToken()
    if (!window.location.pathname.startsWith('/login')) window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    throw new Error((await res.text()) || res.statusText)
  }
  if (!res.body) throw new Error('No progress stream')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let doneEvent: T | null = null
  while (true) {
    const chunk = await reader.read()
    if (chunk.done) break
    pending += decoder.decode(chunk.value, { stream: true })
    const lines = pending.split('\n')
    pending = lines.pop() || ''
    for (const line of lines) {
      const text = line.trim()
      if (!text) continue
      const event = JSON.parse(text) as StreamProgress
      if (event.type === 'error') throw new Error(event.detail || 'Archive operation failed')
      if (event.type === 'progress') onProgress(event)
      if (event.type === 'done') doneEvent = event as T
    }
  }
  if (!doneEvent) throw new Error('Archive finished without a result')
  return doneEvent
}

/** Authenticated binary download (ZIP, etc.). Returns blob + filename hint. */
export async function apiDownload(
  path: string,
  options: RequestInit = {},
): Promise<{ blob: Blob; filename: string | null }> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(path, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j?.detail || j?.error || detail
    } catch {
      try {
        detail = (await res.text()) || detail
      } catch {
        /* ignore */
      }
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return { blob: await res.blob(), filename: filenameFromDisposition(res.headers.get('Content-Disposition') || '') }
}

/** RFC 6266: prefer filename*=UTF-8''<percent-encoded> (used for spaces / non-ASCII), else filename="…". */
export function filenameFromDisposition(cd: string): string | null {
  const star = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(cd)
  if (star) {
    try {
      return decodeURIComponent(star[2].trim())
    } catch {
      /* fall through to the plain form */
    }
  }
  const plain = /filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]+))/i.exec(cd)
  if (!plain) return null
  return plain[1] != null ? plain[1].replace(/\\(.)/g, '$1') : plain[2].trim()
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
