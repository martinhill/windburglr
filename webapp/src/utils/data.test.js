import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { filterOldObservations, loadHistoricalData, HistoricalDataError } from './data.js'

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

    const ok = (body) => ({ ok: true, status: 200, json: () => Promise.resolve(body) })

    beforeEach(() => {
      global.Sentry = { captureException: vi.fn() }
      vi.spyOn(console, 'warn').mockImplementation(() => {})
      vi.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
      delete global.Sentry
    })

    it('should load live historical data with correct URL', async () => {
      global.fetch.mockResolvedValueOnce(ok(mockResponse))

      const result = await loadHistoricalData('CYYZ', 6, true)

      expect(global.fetch).toHaveBeenCalledWith('/api/wind?stn=CYYZ&hours=6')
      expect(result).toEqual(mockResponse.winddata)
      expect(global.Sentry.captureException).not.toHaveBeenCalled()
    })

    it('should load historical data with date range', async () => {
      global.fetch.mockResolvedValueOnce(ok(mockResponse))

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

    it.each(['Load failed', 'Failed to fetch', 'NetworkError when attempting to fetch resource.'])(
      'should report a network failure (%s) as a warning',
      async (message) => {
        const error = new TypeError(message)
        global.fetch.mockRejectedValueOnce(error)

        await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toBe(error)
        expect(global.Sentry.captureException).toHaveBeenCalledWith(
          error,
          expect.objectContaining({ level: 'warning', extra: { url: '/api/wind?stn=CYYZ&hours=6' } })
        )
      }
    )

    it('should not report an aborted request', async () => {
      const error = new DOMException('The operation was aborted.', 'AbortError')
      global.fetch.mockRejectedValueOnce(error)

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toBe(error)
      expect(global.Sentry.captureException).not.toHaveBeenCalled()
    })

    it('should report an unexpected fetch error as an error', async () => {
      const error = new Error('Something else')
      global.fetch.mockRejectedValueOnce(error)

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toBe(error)
      expect(global.Sentry.captureException).toHaveBeenCalledWith(
        error,
        expect.objectContaining({ level: 'error' })
      )
    })

    it('should report an HTTP error status as an error', async () => {
      const json = vi.fn()
      global.fetch.mockResolvedValueOnce({ ok: false, status: 502, json })

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toMatchObject({
        name: 'HistoricalDataError',
        status: 502,
        message: 'Historical data request failed: HTTP 502',
      })
      expect(json).not.toHaveBeenCalled()
      expect(global.Sentry.captureException).toHaveBeenCalledWith(
        expect.any(HistoricalDataError),
        expect.objectContaining({ level: 'error' })
      )
    })

    it('should reject a response without winddata', async () => {
      global.fetch.mockResolvedValueOnce(ok({ detail: 'nope' }))

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toThrow(
        'Historical data response has no winddata array'
      )
      expect(global.Sentry.captureException).toHaveBeenCalledWith(
        expect.any(HistoricalDataError),
        expect.objectContaining({ level: 'error' })
      )
    })

    it('should report JSON parsing errors as errors', async () => {
      const error = new SyntaxError('Invalid JSON')
      global.fetch.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.reject(error) })

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toBe(error)
      expect(global.Sentry.captureException).toHaveBeenCalledWith(
        error,
        expect.objectContaining({ level: 'error' })
      )
    })

    it('should work without Sentry loaded', async () => {
      delete global.Sentry
      global.fetch.mockRejectedValueOnce(new TypeError('Load failed'))

      await expect(loadHistoricalData('CYYZ', 6, true)).rejects.toThrow('Load failed')
    })
  })
})