// Light / dark theme. With no choice saved the page follows the system setting
// (the prefers-color-scheme block in styles.css); choosing one pins it with
// data-theme on <html> and remembers it in this browser. index.html applies a
// saved choice before the first paint, so a dark page never flashes light.

export const THEME_KEY = 'road-runner-theme'

export const isTheme = (value) => value === 'light' || value === 'dark'
export const otherTheme = (theme) => (theme === 'dark' ? 'light' : 'dark')

// The theme on screen: the pinned one, else whatever the system asks for.
export function currentTheme(root = document.documentElement, media = window.matchMedia) {
  const pinned = root.dataset.theme
  if (isTheme(pinned)) return pinned
  return media?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

// Pin a theme and remember it. Storage can be unavailable (a private window,
// blocked site data), in which case the choice still applies until reload.
export function applyTheme(theme, root = document.documentElement, storage = window.localStorage) {
  root.dataset.theme = theme
  try {
    storage.setItem(THEME_KEY, theme)
  } catch {
    // keep the on-screen choice; it just won't survive a reload
  }
}
