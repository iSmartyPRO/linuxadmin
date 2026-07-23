import { Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { useAppSettings, type ModuleKey } from '../api/settings'
import { useAccess } from '../api/access'

/** Redirect away when module is disabled or the user lacks read permission. */
export function ModuleGate({
  module,
  children,
}: {
  module: ModuleKey
  children: React.ReactNode
}) {
  const { loading, isModuleEnabled } = useAppSettings()
  const { loading: accessLoading, can } = useAccess()
  if (loading || accessLoading) {
    return (
      <div style={{ padding: 48, display: 'grid', placeItems: 'center' }}>
        <Spin />
      </div>
    )
  }
  if (!isModuleEnabled(module) || !can(module, 'read')) {
    return <Navigate to="/" replace />
  }
  return children
}
