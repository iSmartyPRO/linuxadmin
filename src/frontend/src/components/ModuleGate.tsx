import { Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { useAppSettings, type ModuleKey } from '../api/settings'

/** Redirect away when a monitoring module is disabled in settings. */
export function ModuleGate({
  module,
  children,
}: {
  module: ModuleKey
  children: React.ReactNode
}) {
  const { loading, isModuleEnabled } = useAppSettings()
  if (loading) {
    return (
      <div style={{ padding: 48, display: 'grid', placeItems: 'center' }}>
        <Spin />
      </div>
    )
  }
  if (!isModuleEnabled(module)) {
    return <Navigate to="/settings" replace />
  }
  return children
}
