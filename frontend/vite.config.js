import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发时把 /api 转发给 FastAPI，无需在前端配置跨域
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,   // 任务完成推送走 WebSocket（/api/ws/jobs）
      },
    },
  },
  build: {
    // 生产构建输出到 agent_lab/static，FastAPI 直接托管
    outDir: '../agent_lab/static',
    emptyOutDir: true,
  },
})
