import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // GitHub Pages ではリポジトリ名がパスに入る（例 /puddle-twin-tokyo/）。
  // ワークフローから VITE_BASE を渡す。ローカルや独自ドメインでは / のまま。
  const env = loadEnv(mode, '.', 'VITE_');
  return {
  base: env.VITE_BASE || '/',
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
  };
});
