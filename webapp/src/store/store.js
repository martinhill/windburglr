/**
 * Simple Store Pattern for WindBurglr
 * Centralized state management with minimal complexity
 */

import { filterOldObservations } from '../utils/data.js';

class Store {
    constructor() {
        // Application state
        this.state = {
            // Wind data
            windData: [],
            lastObservationTime: null,
            
            // Time window settings
            currentTimeWindowHours: 3,
            
            // Application configuration
            config: {
                station: '',
                isLive: false,
                dateStart: null,
                dateEnd: null,
                stationTimezone: null,
                hours: 3
            },
            
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
            currentConditions: {
                speed_kts: null,
                direction: null,
                gust_kts: null,
                timestamp: null
            }
        };
        
        this.listeners = [];
        this.computedCache = new Map();
    }
    
    /**
     * Subscribe to state changes
     */
    subscribe(listener) {
        this.listeners.push(listener);
        // Return unsubscribe function
        return () => {
            const index = this.listeners.indexOf(listener);
            if (index > -1) {
                this.listeners.splice(index, 1);
            }
        };
    }
    
    /**
     * Get current state (immutable)
     */
    getState() {
        return { ...this.state };
    }
    
    /**
     * Update state and notify listeners
     */
    setState(updates, source = 'unknown') {
        const prevState = { ...this.state };
        this.state = { ...this.state, ...updates };
        
        // Clear computed cache when relevant state changes
        this.clearComputedCache(updates);
        
        // Notify listeners
        this.listeners.forEach(listener => {
            try {
                listener(this.state, prevState, source);
            } catch (error) {
                console.error('Store listener error:', error);
            }
        });
        
        // Debug logging
        if (console.debug) {
            console.debug(`[Store] State updated by ${source}:`, updates);
        }
    }
    
    /**
     * Initialize store with configuration
     */
    initialize(config) {
        this.setState({
            config: { ...this.state.config, ...config },
            currentTimeWindowHours: config.hours || 3
        }, 'initialize');
    }
    
    // === Wind Data Actions ===
    
    /**
     * Set wind data (replaces existing data)
     */
    setWindData(data, source = 'api') {
        let processedData = Array.isArray(data) ? [...data] : [];
        
        // Apply time window filtering for live data
        if (this.state.config.isLive && this.state.currentTimeWindowHours > 0) {
            processedData = filterOldObservations(
                processedData, 
                true, 
                this.state.currentTimeWindowHours
            );
        }
        
        // Limit data size
        if (processedData.length > 1000) {
            processedData = processedData.slice(-1000);
        }
        
        // Update last observation time
        let lastObservationTime = this.state.lastObservationTime;
        if (processedData.length > 0) {
            const latestTimestamp = Math.max(...processedData.map(d => d[0]));
            if (!lastObservationTime || latestTimestamp > lastObservationTime) {
                lastObservationTime = latestTimestamp;
            }
        }
        
        this.setState({
            windData: processedData,
            lastObservationTime
        }, source);
    }
    
    /**
     * Add new wind data point
     */
    addWindData(newPoint, source = 'websocket') {
        const existingData = [...this.state.windData];
        
        // Check for duplicates
        const isDuplicate = existingData.some(existingPoint =>
            Math.abs(existingPoint[0] - newPoint[0]) < 1
        );
        
        if (isDuplicate) {
            console.log('Discarding duplicate wind data point:', newPoint);
            return;
        }
        
        console.log('New wind data point:', newPoint);
        existingData.push(newPoint);
        existingData.sort((a, b) => a[0] - b[0]);
        
        // Use setWindData to apply filtering and limits
        this.setWindData(existingData, source);
    }
    
