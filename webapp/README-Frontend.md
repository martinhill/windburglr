# WindBurglr Frontend Build System

## Overview

The WindBurglr frontend has been successfully modularized and now uses Vite as a modern build system. The previous 900+ line monolithic JavaScript file has been broken down into focused, maintainable modules.

## Architecture

### New Module Structure

```
src/
├── main.js                    # Application entry point and orchestration
├── chart/
│   ├── config.js             # Chart.js configuration and management
│   └── zoom.js               # Chart zoom controls and interactions
├── websocket/
│   └── connection.js         # WebSocket connection management
├── ui/
│   ├── conditions.js         # Current conditions display
│   └── mobile.js             # Mobile orientation handling
├── store/
│   └── store.js              # Centralized state management
└── utils/
    ├── data.js               # Data fetching and processing
    └── time.js               # Time formatting utilities
```

### Build System

- **Vite**: Modern build tool with fast HMR and optimized production builds
- **ES Modules**: Native browser module support for better tree-shaking
- **Development Mode**: Hot module replacement for faster development
- **Production Mode**: Optimized bundles with cache-busting hashes

## Usage

### Development Mode

1. Install dependencies:
   ```bash
   npm install
   ```

2. Start the Vite dev server:
   ```bash
   npm run dev
   ```

3. Start the backend with dev mode enabled:
   ```bash
   DEV_MODE=true python main.py
   ```

In development mode, the application will load modules directly from the Vite dev server with hot module replacement.

### Production Mode

1. Build the frontend:
   ```bash
   npm run build
   ```

2. Start the backend normally:
   ```bash
   python main.py
   ```

The built assets will be served from the `/dist` directory.

### Preview Production Build

```bash
npm run preview
```

### Testing

Due to CORS restrictions, test files cannot be opened directly in browsers. Use one of these methods:

**Method 1: Python HTTP Server (Recommended)**
```bash
python -m http.server 3000
# Then open: http://localhost:3000/test-store.html
# Or: http://localhost:3000/test-navigation.html
```

**Method 2: Vite Dev Server**
```bash
npm run dev
# Then open: http://localhost:5173/test-store.html
# Or: http://localhost:5173/test-navigation.html
```

**Method 3: Quick Test Commands**
```bash
npm run test:store    # Opens store tests
npm run test:nav      # Opens navigation tests
```

## Key Improvements

### Code Organization
- **Separation of Concerns**: Each module handles a specific responsibility
- **Reusable Components**: Functions can be imported and used across modules  
- **Clear Dependencies**: Import/export statements make dependencies explicit
- **Easier Testing**: Individual modules can be tested in isolation

### Performance
- **Tree Shaking**: Unused code is eliminated in production builds
- **Code Splitting**: Potential for lazy loading of modules
- **Optimized Bundles**: Vite produces efficient, minified builds
- **Modern JavaScript**: Leverages native ES modules and modern browser features

### Developer Experience
- **Hot Module Replacement**: Changes appear instantly during development
- **Better Error Messages**: Module-level error reporting
- **IDE Support**: Better autocomplete and refactoring with explicit imports
- **Maintainability**: Smaller, focused files are easier to understand and modify

## Build Output

Production builds create:
- `dist/js/main-[hash].js` - Main application bundle
- Hash-based filenames for cache busting
- Optimized and minified code

## Next Steps

### Potential Enhancements
1. **TypeScript**: Add type safety for better development experience
2. **CSS Modules**: Modularize stylesheets alongside JavaScript
3. **Testing Setup**: Add unit tests for individual modules
4. **Bundle Analysis**: Monitor bundle size and optimize imports
5. **PWA Features**: Add service worker for offline capability

### Migration Notes
- The original inline JavaScript has been completely replaced
- All functionality has been preserved in the modular structure
- Template variables are now passed via `window` globals
- Development and production modes are handled automatically

## Directory Structure

```
webapp/
├── src/                      # Frontend source code (development only)
│   ├── main.js              # Application entry point
│   ├── store/               # State management
│   ├── chart/               # Chart components
│   ├── websocket/           # WebSocket handling
│   ├── ui/                  # UI components
│   └── utils/               # Utility functions
├── static/                  # Static assets (served directly)
│   ├── style.css           # Main stylesheet
│   ├── *.png, *.svg, *.ico # Icons and images
│   └── site.webmanifest    # PWA manifest
├── dist/                    # Built assets (production)
│   └── js/main-[hash].js   # Bundled JavaScript
├── templates/               # Jinja2 templates
├── app/                     # Backend Python code
└── tests/                   # Test files
```

## Files Modified

- `package.json` - Added Vite and Chart.js dependencies
- `vite.config.js` - Vite configuration for build and dev server
- `templates/index.html` - Updated to conditionally load dev/prod assets
- `app/routers/web.py` - Added `dev_mode` template variable
- `main.py` - Added `/dist` static file mount
- **Directory restructure**: Moved `static/src/` → `src/`

The refactoring maintains all existing functionality while providing a modern, maintainable foundation for future frontend development.