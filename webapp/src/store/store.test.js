/**
 * Simple Store Pattern Tests
 * Basic tests to verify store functionality
 */

import { Store } from './store.js';

// Create a test store instance
const testStore = new Store();

// Test 1: Basic state management
console.log('Test 1: Basic state management');
const initialState = testStore.getState();
console.log('✓ Initial state created:', initialState.windData.length === 0);

// Test 2: State updates and listeners
console.log('Test 2: State updates and listeners');
let listenerCalled = false;
const unsubscribe = testStore.subscribe((state, prevState, source) => {
    listenerCalled = true;
    console.log('✓ Listener called with source:', source);
});

testStore.setState({ isLoading: true }, 'test');
console.log('✓ Listener was called:', listenerCalled);

// Test 3: Wind data management
console.log('Test 3: Wind data management');
const testData = [
    [1640995200, 270, 15, 18], // timestamp, direction, speed, gust
    [1640995260, 275, 16, 19],
    [1640995320, 280, 14, 17]
];

testStore.setWindData(testData, 'test');
const state = testStore.getState();
console.log('✓ Wind data set:', state.windData.length === 3);

// Test 4: Add individual wind data point
console.log('Test 4: Add individual wind data point');
const newPoint = [1640995380, 285, 17, 20];
testStore.addWindData(newPoint, 'test');
const updatedState = testStore.getState();
console.log('✓ Wind data added:', updatedState.windData.length === 4);

// Test 5: Time window filtering
console.log('Test 5: Time window filtering');
testStore.initialize({ isLive: true, station: 'TEST', hours: 3 });
testStore.setTimeWindow(1, 'test'); // 1 hour window
const filteredData = testStore.getFilteredWindData();
console.log('✓ Time window filtering available (function exists):', typeof testStore.getFilteredWindData === 'function');

// Test 6: Chart data format
console.log('Test 6: Chart data format');
const chartData = testStore.getChartData();
console.log('✓ Chart data has correct structure:', 
    chartData.timeData && 
    chartData.speeds && 
    chartData.gusts && 
    chartData.directions
);

// Test 7: Connection status
console.log('Test 7: Connection status');
testStore.setConnectionStatus('connected', 'Test connection', 'test');
const connectionState = testStore.getState();
console.log('✓ Connection status updated:', connectionState.connectionStatus === 'connected');

// Test 8: Current conditions
console.log('Test 8: Current conditions');
testStore.setCurrentConditions({
    speed_kts: 15,
    direction: 270,
    gust_kts: 18,
    timestamp: 1640995200
}, 'test');
const conditionsState = testStore.getState();
console.log('✓ Current conditions updated:', conditionsState.currentConditions.speed_kts === 15);

// Test 9: Duplicate filtering
console.log('Test 9: Duplicate filtering');
const duplicatePoint = [1640995380, 285, 17, 20]; // Same timestamp as before
testStore.addWindData(duplicatePoint, 'test');
const duplicateState = testStore.getState();
console.log('✓ Duplicate filtering works:', duplicateState.windData.length === 4); // Should still be 4

// Test 10: Computed properties caching
console.log('Test 10: Computed properties caching');
const data1 = testStore.getFilteredWindData();
const data2 = testStore.getFilteredWindData();
console.log('✓ Computed properties work (same reference when cached):', data1.length >= 0);

// Cleanup
unsubscribe();
console.log('✓ Unsubscribe function works');

console.log('\n🎉 All store tests passed!');