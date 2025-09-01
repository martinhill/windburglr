import { describe, it, expect, beforeEach, vi } from 'vitest'
import { Store } from './store.js'

describe('Store', () => {
  let store

  beforeEach(() => {
    store = new Store()
  })

  describe('Basic State Management', () => {
    it('should initialize with default state', () => {
      const state = store.getState()
      
      expect(state.windData).toEqual([])
      expect(state.currentTimeWindowHours).toBe(3)
      expect(state.connectionStatus).toBe('disconnected')
      expect(state.isLoading).toBe(false)
    })

    it('should update state and notify listeners', () => {
      const listener = vi.fn()
      store.subscribe(listener)

      store.setState({ isLoading: true }, 'test')

      expect(store.getState().isLoading).toBe(true)
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({ isLoading: true }),
        expect.objectContaining({ isLoading: false }),
        'test'
      )
    })

    it('should return unsubscribe function', () => {
      const listener = vi.fn()
      const unsubscribe = store.subscribe(listener)

      store.setState({ isLoading: true }, 'test')
      expect(listener).toHaveBeenCalledTimes(1)

      unsubscribe()
      store.setState({ isLoading: false }, 'test')
      expect(listener).toHaveBeenCalledTimes(1) // Should not be called again
    })
  })

  describe('Configuration', () => {
    it('should initialize with configuration', () => {
      const config = {
        station: 'CYYZ',
        isLive: true,
        hours: 6
      }

      store.initialize(config)
      const state = store.getState()

      expect(state.config.station).toBe('CYYZ')
      expect(state.config.isLive).toBe(true)
      expect(state.currentTimeWindowHours).toBe(6)
    })
  })

  describe('Wind Data Management', () => {
    const testData = [
      [1640995200, 270, 15, 18], // [timestamp, direction, speed, gust]
      [1640995260, 275, 16, 19],
      [1640995320, 280, 14, 17]
    ]

    it('should set wind data', () => {
      store.setWindData(testData, 'test')
      const state = store.getState()

      expect(state.windData).toEqual(testData)
      expect(state.lastObservationTime).toBe(1640995320) // Latest timestamp
    })

    it('should add individual wind data point', () => {
      store.setWindData(testData, 'initial')
      const newPoint = [1640995380, 285, 17, 20]
      
      store.addWindData(newPoint, 'websocket')
      const state = store.getState()

      expect(state.windData).toHaveLength(4)
      expect(state.windData[3]).toEqual(newPoint)
      expect(state.lastObservationTime).toBe(1640995380)
    })

    it('should prevent duplicate data points', () => {
      store.setWindData(testData, 'initial')
      const duplicatePoint = [1640995320, 285, 17, 20] // Same timestamp as existing
      
      store.addWindData(duplicatePoint, 'websocket')
      const state = store.getState()

      expect(state.windData).toHaveLength(3) // Should not add duplicate
    })

    it('should sort data points by timestamp', () => {
      const unsortedData = [
        [1640995320, 280, 14, 17],
        [1640995200, 270, 15, 18], // Earlier timestamp
        [1640995260, 275, 16, 19]
      ]
      
      store.setWindData(unsortedData, 'test')
      store.addWindData([1640995380, 285, 17, 20], 'websocket')
      
      const state = store.getState()
      const timestamps = state.windData.map(point => point[0])
      
      expect(timestamps).toEqual([1640995200, 1640995260, 1640995320, 1640995380])
    })

    it('should limit data size to 1000 points', () => {
      const largeDataSet = Array.from({ length: 1200 }, (_, i) => [
        1640995200 + i * 60,
        270,
        15,
        18
      ])

      store.setWindData(largeDataSet, 'test')
      const state = store.getState()

      expect(state.windData).toHaveLength(1000)
      // Should keep the most recent 1000 points
      expect(state.windData[0][0]).toBe(1640995200 + 200 * 60)
    })
  })

  describe('Time Window Management', () => {
    beforeEach(() => {
      // Set up live mode
      store.initialize({ isLive: true, station: 'TEST' })
    })

    it('should update time window', () => {
      store.setTimeWindow(6, 'user')
      const state = store.getState()

      expect(state.currentTimeWindowHours).toBe(6)
    })

    it('should filter data when time window changes in live mode', () => {
      // Mock current time to be predictable
      const mockNow = 1640999000 // Mock current time
      vi.spyOn(Date, 'now').mockReturnValue(mockNow * 1000)

      const testData = [
        [mockNow - 7200, 270, 15, 18], // 2 hours ago
        [mockNow - 3600, 275, 16, 19], // 1 hour ago  
        [mockNow - 1800, 280, 14, 17], // 30 minutes ago
        [mockNow - 900, 285, 17, 20]   // 15 minutes ago
      ]

      store.setWindData(testData, 'initial')
      // In live mode with default 3-hour window, all 4 points should be kept
      expect(store.getState().windData).toHaveLength(4)

      // Set 1 hour window - should filter out points older than 1 hour
      store.setTimeWindow(1, 'user')
      
      const filteredData = store.getFilteredWindData()
      expect(filteredData).toHaveLength(3) // Points within 1 hour window from cutoff time
    })
  })

  describe('Connection Management', () => {
    it('should update connection status', () => {
      store.setConnectionStatus('connected', 'Connected to server', 'websocket')
      const state = store.getState()

      expect(state.connectionStatus).toBe('connected')
      expect(state.connectionText).toBe('Connected to server')
    })

    it('should check connection status', () => {
      expect(store.isConnected()).toBe(false)
      
      store.setConnectionStatus('connected', 'Connected', 'websocket')
      expect(store.isConnected()).toBe(true)
    })
  })

  describe('Chart Data Generation', () => {
    it('should generate chart data in correct format', () => {
      const testData = [
        [1640995200, 270, 15, 18],
        [1640995260, 275, 16, 19],
        [1640995320, null, 14, 17] // Test null direction
      ]

      store.setWindData(testData, 'test')
      const chartData = store.getChartData()

      expect(chartData).toHaveProperty('timeData')
      expect(chartData).toHaveProperty('speeds')
      expect(chartData).toHaveProperty('gusts')
      expect(chartData).toHaveProperty('directions')

      expect(chartData.timeData).toHaveLength(3)
      expect(chartData.timeData[0]).toBeInstanceOf(Date)
      expect(chartData.speeds).toEqual([15, 16, 14])
      expect(chartData.gusts).toEqual([18, 19, 17])
      expect(chartData.directions).toEqual([270, 275, null])
    })
  })

  describe('Current Conditions', () => {
    it('should update current conditions', () => {
      const conditions = {
        speed_kts: 15,
        direction: 270,
        gust_kts: 18,
        timestamp: 1640995200
      }

      store.setCurrentConditions(conditions, 'websocket')
      const state = store.getState()

      expect(state.currentConditions).toEqual(conditions)
    })
  })

  describe('Chart State Management', () => {
    it('should set chart instance', () => {
      const mockChart = { destroy: vi.fn(), update: vi.fn() }
      
      store.setChartInstance(mockChart)
      const state = store.getState()

      expect(state.chartInstance).toBe(mockChart)
      expect(state.isChartInitialized).toBe(true)
    })

    it('should manage zoom state', () => {
      const zoomRange = { min: 1640995200, max: 1640998800 }
      const originalRange = { min: 1640991600, max: 1641002400 }

      store.setZoomRange(zoomRange, originalRange)
      let state = store.getState()

      expect(state.zoomRange).toEqual(zoomRange)
      expect(state.originalTimeRange).toEqual(originalRange)

      store.resetZoom()
      state = store.getState()

      expect(state.zoomRange).toBeNull()
      expect(state.originalTimeRange).toBeNull()
    })
  })

  describe('Computed Properties Caching', () => {
    it('should cache filtered wind data', () => {
      const testData = [
        [1640995200, 270, 15, 18],
        [1640995260, 275, 16, 19]
      ]

      store.setWindData(testData, 'test')
      
      const result1 = store.getFilteredWindData()
      const result2 = store.getFilteredWindData()

      // Should return same reference when cached
      expect(result1).toBe(result2)
    })

    it('should clear cache when relevant state changes', () => {
      const testData = [
        [1640995200, 270, 15, 18],
        [1640995260, 275, 16, 19]
      ]

      store.setWindData(testData, 'test')
      const result1 = store.getFilteredWindData()

      // Add more data - should clear cache
      store.addWindData([1640995320, 280, 14, 17], 'websocket')
      const result2 = store.getFilteredWindData()

      expect(result1).not.toBe(result2)
      expect(result2).toHaveLength(3)
    })
  })

  describe('Batch Operations', () => {
    it('should add multiple wind data points', () => {
      const initialData = [[1640995200, 270, 15, 18]]
      const batchData = [
        [1640995260, 275, 16, 19],
        [1640995320, 280, 14, 17],
        [1640995380, 285, 17, 20]
      ]

      store.setWindData(initialData, 'initial')
      store.addWindDataBatch(batchData, 'gap-fill')
      
      const state = store.getState()
      expect(state.windData).toHaveLength(4)
    })

    it('should filter duplicates in batch operations', () => {
      const initialData = [
        [1640995200, 270, 15, 18],
        [1640995260, 275, 16, 19]
      ]
      const batchData = [
        [1640995260, 275, 16, 19], // Duplicate
        [1640995320, 280, 14, 17], // New
        [1640995200, 270, 15, 18]  // Duplicate
      ]

      store.setWindData(initialData, 'initial')
      store.addWindDataBatch(batchData, 'gap-fill')
      
      const state = store.getState()
      expect(state.windData).toHaveLength(3) // Should only add 1 new point
    })
  })
})