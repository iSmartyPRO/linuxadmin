import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

type SetupStatusState = {
  configured: boolean | null
  markConfigured: () => void
  refresh: () => Promise<boolean>
}

const SetupStatusContext = createContext<SetupStatusState | null>(null)

export function SetupStatusProvider({ children }: { children: ReactNode }) {
  const [configured, setConfigured] = useState<boolean | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/setup/status')
      const data = await res.json()
      const next = !!data.configured
      setConfigured(next)
      return next
    } catch {
      // Fail open to login rather than trapping users on setup.
      setConfigured(true)
      return true
    }
  }, [])

  const markConfigured = useCallback(() => {
    setConfigured(true)
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const value = useMemo(
    () => ({ configured, markConfigured, refresh }),
    [configured, markConfigured, refresh],
  )

  return <SetupStatusContext.Provider value={value}>{children}</SetupStatusContext.Provider>
}

export function useSetupStatus() {
  const ctx = useContext(SetupStatusContext)
  if (!ctx) throw new Error('useSetupStatus must be used within SetupStatusProvider')
  return ctx
}
