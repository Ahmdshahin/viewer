import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// The ledger field registry lives at <repo>/shared/ledger_fields.json so the
// frontend table and the backend export share one definition. Allow the dev
// server to serve files from the repo root (the workspace root is frontend/).
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    tailwindcss(),
    react()
  ],
  server: {
    host: true,
    port: 5173,
    fs: {
      allow: [repoRoot]
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  optimizeDeps: {
    exclude: ['maplibre-gl']
  }
})
