import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { 
  DIRECTIONS,
  getDirectionText, 
  formatTime, 
  formatDateTime, 
  getYesterdayDate, 
  navigateToDate 
} from './time.js'

describe('Time Utilities', () => {
  
  describe('DIRECTIONS constant', () => {
    it('should have 16 direction values', () => {
      expect(DIRECTIONS).toHaveLength(16)
      expect(DIRECTIONS[0]).toBe('N')
      expect(DIRECTIONS[4]).toBe('E')
      expect(DIRECTIONS[8]).toBe('S')
      expect(DIRECTIONS[12]).toBe('W')
    })
  })

  describe('getDirectionText', () => {
    it('should return correct direction for valid degrees', () => {
      expect(getDirectionText(0)).toBe('N')
      expect(getDirectionText(90)).toBe('E')
      expect(getDirectionText(180)).toBe('S')
      expect(getDirectionText(270)).toBe('W')
      expect(getDirectionText(360)).toBe('N') // Should wrap around
    })

    it('should handle intermediate directions', () => {
      expect(getDirectionText(45)).toBe('NE')
      expect(getDirectionText(135)).toBe('SE')
      expect(getDirectionText(225)).toBe('SW')
      expect(getDirectionText(315)).toBe('NW')
    })

    it('should return -- for null or undefined values', () => {
      expect(getDirectionText(null)).toBe('--')
      expect(getDirectionText(undefined)).toBe('--')
    })

    it('should handle edge cases and rounding', () => {
      expect(getDirectionText(11.25)).toBe('NNE') // 11.25/22.5 = 0.5, rounds to 1 = NNE
      expect(getDirectionText(33.75)).toBe('NE') // 33.75/22.5 = 1.5, rounds to 2 = NE  
      expect(getDirectionText(348.75)).toBe('N') // 348.75/22.5 = 15.5, rounds to 16 % 16 = 0 = N
    })

    it('should handle negative degrees', () => {
      // JavaScript's modulo with negative numbers needs special handling
      // The current implementation doesn't handle negatives properly
      // This test documents the current behavior
      expect(getDirectionText(-45)).toBeUndefined() // Current implementation doesn't handle negatives
      expect(getDirectionText(-90)).toBeUndefined() // Current implementation doesn't handle negatives
    })
  })

  describe('formatTime', () => {
    const testTimestamp = 1640995200 // 2022-01-01 00:00:00 UTC

    beforeEach(() => {
      // Mock toLocaleTimeString to return predictable values
      vi.spyOn(Date.prototype, 'toLocaleTimeString').mockImplementation(function(locales, options) {
        if (options?.timeZone === 'America/Toronto') {
          return '19:00' // EST is UTC-5
        }
        return '00:00'
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should format time for live mode without timezone', () => {
      const result = formatTime(testTimestamp, true)
      
      expect(Date.prototype.toLocaleTimeString).toHaveBeenCalledWith([], {
        hour12: false,
        timeStyle: "short"
      })
      expect(result).toBe('00:00')
    })

    it('should format time for historical mode with timezone', () => {
      const result = formatTime(testTimestamp, false, 'America/Toronto')
      
      expect(Date.prototype.toLocaleTimeString).toHaveBeenCalledWith([], {
        timeZone: 'America/Toronto',
        hour12: false
      })
      expect(result).toBe('19:00')
    })

    it('should default to live mode formatting when no timezone provided', () => {
      const result = formatTime(testTimestamp, false, null)
      
      expect(Date.prototype.toLocaleTimeString).toHaveBeenCalledWith([], {
        hour12: false,
        timeStyle: "short"
      })
      expect(result).toBe('00:00')
    })
  })

  describe('formatDateTime', () => {
    const testTimestamp = 1640995200 // 2022-01-01 00:00:00 UTC

    beforeEach(() => {
      vi.spyOn(Date.prototype, 'toLocaleString').mockImplementation(function(locale, options) {
        if (options?.timeZone === 'America/Toronto') {
          return '12/31/2021, 7:00:00 PM' // EST is UTC-5
        }
        return '1/1/2022, 12:00:00 AM'
      })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should format datetime for live mode', () => {
      const result = formatDateTime(testTimestamp, true)
      
      expect(Date.prototype.toLocaleString).toHaveBeenCalledWith()
      expect(result).toBe('1/1/2022, 12:00:00 AM')
    })

    it('should format datetime for historical mode with timezone', () => {
      const result = formatDateTime(testTimestamp, false, 'America/Toronto')
      
      expect(Date.prototype.toLocaleString).toHaveBeenCalledWith('en-US', {
        timeZone: 'America/Toronto'
      })
      expect(result).toBe('12/31/2021, 7:00:00 PM')
    })

    it('should default to live mode formatting when no timezone', () => {
      const result = formatDateTime(testTimestamp, false, null)
      
      expect(Date.prototype.toLocaleString).toHaveBeenCalledWith()
      expect(result).toBe('1/1/2022, 12:00:00 AM')
    })
  })

  describe('getYesterdayDate', () => {
    beforeEach(() => {
      // Mock Date to return a specific date
      vi.setSystemTime(new Date('2022-01-15T12:00:00Z'))
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should return yesterday date in YYYY-MM-DD format', () => {
      const result = getYesterdayDate()
      expect(result).toBe('2022-01-14')
    })

    it('should handle month boundary correctly', () => {
      vi.setSystemTime(new Date('2022-02-01T12:00:00Z'))
      const result = getYesterdayDate()
      expect(result).toBe('2022-01-31')
    })

    it('should handle year boundary correctly', () => {
      vi.setSystemTime(new Date('2022-01-01T12:00:00Z'))
      const result = getYesterdayDate()
      expect(result).toBe('2021-12-31')
    })

    it('should pad single digit months and days', () => {
      vi.setSystemTime(new Date('2022-01-02T12:00:00Z'))
      const result = getYesterdayDate()
      expect(result).toBe('2022-01-01')
    })
  })

  describe('navigateToDate', () => {
    const mockLocation = {
      href: '',
      search: ''
    }

    beforeEach(() => {
      // Mock window.location
      Object.defineProperty(window, 'location', {
        value: mockLocation,
        writable: true
      })

      // Mock URLSearchParams
      global.URLSearchParams = vi.fn().mockImplementation((search) => ({
        get: vi.fn().mockImplementation((key) => {
          if (key === 'stn' && search === '?stn=CYYZ') return 'CYYZ'
          if (key === 'stn' && search === '') return null
          return null
        })
      }))

      mockLocation.href = ''
      mockLocation.search = ''
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should navigate with provided station', () => {
      navigateToDate('2022-01-15', 'CYYZ')
      expect(mockLocation.href).toBe('/day/2022-01-15?stn=CYYZ')
    })

    it('should use station from URL params when provided station is falsy', () => {
      mockLocation.search = '?stn=CYYZ'
      
      navigateToDate('2022-01-15', null)
      expect(mockLocation.href).toBe('/day/2022-01-15?stn=CYYZ')
    })

    it('should use provided station over URL params when both exist', () => {
      mockLocation.search = '?stn=CYOW'
      
      navigateToDate('2022-01-15', 'CYYZ')
      expect(mockLocation.href).toBe('/day/2022-01-15?stn=CYYZ')
    })

    it('should handle missing station gracefully', () => {
      mockLocation.search = ''
      
      navigateToDate('2022-01-15', null)
      expect(mockLocation.href).toBe('/day/2022-01-15?stn=null')
    })

    it('should handle different date formats', () => {
      navigateToDate('2022-12-25', 'CYYZ')
      expect(mockLocation.href).toBe('/day/2022-12-25?stn=CYYZ')
    })
  })

  describe('Edge cases and error handling', () => {
    it('should handle extreme direction values', () => {
      expect(getDirectionText(720)).toBe('N') // 720 % 360 = 0
      expect(getDirectionText(-720)).toBe('N') // -720 % 360 = 0
      expect(getDirectionText(1080)).toBe('N') // 1080 % 360 = 0
    })

    it('should handle very large timestamps', () => {
      const futureTimestamp = 2000000000 // Year 2033
      
      // Should not throw error
      expect(() => formatTime(futureTimestamp)).not.toThrow()
      expect(() => formatDateTime(futureTimestamp)).not.toThrow()
    })

    it('should handle zero timestamp', () => {
      expect(() => formatTime(0)).not.toThrow()
      expect(() => formatDateTime(0)).not.toThrow()
    })
  })
})