/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_PUBLIC_HOSTNAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
