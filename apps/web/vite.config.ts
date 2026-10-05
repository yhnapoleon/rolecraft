import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// Development/preview forwarding only. Existing backend routes stay unchanged.
const proxy = {
  '/api': {
    target: process.env.ROLECRAFT_API_TARGET || 'http://127.0.0.1:8502',
    changeOrigin: false,
    rewrite: (path: string) => path.replace(/^\/api(?=\/)/, ''),
  },
};
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      input: {
        workbench: fileURLToPath(new URL('./index.html', import.meta.url)),
        connected: fileURLToPath(new URL('./connected/index.html', import.meta.url)),
      },
    },
  },
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
});
