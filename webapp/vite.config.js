import { sentryVitePlugin } from "@sentry/vite-plugin";
import { defineConfig } from 'vite'

export default defineConfig({
  root: '.',

  // Resolve src/test/ files correctly
  resolve: {
    alias: {
      '@': '/src'
    }
  },

  build: {
    outDir: 'dist',
    emptyOutDir: true,

    rollupOptions: {
      input: 'src/main.js',
      output: {
        entryFileNames: 'js/[name]-[hash].js',
        chunkFileNames: 'js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name?.endsWith('.css')) {
            return 'css/[name]-[hash][extname]'
          }
          return 'assets/[name]-[hash][extname]'
        }
      }
    },

    sourcemap: true
  },

  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  },

  plugins: [sentryVitePlugin({
    org: "martin-hill",
    project: "windburglr",
    authToken: process.env.SENTRY_AUTH_TOKEN,
  })]
})
