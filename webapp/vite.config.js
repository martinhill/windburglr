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

    // Maps are uploaded to Sentry and then deleted; 'hidden' omits the sourceMappingURL
    // comment so browsers don't request them
    sourcemap: 'hidden'
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
    // Docker builds have no .git to detect the release from, so the Dockerfile passes it
    release: { name: process.env.SENTRY_RELEASE },
  })]
})
