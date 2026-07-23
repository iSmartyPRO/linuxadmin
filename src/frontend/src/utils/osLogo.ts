/** Map /etc/os-release ID (and ID_LIKE) to SVG under /os-logos/ */

const ID_TO_LOGO: Record<string, string> = {
  ubuntu: 'ubuntu.svg',
  debian: 'debian.svg',
  fedora: 'fedora.svg',
  centos: 'centos.svg',
  rhel: 'redhat.svg',
  redhat: 'redhat.svg',
  rocky: 'rockylinux.svg',
  rockylinux: 'rockylinux.svg',
  alma: 'almalinux.svg',
  almalinux: 'almalinux.svg',
  arch: 'archlinux.svg',
  archlinux: 'archlinux.svg',
  manjaro: 'manjaro.svg',
  opensuse: 'opensuse.svg',
  'opensuse-leap': 'opensuse.svg',
  'opensuse-tumbleweed': 'opensuse.svg',
  sles: 'suse.svg',
  suse: 'suse.svg',
  alpine: 'alpinelinux.svg',
  amzn: 'amazonlinux.svg',
  amazon: 'amazonlinux.svg',
  ol: 'oracle.svg',
  oracle: 'oracle.svg',
  linuxmint: 'linuxmint.svg',
  mint: 'linuxmint.svg',
  elementary: 'elementary.svg',
  pop: 'popos.svg',
  'pop-os': 'popos.svg',
  pop_os: 'popos.svg',
  gentoo: 'gentoo.svg',
  kali: 'kali.svg',
  raspbian: 'raspberry-pi.svg',
  raspberrypi: 'raspberry-pi.svg',
  linux: 'linux.svg',
}

const LIKE_PRIORITY = [
  'ubuntu',
  'debian',
  'rhel',
  'fedora',
  'suse',
  'arch',
  'alpine',
]

export function resolveOsLogo(osId?: string | null, osIdLike?: string | null): string {
  const id = (osId || '').toLowerCase().trim()
  if (id && ID_TO_LOGO[id]) {
    return `/os-logos/${ID_TO_LOGO[id]}`
  }
  const likes = (osIdLike || '').toLowerCase().split(/\s+/).filter(Boolean)
  for (const key of LIKE_PRIORITY) {
    if (likes.includes(key) && ID_TO_LOGO[key]) {
      return `/os-logos/${ID_TO_LOGO[key]}`
    }
  }
  for (const like of likes) {
    if (ID_TO_LOGO[like]) return `/os-logos/${ID_TO_LOGO[like]}`
  }
  return '/os-logos/linux.svg'
}

export const OS_LOGO_FILES = Object.values(ID_TO_LOGO)