    /**
     * Add multiple wind data points (for gap filling)
     */
    addWindDataBatch(newData, source = 'gap-fill') {
        const existingData = [...this.state.windData];
        
        // Filter out duplicates
        const filteredNewData = newData.filter(newPoint => {
            return !existingData.some(existingPoint =>
                Math.abs(existingPoint[0] - newPoint[0]) < 1
            );
        });
        
        if (filteredNewData.length === 0) {
            console.log('No new data points after deduplication');
            return;
        }
        
        console.log(`Adding ${filteredNewData.length} new data points after deduplication`);
        const combinedData = existingData.concat(filteredNewData);
        combinedData.sort((a, b) => a[0] - b[0]);
        
        // Use setWindData to apply filtering and limits
        this.setWindData(combinedData, source);
    }
    
    // === Time Window Actions ===
    
    /**
     * Update time window hours
     */
    setTimeWindow(hours, source = 'user') {
        console.log(`Time range changed to: ${hours} hours`);
        this.setState({
            currentTimeWindowHours: hours
        }, source);
        
        // Re-filter existing data with new time window
        if (this.state.windData.length > 0 && this.state.config.isLive) {
            this.setWindData(this.state.windData, 'time-window-filter');
        }
    }
    
    // === Connection Actions ===
    
    /**
     * Update connection status
     */
    setConnectionStatus(status, text, source = 'websocket') {
        this.setState({
            connectionStatus: status,
            connectionText: text
        }, source);
    }
    
    // === Chart Actions ===
    
    /**
     * Set chart instance
     */
    setChartInstance(chart) {
        this.setState({
            chartInstance: chart,
            isChartInitialized: true
        }, 'chart-init');
    }
    
    /**
     * Set zoom range
     */
    setZoomRange(range, originalRange = null) {
        this.setState({
            zoomRange: range,
            originalTimeRange: originalRange || this.state.originalTimeRange
        }, 'zoom');
    }
    
    /**
     * Reset zoom
     */
    resetZoom() {
        this.setState({
            zoomRange: null,
            originalTimeRange: null
        }, 'zoom-reset');
    }
    
    // === Current Conditions Actions ===
    
    /**
     * Update current conditions display
     */
    setCurrentConditions(conditions, source = 'websocket') {
        this.setState({
            currentConditions: { ...conditions }
        }, source);
    }
    
    // === UI Actions ===
    
    /**
     * Set loading state
     */
    setLoading(isLoading, source = 'ui') {
        this.setState({ isLoading }, source);
    }
    
    // === Computed Properties ===
    
    /**
     * Get filtered wind data based on current time window
     */
    getFilteredWindData() {
        const cacheKey = 'filteredWindData';
        const cached = this.computedCache.get(cacheKey);
        
        if (cached && 
            cached.timestamp > Date.now() - 1000 && // Cache for 1 second
            cached.dataLength === this.state.windData.length &&
            cached.timeWindow === this.state.currentTimeWindowHours) {
            return cached.value;
        }
        
        let filtered = this.state.windData;
        
        if (this.state.config.isLive && this.state.currentTimeWindowHours > 0) {
            filtered = filterOldObservations(
                this.state.windData,
                true,
                this.state.currentTimeWindowHours
            );
        }
        
        const result = filtered;
        this.computedCache.set(cacheKey, {
            value: result,
            timestamp: Date.now(),
            dataLength: this.state.windData.length,
            timeWindow: this.state.currentTimeWindowHours
        });
        
        return result;
    }
    
    /**
     * Get chart data in format expected by Chart.js
     */
    getChartData() {
        const data = this.getFilteredWindData();
        
        return {
            timeData: data.map(d => new Date(d[0] * 1000)),
            speeds: data.map(d => d[2]),
            gusts: data.map(d => d[3]),
            directions: data.map(d => d[1] === null ? null : d[1])
        };
    }
    
    /**
     * Check if connection is active
     */
    isConnected() {
        return this.state.connectionStatus === 'connected';
    }
    
    /**
     * Check if application is in live mode
     */
    isLive() {
        return this.state.config.isLive;
    }
    
    // === Private Methods ===
    
    /**
     * Clear computed cache when relevant state changes
     */
    clearComputedCache(updates) {
        if (updates.windData || updates.currentTimeWindowHours) {
            this.computedCache.clear();
        }
    }
}

// Create singleton store instance
export const store = new Store();

// Export store class for testing
export { Store };