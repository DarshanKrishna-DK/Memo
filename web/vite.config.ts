import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// All backend paths go to FastAPI (backend/app/main.py) so cookies stay same-origin in dev.
const BACKEND = process.env.MEMO_BACKEND_URL || 'http://127.0.0.1:8000';
const PROXY = Object.fromEntries(
  ['^/api/', '^/media/', '^/m/', '^/i/', '^/webhooks/', '^/twilio/'].map((p) => [p, { target: BACKEND, changeOrigin: true }]),
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, open: false, proxy: PROXY, allowedHosts: ['.trycloudflare.com', 'localhost'] },
  preview: { port: 5173, proxy: PROXY },
});
