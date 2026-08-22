/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** バックエンドAPIのベースURL。未設定なら /api（開発時はViteのプロキシ経由）。 */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
