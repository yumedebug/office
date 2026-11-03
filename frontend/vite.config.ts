import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The bundle is loaded from disk by QWebEngineView (file:// URL), therefore
// every generated asset path must be relative.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: 'assets',
    target: 'es2020',
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
