import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api } from './client'
import { useAuth } from './auth'

export type PermLevel = 'none' | 'read' | 'full'

export type AccessProfile = {
  user_id: number
  username: string
  display_name: string
  is_superadmin: boolean
  role: { id: number; name: string; slug: string } | null
  permissions: Record<string, PermLevel>
  auth_via?: string
}

type AccessState = {
  loading: boolean
  profile: AccessProfile | null
  refresh: () => Promise<void>
  can: (module: string, need?: 'read' | 'full') => boolean
  canMutate: (module: string) => boolean
}

const RANK: Record<string, number> = { none: 0, read: 1, full: 2 }

const AccessContext = createContext<AccessState | null>(null)

export function AccessProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  const [loading, setLoading] = useState(true)
  const [profile, setProfile] = useState<AccessProfile | null>(null)

  const refresh = useCallback(async () => {
    if (!token) {
      setProfile(null)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const me = await api<AccessProfile>('/api/access/me')
      setProfile(me)
    } catch {
      setProfile(null)
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const can = useCallback(
    (module: string, need: 'read' | 'full' = 'read') => {
      if (!profile) return false
      if (profile.is_superadmin) return true
      const have = profile.permissions?.[module] || 'none'
      return (RANK[have] || 0) >= (RANK[need] || 0)
    },
    [profile],
  )

  const canMutate = useCallback((module: string) => can(module, 'full'), [can])

  const value = useMemo(
    () => ({ loading, profile, refresh, can, canMutate }),
    [loading, profile, refresh, can, canMutate],
  )

  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>
}

export function useAccess() {
  const ctx = useContext(AccessContext)
  if (!ctx) throw new Error('useAccess outside provider')
  return ctx
}
