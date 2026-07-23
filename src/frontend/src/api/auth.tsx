import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, clearToken, getToken, setToken } from './client'

type AuthState = {
  token: string | null
  username: string | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTok] = useState<string | null>(getToken())
  const [username, setUsername] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const me = await api<{ username: string }>('/api/auth/me')
        if (!cancelled) setUsername(me.username)
      } catch {
        if (!cancelled) {
          clearToken()
          setTok(null)
          setUsername(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [token])

  const login = useCallback(async (user: string, password: string) => {
    const res = await api<{ access_token: string; username: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: user, password }),
    })
    setToken(res.access_token)
    setTok(res.access_token)
    setUsername(res.username)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setTok(null)
    setUsername(null)
  }, [])

  const value = useMemo(
    () => ({ token, username, loading, login, logout }),
    [token, username, loading, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside provider')
  return ctx
}
