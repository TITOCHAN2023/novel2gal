import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 资产文件代理到后端
      '/assets': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // API 代理到后端
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // WebSocket 代理到后端
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
})
