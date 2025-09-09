// Import CSS modules
import './styles/index.css';

// Use static asset path for reliable serving
const windburglrLogo = '/static/windburglr.svg';

import { store } from './store/store.js';
import { ChartManager } from './chart/config.js';
import { WebSocketManager } from './websocket/connection.js';
import { loadHistoricalData } from './utils/data.js';
import { getYesterdayDate, navigateToDate } from './utils/time.js';
import { ConditionsManager } from './ui/conditions.js';
import {
    checkOrientationPopup,
    setupOrientationHandlers,
    dismissOrientationPopup
} from './ui/mobile.js';
import { MemorialPopupManager } from './ui/ghostrider.js';

// Set up global functions immediately when module loads
// This ensures they're available for template inline handlers
function setupGlobalFunctions() {
    // Make navigateToDate globally available for template inline handlers
    window.navigateToDate = (date) => {
        const state = store.getState();
        const station = state.config.station || window.STATION || 'UNKNOWN';
        console.log(`Navigating to date: ${date} for station: ${station}`);
        navigateToDate(date, station);
    };

    // Make dismissOrientationPopup globally available
    window.dismissOrientationPopup = dismissOrientationPopup;

    // Make logo URL globally available for templates
    // Use static path for reliable serving in both dev and production
    window.WINDBURGLR_LOGO_URL = windburglrLogo;

    // Set loading logo src when available
    const loadingLogoImg = document.getElementById('loading-logo-img');
    if (loadingLogoImg) {
        loadingLogoImg.src = windburglrLogo;
    }

    console.log('✓ Global navigation functions set up');
}

// Set up global functions immediately
setupGlobalFunctions();

    // Debug: Verify global functions are available
    setTimeout(() => {
        console.log('[DEBUG] Global functions check:');
        console.log('- navigateToDate type:', typeof window.navigateToDate);
        console.log('- dismissOrientationPopup type:', typeof window.dismissOrientationPopup);
        console.log('- showMemorialPopup type:', typeof window.showMemorialPopup);
        console.log('- dismissMemorialPopup type:', typeof window.dismissMemorialPopup);
        console.log('- WINDBURGLR_LOGO_URL:', typeof window.WINDBURGLR_LOGO_URL);
        if (typeof window.navigateToDate === 'function' &&
            typeof window.dismissOrientationPopup === 'function' &&
            typeof window.showMemorialPopup === 'function' &&
            typeof window.dismissMemorialPopup === 'function' &&
            typeof window.WINDBURGLR_LOGO_URL === 'string') {
            console.log('✅ All global functions and assets are properly set up');
        } else {
            console.error('❌ Global functions/assets setup failed');
        }
    }, 100);

class WindBurglrApp {
    constructor() {
        this.chartManager = null;
        this.wsManager = null;
        this.conditionsManager = null;
        this.memorialPopupManager = null;
        this.unsubscribeStore = null;
    }

    async init() {
        try {
            // Initialize store with configuration from template globals
            const config = {
                station: window.STATION || '',
                isLive: window.IS_LIVE || false,
                dateStart: window.DATE_START || null,
                dateEnd: window.DATE_END || null,
                stationTimezone: window.STATION_TIMEZONE || null,
                hours: window.HOURS || 3
            };

            store.initialize(config);

            // Subscribe to store changes
            this.unsubscribeStore = store.subscribe((state, prevState, source) => {
                this.handleStoreChange(state, prevState, source);
            });

            // Initialize chart manager
            this.chartManager = new ChartManager();
            this.chartManager.init();

            // Initialize conditions manager
            this.conditionsManager = new ConditionsManager();

            // Initialize memorial popup manager
            this.memorialPopupManager = new MemorialPopupManager();
            this.memorialPopupManager.init();

            // Setup mobile orientation handling
            checkOrientationPopup();
            setupOrientationHandlers();

            // Load initial data
            await this.loadInitialData();

            // Setup WebSocket for live data
            if (config.isLive) {
                this.setupWebSocket();
            }

            // Setup event listeners
            this.setupEventListeners();

            // Format date display for historical view
            if (!config.isLive) {
                this.formatHistoricalDate();
            }

        } catch (error) {
            console.error('Error initializing app:', error);
            if (window.Sentry) {
                window.Sentry.captureException(error);
            }
        }
    }

    /**
     * Handle store state changes
     */
    handleStoreChange(state, prevState, source) {
        // Debug logging for important state changes
        if (state.currentTimeWindowHours !== prevState.currentTimeWindowHours) {
            console.log(`[App] Time window changed to ${state.currentTimeWindowHours} hours`);
        }

        if (state.windData.length !== prevState.windData.length) {
            console.log(`[App] Wind data updated: ${state.windData.length} points`);
        }

        if (state.connectionStatus !== prevState.connectionStatus) {
            console.log(`[App] Connection status changed to: ${state.connectionStatus}`);
        }
    }

    async loadInitialData() {
        try {
            store.setLoading(true, 'data-load');

            const state = store.getState();
            const hoursToUse = state.config.isLive ? state.currentTimeWindowHours : state.config.hours;

            const windData = await loadHistoricalData(
                state.config.station,
                hoursToUse,
                state.config.isLive,
                state.config.dateStart,
                state.config.dateEnd
            );

            store.setWindData(windData, 'initial-load');
            store.setLoading(false, 'data-load');

        } catch (error) {
            console.error('Error loading initial data:', error);
            store.setLoading(false, 'data-load');
        }
    }

    setupWebSocket() {
        this.wsManager = new WebSocketManager();
        this.wsManager.connect();
    }

    setupEventListeners() {
        const state = store.getState();

        // Time range selector for live view
        if (state.config.isLive) {
            const timeRangeSelect = document.getElementById('time-range');
            if (timeRangeSelect) {
                timeRangeSelect.addEventListener('change', async (e) => {
                    const hours = parseInt(e.target.value);
                    store.setTimeWindow(hours, 'user-selection');
                    // Reload data with new time window
                    await this.loadInitialData();
                });
            }

            const viewYesterdayBtn = document.getElementById('view-yesterday');
            if (viewYesterdayBtn) {
                viewYesterdayBtn.addEventListener('click', () => {
                    const yesterdayDate = getYesterdayDate();
                    navigateToDate(yesterdayDate, state.config.station);
                });
            }
        }


    }

    formatHistoricalDate() {
        const state = store.getState();
        const dateElement = document.getElementById('formatted-date');

        if (dateElement && state.config.dateStart) {
            const date = new Date(state.config.dateStart.split('T')[0] + 'T00:00:00');
            const options = {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            };
            dateElement.textContent = date.toLocaleDateString('en-US', options);
        }
    }

    /**
     * Cleanup method
     */
    destroy() {
        if (this.unsubscribeStore) {
            this.unsubscribeStore();
        }
        if (this.chartManager) {
            this.chartManager.destroy();
        }
        if (this.conditionsManager) {
            this.conditionsManager.destroy();
        }
        if (this.memorialPopupManager) {
            this.memorialPopupManager.destroy();
        }
        if (this.wsManager) {
            this.wsManager.disconnect();
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Prevent multiple app instances
    if (window.windBurglrApp) {
        console.warn('⚠️ WindBurglrApp already initialized, skipping duplicate initialization');
        return;
    }

    window.windBurglrApp = new WindBurglrApp();
    window.windBurglrApp.init();
});
