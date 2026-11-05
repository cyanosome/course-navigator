import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 開発サーバーで /api を送る先（例 NAVI_API_PROXY=http://localhost:8000 npm run dev）。送る先では /api を剥がす（Traefik と同じ）。
// 未設定なら送らない（compose では Traefik が /api を backend へ送る）
const apiProxy = process.env.NAVI_API_PROXY

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      usePolling: true,
    },
    proxy:
      apiProxy === undefined
        ? undefined
        : { '/api': { target: apiProxy, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') } },
  },
})
