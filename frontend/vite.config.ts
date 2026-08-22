import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // バックエンド(uvicorn app.main:app --port 8000)へ転送する。
    // これで開発中はフロントとAPIが同一オリジンになり、CORSを気にせず済む。
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
