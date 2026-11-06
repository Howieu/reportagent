import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const api = 'http://127.0.0.1:8501';
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../reportagent/static', emptyOutDir: true },
  server: { proxy: { '/api': api, '/reports': api, '/funnel': api } },
});
