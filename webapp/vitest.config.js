import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.{test,spec}.js'],
    coverage: {
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.js'],
      exclude: ['src/**/*.{test,spec}.js', 'src/test/**']
    }
  },
  // Use existing Vite config for module resolution
  resolve: {
    alias: {
      '@': '/src'
    }
  }
})