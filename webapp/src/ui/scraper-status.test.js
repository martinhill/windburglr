import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ScraperStatusManager } from './scraper-status.js';

describe('ScraperStatusManager', () => {
    let manager;
    let mockElement;

    beforeEach(() => {
        // Mock DOM elements
        mockElement = {
            textContent: '',
            className: '',
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
            querySelector: vi.fn(),
            contains: vi.fn(),
            classList: {
                add: vi.fn(),
                remove: vi.fn(),
                contains: vi.fn(),
                replace: vi.fn()
            }
        };

        // Mock document methods
        global.document = {
            getElementById: vi.fn((id) => {
                if (id === 'scraper-status') return mockElement;
                if (id === 'status-banner') return mockElement;
                if (id === 'status-banner-close') return mockElement;
                return null;
            }),
            addEventListener: vi.fn(),
            removeEventListener: vi.fn()
        };

        manager = new ScraperStatusManager();
    });

    afterEach(() => {
        vi.clearAllMocks();
    });

    describe('Initialization', () => {
        it('should initialize with null elements when not found', () => {
            global.document.getElementById.mockReturnValue(null);
            const newManager = new ScraperStatusManager();

            expect(newManager.statusElement).toBeNull();
            expect(newManager.bannerElement).toBeNull();
        });

        it('should setup elements when found', () => {
            expect(manager.statusElement).toBe(mockElement);
            expect(manager.bannerElement).toBe(mockElement);
        });

        it('should setup event listeners', () => {
            expect(mockElement.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
        });
    });

    describe('Status Updates', () => {
        it('should update status display for healthy status', () => {
            const statusData = {
                status: 'healthy',
                station_name: 'Test Station'
            };

            manager.updateStatus(statusData);

            expect(mockElement.classList.add).toHaveBeenCalledWith('healthy');
        });

        it('should update status display for error status', () => {
            const statusData = {
                status: 'http_error',
                station_name: 'Test Station'
            };

            manager.updateStatus(statusData);

            expect(mockElement.classList.add).toHaveBeenCalledWith('error');
        });

        it('should update status display for warning status', () => {
            const statusData = {
                status: 'stale_data',
                station_name: 'Test Station'
            };

            manager.updateStatus(statusData);

            expect(mockElement.classList.add).toHaveBeenCalledWith('warning');
        });

        it('should update status display for stopped status', () => {
            const statusData = {
                status: 'stopped',
                station_name: 'Test Station'
            };

            manager.updateStatus(statusData);

            expect(mockElement.classList.add).toHaveBeenCalledWith('stopped');
        });
    });

    describe('Human Readable Status', () => {
        it('should convert status codes to human readable text', () => {
            const testCases = [
                { input: 'healthy', expected: 'OK' },
                { input: 'stale_data', expected: 'Stale Data' },
                { input: 'http_error', expected: 'HTTP Error' },
                { input: 'parse_error', expected: 'Parse Error' },
                { input: 'network_error', expected: 'Network Error' },
                { input: 'error', expected: 'Error' },
                { input: 'unknown', expected: 'Unknown' },
                { input: 'stopped', expected: 'Stopped' },
                { input: 'custom_status', expected: 'custom_status' }
            ];

            testCases.forEach(({ input, expected }) => {
                expect(manager.getHumanReadableStatus(input)).toBe(expected);
            });
        });
    });

    describe('Duration Formatting', () => {
        it('should format duration in seconds correctly', () => {
            const testCases = [
                { input: 0, expected: '0s' },
                { input: 45, expected: '45s' },
                { input: 125, expected: '2m 5s' },
                { input: 3665, expected: '1h 1m' },
                { input: 90061, expected: '1d 1h' },
                { input: 86400 * 2 + 3600 + 60 + 1, expected: '2d 1h' },
                { input: 1800, expected: '30m' }, // 30 minutes exactly
                { input: 7265, expected: '2h 1m' } // 2 hours and 1 minute
            ];

            testCases.forEach(({ input, expected }) => {
                expect(manager.formatDurationSeconds(input)).toBe(expected);
            });
        });

        it('should handle negative durations', () => {
            expect(manager.formatDurationSeconds(-100)).toBe('Unknown');
        });
    });

    describe('Elapsed Time Formatting', () => {
        beforeEach(() => {
            // Mock Date.now to return a consistent time
            vi.useFakeTimers();
            const mockNow = new Date('2024-01-01T12:00:00Z').getTime();
            vi.setSystemTime(mockNow);
        });

        afterEach(() => {
            vi.useRealTimers();
        });

        it('should format elapsed time from timestamp', () => {
            const pastTime = '2024-01-01T11:30:00Z'; // 30 minutes ago
            const result = manager.formatElapsedTime(pastTime);
            expect(result).toBe('30m');
        });

        it('should handle invalid timestamps', () => {
            const result = manager.formatElapsedTime('invalid-date');
            expect(result).toBe('Invalid date');
        });

        it('should handle future timestamps', () => {
            const futureTime = '2024-01-01T13:00:00Z'; // 1 hour in future
            const result = manager.formatElapsedTime(futureTime);
            expect(result).toBe('just now');
        });

        it('should handle null/undefined timestamps', () => {
            expect(manager.formatElapsedTime(null)).toBe('Unknown');
            expect(manager.formatElapsedTime(undefined)).toBe('Unknown');
        });
    });

    describe('Banner Management', () => {
        it('should toggle banner visibility', () => {
            mockElement.classList.contains.mockReturnValue(false);
            manager.toggleBanner();
            expect(mockElement.classList.add).toHaveBeenCalledWith('visible');

            mockElement.classList.contains.mockReturnValue(true);
            manager.toggleBanner();
            expect(mockElement.classList.remove).toHaveBeenCalledWith('visible');
        });

        it('should show banner', () => {
            manager.showBanner();
            expect(mockElement.classList.add).toHaveBeenCalledWith('visible');
        });

        it('should hide banner', () => {
            manager.hideBanner();
            expect(mockElement.classList.remove).toHaveBeenCalledWith('visible');
        });
    });

    describe('Banner Content Update', () => {
        beforeEach(() => {
            const mockBannerContent = {
                innerHTML: ''
            };
            mockElement.querySelector.mockReturnValue(mockBannerContent);
        });

        it('should update banner content with status data', () => {
            const statusData = {
                station_name: 'Test Station',
                status: 'http_error',
                last_success: '2024-01-01T10:00:00Z',
                last_attempt: '2024-01-01T11:30:00Z',
                retry_count: 3,
                error_message: 'Connection timeout'
            };

            // Mock current time
            vi.useFakeTimers();
            const mockNow = new Date('2024-01-01T12:00:00Z').getTime();
            vi.setSystemTime(mockNow);

            manager.updateStatus(statusData);
            manager.updateBannerContent();

            const bannerContent = mockElement.querySelector('.status-banner-details');
            expect(bannerContent.innerHTML).toContain('Test Station');
            expect(bannerContent.innerHTML).toContain('HTTP Error');
            expect(bannerContent.innerHTML).toContain('Connection timeout');

            vi.useRealTimers();
        });

        it('should handle missing status data gracefully', () => {
            manager.updateBannerContent();
            // Should not throw error
            expect(true).toBe(true);
        });
    });

    describe('Cleanup', () => {
        it('should destroy manager and clear references', () => {
            manager.destroy();

            expect(manager.currentStatus).toBeNull();
            expect(manager.statusElement).toBeNull();
            expect(manager.bannerElement).toBeNull();
        });
    });
});
