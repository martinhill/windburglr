import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { filterOldObservations, loadHistoricalData, fillDataGap } from './data.js'

describe('Data Utilities', () => {
  
  describe('filterOldObservations', () => {
    const mockData = [
      [1640995200, 270, 15, 18], // timestamp, direction, speed, gust
      [1640995260, 275, 16, 19], // 1 minute later
      [1640995320, 280, 14, 17], // 2 minutes after first
      [1640995380, 285, 17, 20]  // 3 minutes after first
    ]

    beforeEach(() => {
      // Mock current time to be predictable
      vi.spyOn(Date, 'now').mockReturnValue(1641000000 * 1000) // 80 minutes after first data point
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should return all data when not in live mode', () => {
      const result = filterOldObservations(mockData, false, 1)
      expect(result).toEqual(mockData)
    })

    it('should return all data when time window is 0 or negative', () => {
      const result1 = filterOldObservations(mockData, true, 0)
      const result2 = filterOldObservations(mockData, true, -1)
      
      expect(result1).toEqual(mockData)
      expect(result2).toEqual(mockData)
    })

    it('should filter out old observations in live mode', () => {
      // With 1 hour window, should keep data from last hour
      const result = filterOldObservations(mockData, true, 1)
      
      // All data points are older than 1 hour, so should return empty array
      expect(result).toEqual([])
    })

    it('should keep recent observations within time window', () => {
      // Mock current time to be just 30 minutes after last data point
      vi.spyOn(Date, 'now').mockReturnValue(1640997180 * 1000) // 30 minutes after last point
      
      const result = filterOldObservations(mockData, true, 1) // 1 hour window
      
      // All data should be within the hour window
      expect(result).toEqual(mockData)
    })

    it('should filter partially - keep only recent data', () => {
      // Mock current time to be 2.5 minutes after first data point
      vi.spyOn(Date, 'now').mockReturnValue(1640995350 * 1000)
      
      const result = filterOldObservations(mockData, true, 1/30) // 2 minute window
      
      // Should keep last 3 points (within 2 minutes from 1640995350)
      // 1640995200 is 150s ago (too old)
      // 1640995260 is 90s ago (within window)
      // 1640995320 is 30s ago (within window) 
      // 1640995380 is 30s in future (within window)
      expect(result).toEqual([
        [1640995260, 275, 16, 19],
        [1640995320, 280, 14, 17],
        [1640995380, 285, 17, 20]
      ])
    })
  })

  describe('loadHistoricalData', () => {
    const mockResponse = {
      winddata: [
        [1640995200, 270, 15, 18],
        [1640995260, 275, 16, 19]
      ]
    }

    beforeEach(() => {
      global.fetch = vi.fn()
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should load live historical data with correct URL', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.resolve(mockResponse)
      })

      const result = await loadHistoricalData('CYYZ', 6, true)

      expect(global.fetch).toHaveBeenCalledWith('/api/wind?stn=CYYZ&hours=6')
      expect(result).toEqual(mockResponse.winddata)
    })

    it('should load historical data with date range', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.resolve(mockResponse)
      })

      const result = await loadHistoricalData(
        'CYYZ', 
        null, 
        false, 
        '2022-01-01T00:00:00',
        '2022-01-01T23:59:59'
      )

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/wind?stn=CYYZ&from_time=2022-01-01T00:00:00&to_time=2022-01-01T23:59:59'
      )
      expect(result).toEqual(mockResponse.winddata)
    })

    it('should handle fetch errors gracefully', async () => {
      const error = new Error('Network error')
      global.fetch.mockRejectedValueOnce(error)

      // Mock Sentry
      global.Sentry = { captureException: vi.fn() }

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toThrow('Network error')
      expect(global.Sentry.captureException).toHaveBeenCalledWith(error)
    })

    it('should handle JSON parsing errors', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.reject(new Error('Invalid JSON'))
      })

      global.Sentry = { captureException: vi.fn() }

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toThrow('Invalid JSON')
    })
  })

  describe('fillDataGap', () => {
    const mockResponse = {
      winddata: [
        [1640995500, 270, 15, 18],
        [1640995560, 275, 16, 19]
      ]
    }

    beforeEach(() => {
      global.fetch = vi.fn()
      vi.spyOn(Date.prototype, 'toISOString').mockImplementation(function() {
        return '2022-01-01T12:00:00.000Z'
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should return empty array when not in live mode', async () => {
      const result = await fillDataGap('CYYZ', 1640995200, 6, false)
      expect(result).toEqual([])
      expect(global.fetch).not.toHaveBeenCalled()
    })

    it('should load data when no last observation time', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.resolve(mockResponse)
      })

      const result = await fillDataGap('CYYZ', null, 6, true)

      expect(global.fetch).toHaveBeenCalledWith('/api/wind?stn=CYYZ&hours=6')
      expect(result).toEqual(mockResponse.winddata)
    })

    it('should fetch data gap successfully', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.resolve(mockResponse)
      })

      const result = await fillDataGap('CYYZ', 1640995200, 6, true)

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/wind?stn=CYYZ&from_time=')
      )
      expect(result).toEqual(mockResponse.winddata)
    })

    it('should handle empty response data', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.resolve({ winddata: [] })
      })

      const result = await fillDataGap('CYYZ', 1640995200, 6, true)
      expect(result).toEqual([])
    })

    it('should handle fetch errors gracefully', async () => {
      const error = new Error('Network error')
      global.fetch.mockRejectedValueOnce(error)
      global.Sentry = { captureException: vi.fn() }

      const result = await fillDataGap('CYYZ', 1640995200, 6, true)

      expect(result).toEqual([])
      expect(global.Sentry.captureException).toHaveBeenCalledWith(error)
    })

    it('should construct correct time range URLs', async () => {
      global.fetch.mockResolvedValueOnce({
        json: () => Promise.resolve(mockResponse)
      })

      // Mock specific ISO string behavior
      const mockToISOString = vi.fn()
        .mockReturnValueOnce('2022-01-01T11:00:00.000Z') // from_time
        .mockReturnValueOnce('2022-01-01T12:00:00.000Z') // to_time
      
      const originalDate = Date
      global.Date = class extends originalDate {
        constructor(...args) {
          super(...args)
          this.toISOString = mockToISOString
        }
        
        static now() {
          return originalDate.now()
        }
      }

      await fillDataGap('CYYZ', 1640995200, 6, true)

      expect(global.fetch).toHaveBeenCalledWith(
        '/api/wind?stn=CYYZ&from_time=2022-01-01T11:00:00&to_time=2022-01-01T12:00:00'
      )

      global.Date = originalDate
    })
  })
})