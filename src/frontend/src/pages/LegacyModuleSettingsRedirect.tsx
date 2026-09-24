import { Navigate, useParams } from 'react-router-dom'

export function LegacyModuleSettingsRedirect() {
  const { moduleKey = '' } = useParams()
  return <Navigate to={`/settings/module/${moduleKey}`} replace />
}
