import { getDirectionText, formatTime } from '../utils/time.js';
import { store } from '../store/store.js';

export class ConditionsManager {
    constructor() {
        this.unsubscribeStore = null;
        this.init();
    }
    
    init() {
        // Subscribe to store changes for current conditions
        this.unsubscribeStore = store.subscribe((state, prevState, source) => {
            if (state.currentConditions !== prevState.currentConditions) {
                this.updateDisplay(state.currentConditions, state.config);
            }
        });
        
        // Initial update
        const state = store.getState();
        this.updateDisplay(state.currentConditions, state.config);
    }
    
    updateDisplay(conditions, config) {
        const speedElement = document.getElementById('current-speed');
        const directionElement = document.getElementById('current-direction');
        const gustElement = document.getElementById('current-gust');
        const updateElement = document.getElementById('last-update');

        if (speedElement) speedElement.textContent = conditions.speed_kts || '--';
        if (directionElement) directionElement.textContent = getDirectionText(conditions.direction);
        if (gustElement) gustElement.textContent = conditions.gust_kts || '--';
        if (updateElement) updateElement.textContent = formatTime(conditions.timestamp, config.isLive, config.stationTimezone);
    }
    
    destroy() {
        if (this.unsubscribeStore) {
            this.unsubscribeStore();
        }
    }
}

// Backward compatibility function
export function updateCurrentConditions(data, isLive = true, stationTimezone = null) {
    store.setCurrentConditions({
        speed_kts: data.speed_kts,
        direction: data.direction,
        gust_kts: data.gust_kts,
        timestamp: data.timestamp
    }, 'legacy');
}