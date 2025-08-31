# Simple Store Pattern Implementation

## Overview

WindBurglr now uses a centralized store pattern for state management. This implementation provides a single source of truth for all application state while maintaining low complexity and high maintainability.

## Architecture

### Store Structure
```
static/src/store/
└── store.js          # Main store implementation with singleton instance
```

### State Organization
```javascript
{
  // Wind data
  windData: [],
  lastObservationTime: null,
  
  // Time window
  currentTimeWindowHours: 3,
  
  // Configuration
  config: { station, isLive, dateStart, dateEnd, stationTimezone, hours },
  
  // Connection state
  connectionStatus: 'disconnected',
  connectionText: 'Disconnected',
  
  // Chart state
  chartInstance: null,
  isChartInitialized: false,
  
  // Zoom state
  zoomRange: null,
  originalTimeRange: null,
  
  // UI state
  isLoading: false,
  
  // Current conditions
  currentConditions: { speed_kts, direction, gust_kts, timestamp }
}
```

## Key Features

### 1. **Single Source of Truth**
- All application state lives in one centralized store
- Components subscribe to store changes for reactive updates
- No more prop drilling or scattered state management

### 2. **Simple API**
```javascript
// Initialize store
store.initialize(config);

// Subscribe to changes
const unsubscribe = store.subscribe((state, prevState, source) => {
  // Handle state changes
});

// Update state
store.setState({ isLoading: true }, 'source-name');

// Specific action methods
store.setWindData(data, 'api-load');
store.addWindData(newPoint, 'websocket');
store.setTimeWindow(6, 'user-selection');
store.setConnectionStatus('connected', 'Connected', 'websocket');
```

### 3. **Computed Properties with Caching**
```javascript
// Automatically filtered based on time window
const filteredData = store.getFilteredWindData();

// Chart.js formatted data
const chartData = store.getChartData();
```

### 4. **Source Tracking**
Every state change includes a source identifier for debugging:
- `'initial-load'` - Initial data loading
- `'websocket'` - Real-time WebSocket data
- `'user-selection'` - User interface actions  
- `'gap-fill'` - Filling data gaps on reconnection
- `'time-window-filter'` - Time window changes

### 5. **Automatic Data Processing**
- **Deduplication**: Prevents duplicate data points
- **Time filtering**: Automatically applies time window filtering for live data
- **Data limits**: Maintains maximum of 1000 data points
- **Sorting**: Keeps data chronologically ordered

## Component Integration

### ChartManager
```javascript
// Subscribe to store changes
this.unsubscribeStore = store.subscribe((state, prevState, source) => {
  if (state.windData !== prevState.windData) {
    this.updateChart();
  }
});

// Update chart with store data
updateChart() {
  const chartData = store.getChartData();
  this.chart.data.labels = chartData.timeData;
  // ...
}
```

### WebSocketManager
```javascript
// Add new data to store
const newPoint = [data.timestamp, data.direction, data.speed_kts, data.gust_kts];
store.addWindData(newPoint, 'websocket');

// Update connection status
store.setConnectionStatus('connected', 'Connected (Live)', 'websocket');
```

### ConditionsManager
```javascript
// Subscribe to conditions changes
store.subscribe((state, prevState, source) => {
  if (state.currentConditions !== prevState.currentConditions) {
    this.updateDisplay(state.currentConditions, state.config);
  }
});
```

## Benefits Achieved

### 1. **Eliminated State Synchronization Issues**
- **Before**: Manual parameter passing between components
- **After**: Automatic synchronization via store subscriptions

### 2. **Centralized Business Logic**
- **Before**: Data filtering scattered across components  
- **After**: All data processing logic in store actions

### 3. **Improved Debugging**
- **Before**: Hard to track state changes
- **After**: Source tracking and centralized logging

### 4. **Simplified Component Logic**
- **Before**: Complex state management in each component
- **After**: Components focus on UI, store handles state

### 5. **Better Testing**
- **Before**: Integration tests required for state interactions
- **After**: Store can be tested in isolation

## Complexity Comparison

### Simple Store vs Alternatives

| Feature | Simple Store | Redux | Zustand | MobX |
|---------|--------------|-------|---------|------|
| **Bundle Size** | ~2KB | ~10KB | ~1KB | ~15KB |
| **Learning Curve** | Low | High | Medium | Medium |
| **Boilerplate** | Minimal | High | Low | Medium |
| **DevTools** | Basic | Excellent | Good | Good |
| **Reactivity** | Manual | Manual | Automatic | Automatic |

### Why Simple Store for WindBurglr?
- **Application size**: Medium complexity doesn't justify Redux overhead
- **Team familiarity**: Simple patterns are easier to understand and maintain
- **Performance**: Manual subscriptions provide fine-grained control
- **Flexibility**: Easy to evolve to more complex patterns if needed

## Usage Examples

### Time Range Selection
```javascript
// User changes time range selector
timeRangeSelect.addEventListener('change', async (e) => {
  const hours = parseInt(e.target.value);
  store.setTimeWindow(hours, 'user-selection');
  await loadInitialData(); // Reload with new window
});
```

### WebSocket Data Handling
```javascript
// WebSocket receives new data
if (data.timestamp !== undefined) {
  // Update current conditions
  store.setCurrentConditions({
    speed_kts: data.speed_kts,
    direction: data.direction,
    gust_kts: data.gust_kts,
    timestamp: data.timestamp
  }, 'websocket');
  
  // Add to wind data array
  const newPoint = [data.timestamp, data.direction, data.speed_kts, data.gust_kts];
  store.addWindData(newPoint, 'websocket');
}
```

### Chart Zoom Integration
```javascript
// ZoomController performs zoom
store.setZoomRange({
  min: minTime,
  max: maxTime
}, originalTimeRange);

// ChartManager automatically updates via subscription
```

## Migration Path

The implementation maintains backward compatibility:

1. **Gradual migration**: Components can be updated incrementally
2. **Legacy functions**: Existing function signatures still work
3. **No breaking changes**: Template and API remain the same

## Testing

Run the store tests:
```bash
# Open in browser
open test-store.html
```

Tests verify:
- Basic state management
- Listener subscriptions
- Wind data operations
- Time window filtering
- Connection status updates
- Computed properties
- Duplicate filtering

## Future Enhancements

The simple store provides a foundation for:

1. **Persistence**: Add localStorage/IndexedDB support
2. **Undo/Redo**: Implement state history tracking
3. **Middleware**: Add async action handling
4. **DevTools**: Create custom development tools
5. **Performance**: Add memoization and optimization
6. **Migration**: Easy path to Redux/Zustand if needed

The implementation successfully centralizes state management while keeping complexity low and maintainability high.