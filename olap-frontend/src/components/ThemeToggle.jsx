import { useEffect, useState } from 'react'
import { applyTheme, currentTheme, otherTheme } from '../lib/theme.js'
import { MoonIcon, SunIcon } from './Icons.jsx'

// Switches between light and dark mode. The label names the mode a click
// switches to; until the viewer picks one, the page follows the system
// setting, and this keeps up if that setting changes.
export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => currentTheme())

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return undefined
    const follow = () => setTheme(currentTheme())
    media.addEventListener('change', follow)
    return () => media.removeEventListener('change', follow)
  }, [])

  const next = otherTheme(theme)
  const Icon = next === 'dark' ? MoonIcon : SunIcon

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => {
        applyTheme(next)
        setTheme(next)
      }}
      aria-label={`Switch to ${next} mode`}
    >
      <Icon className="theme-toggle-icon" />
      <span>{next === 'dark' ? 'Dark mode' : 'Light mode'}</span>
    </button>
  )
}
