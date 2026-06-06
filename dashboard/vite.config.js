import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 600,  // Recharts is ~155 KB gzip; warning is a false positive
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'charts': ['recharts'],
          'utils': ['date-fns'],
        },
      },
    },
  },
  server: {
    port: 3000,
    // Proxy /api/* to the API Gateway URL in dev so the browser never
    // hits a CORS preflight against localhost. Set VITE_API_URL in .env
    // and remove this proxy for prod builds.
    proxy: process.env.VITE_API_URL
      ? {
          '/api': {
            target: process.env.VITE_API_URL,
            changeOrigin: true,
            rewrite: (path) => path.replace(/^\/api/, ''),
          },
        }
      : {},
  },
})
