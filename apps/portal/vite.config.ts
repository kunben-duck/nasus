import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxyTarget = process.env.NASUS_PORTAL_API_PROXY ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    preserveSymlinks: true,
  },
  server: {
    proxy: {
      '/v1': apiProxyTarget,
      '/healthz': apiProxyTarget,
    },
  },
})
