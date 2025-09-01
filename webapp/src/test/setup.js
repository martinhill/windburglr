// Test setup file for Vitest
// Mock browser APIs that aren't available in jsdom

// Mock fetch for API calls
global.fetch = vi.fn()

// Mock Chart.js
vi.mock('chart.js', () => ({
  Chart: vi.fn(() => ({
    destroy: vi.fn(),
    update: vi.fn(),
    data: { datasets: [] }
  })),
  registerables: []
}))

// Mock Sentry
global.Sentry = {
  captureException: vi.fn(),
  captureMessage: vi.fn()
}

// Mock console methods to avoid noise in tests
global.console = {
  ...console,
  debug: vi.fn(),
  log: vi.fn()
}