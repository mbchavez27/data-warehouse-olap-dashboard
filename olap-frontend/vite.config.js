import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard runs on :3000 and forwards /api calls to the Go API on :8080,
// so the browser never needs CORS. Override the target with API_TARGET.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: process.env.API_TARGET || 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
