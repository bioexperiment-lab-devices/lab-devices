import { Monitor, Moon, Sun } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cycleSetting, type ThemeSetting } from '../stores/themeSetting'
import { useThemeStore } from '../stores/themeStore'
import { IconButton } from '../ui/IconButton'

/** The icon shows the SETTING (Monitor = following the OS), not the effective theme —
 * a Monitor icon that flipped to Moon whenever the OS went dark would read as "you
 * chose dark" when the user chose "follow the system". */
const ICONS: Record<ThemeSetting, LucideIcon> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
}

export function ThemeToggle() {
  const setting = useThemeStore((s) => s.setting)
  const cycle = useThemeStore((s) => s.cycle)
  return (
    <IconButton
      icon={ICONS[setting]}
      label={`Theme: ${setting} — switch to ${cycleSetting(setting)}`}
      onClick={cycle}
    />
  )
}
