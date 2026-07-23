export const brand = {
  name: 'Linux Admin',
  accent: '#0d9488',
  accentSoft: '#14b8a6',
  accentDeep: '#0f766e',
  ink: '#0b1220',
  slate: '#1a2332',
  mist: '#e8eef4',
  paper: '#f4f7fa',
  danger: '#e11d48',
  warn: '#d97706',
  ok: '#059669',
} as const

export function buildAntdTheme(dark: boolean) {
  return {
    token: {
      colorPrimary: brand.accent,
      colorInfo: brand.accent,
      colorSuccess: brand.ok,
      colorWarning: brand.warn,
      colorError: brand.danger,
      colorBgBase: dark ? brand.ink : brand.paper,
      colorBgContainer: dark ? 'rgba(26, 35, 50, 0.72)' : 'rgba(255, 255, 255, 0.78)',
      colorBgElevated: dark ? '#1e2a3a' : '#ffffff',
      colorBorder: dark ? 'rgba(148, 163, 184, 0.14)' : 'rgba(15, 23, 42, 0.08)',
      colorBorderSecondary: dark ? 'rgba(148, 163, 184, 0.08)' : 'rgba(15, 23, 42, 0.05)',
      colorText: dark ? '#e8eef4' : '#0f172a',
      colorTextSecondary: dark ? '#94a3b8' : '#64748b',
      borderRadius: 14,
      borderRadiusLG: 18,
      borderRadiusSM: 10,
      fontFamily: '"Manrope", "Segoe UI", sans-serif',
      fontFamilyCode: '"JetBrains Mono", ui-monospace, monospace',
      controlHeight: 38,
      wireframe: false,
    },
    components: {
      Layout: {
        bodyBg: 'transparent',
        headerBg: 'transparent',
        siderBg: 'transparent',
        triggerBg: dark ? brand.slate : '#fff',
      },
      Menu: {
        itemBg: 'transparent',
        subMenuItemBg: 'transparent',
        itemSelectedBg: dark ? 'rgba(13, 148, 136, 0.18)' : 'rgba(13, 148, 136, 0.12)',
        itemHoverBg: dark ? 'rgba(148, 163, 184, 0.08)' : 'rgba(15, 23, 42, 0.04)',
        itemSelectedColor: dark ? brand.accentSoft : brand.accentDeep,
        itemColor: dark ? '#cbd5e1' : '#334155',
        iconSize: 16,
      },
      Card: {
        paddingLG: 20,
      },
      Table: {
        headerBg: dark ? 'rgba(148, 163, 184, 0.06)' : 'rgba(15, 23, 42, 0.03)',
        rowHoverBg: dark ? 'rgba(13, 148, 136, 0.08)' : 'rgba(13, 148, 136, 0.05)',
      },
      Button: {
        primaryShadow: '0 8px 24px rgba(13, 148, 136, 0.28)',
      },
    },
  }
}
