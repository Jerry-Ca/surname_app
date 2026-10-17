import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 同源策略：开发时把 /api 代理到本地后端，生产由 Nginx 反代（见 deploy/nginx/surname_app.conf）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})