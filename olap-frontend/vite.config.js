import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard runs on :3000 and forwards /api calls to the Go API on :8080,
// so the browser never needs CORS. Override the target with API_TARGET.
//
// VITE_POLL=true makes the dev server check files on a timer instead of
// waiting for change events. Docker bind mounts on macOS and Windows don't
// pass those events into the container, so without it edits never reach the
// browser; docker compose sets it for the web service.
const poll = process.env.VITE_POLL === 'true'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    watch: poll ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      '/api': {
        target: process.env.API_TARGET || 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
