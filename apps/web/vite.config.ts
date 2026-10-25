import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { PRODUCT_NAME } from './src/app/product.js';

// Development/preview forwarding only. Existing backend routes stay unchanged.
const proxy = {
  '/api': {
    target: process.env.ROLECRAFT_API_TARGET || 'http://127.0.0.1:8502',
    changeOrigin: false,
    rewrite: (path: string) => path.replace(/^\/api(?=\/)/, ''),
  },
};
// index.html names the product through %PRODUCT_NAME%, from the same constant the workbench uses.
const productName = {
  name: 'rolecraft-product-name',
  transformIndexHtml: (html: string) => html.replaceAll('%PRODUCT_NAME%', PRODUCT_NAME),
};
export default defineConfig({
  // Tailwind only reaches src/islands/tw.css (prefixed tw:, no preflight); see that file.
  plugins: [react(), tailwindcss(), productName],
  build: {
    rolldownOptions: {
      input: {
        workbench: fileURLToPath(new URL('./index.html', import.meta.url)),
      },
    },
  },
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
});
