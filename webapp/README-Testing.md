# Frontend Testing with Vitest

This project now includes comprehensive frontend JavaScript unit tests using Vitest.

## Test Structure

```
src/
├── store/
│   ├── store.js
│   └── store.test.js      # Store state management tests
├── utils/
│   ├── data.js
│   ├── data.test.js       # Data filtering and API tests
│   ├── time.js
│   └── time.test.js       # Time formatting and utility tests
└── test/
    └── setup.js           # Test setup and mocks
```

## Running Tests

```bash
# Run tests in watch mode (development)
npm test

# Run tests once (CI/CD)
npm run test:run

# Run tests with UI dashboard
npm run test:ui

# Run tests with coverage report
npm run test:coverage

# Legacy HTML test runner (for comparison)
npm run test:legacy
```

## Test Coverage

### Store Tests (`src/store/store.test.js`)
- ✅ Basic state management and listeners
- ✅ Configuration initialization
- ✅ Wind data management (add, filter, deduplicate)
- ✅ Time window filtering
- ✅ Connection status management
- ✅ Chart data generation
- ✅ Current conditions tracking
- ✅ Computed properties caching
- ✅ Batch operations

### Data Utilities Tests (`src/utils/data.test.js`)
- ✅ Time-based data filtering
- ✅ Historical data loading (live/historical modes)
- ✅ Data gap filling
- ✅ API error handling
- ✅ Network request mocking

### Time Utilities Tests (`src/utils/time.test.js`)
- ✅ Wind direction text conversion
- ✅ Time formatting (live/historical with timezones)
- ✅ Date manipulation utilities
- ✅ Navigation helpers
- ✅ Edge case handling

## Key Features

- **Fast**: Vitest runs tests in milliseconds
- **Isolated**: Each test runs in isolation with fresh state
- **Mocked**: External dependencies (fetch, Chart.js, Sentry) are mocked
- **Comprehensive**: Covers core business logic and edge cases
- **Developer Friendly**: Hot reload in watch mode, clear error messages

## Integration with Existing Tests

This unit test suite complements the existing E2E Playwright tests:

- **Unit Tests**: Test individual functions and business logic
- **E2E Tests**: Test complete user workflows and browser interactions

Together, they provide comprehensive test coverage across the testing pyramid.