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

  // In development the browser talks only to Vite (make dev), which serves the frontend
  // modules and passes everything else (pages, /api, /static) to the backend. One origin
  // works the same on localhost, over Tailscale or through a tunnel.
  server: {
    allowedHosts: ['.ts.net'],
    proxy: {
      '^/(?!@vite/|@id/|@fs/|src/|node_modules/)': {
        // 127.0.0.1, not localhost: Node may resolve localhost to ::1, where the
        // backend doesn't listen
        target: `http://127.0.0.1:${process.env.BACKEND_PORT ?? 8000}`,
      },
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
