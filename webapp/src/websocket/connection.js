import { fillDataGap } from '../utils/data.js';
import { store } from '../store/store.js';

export class WebSocketManager {
    constructor() {
        this.websocket = null;
        this.needsBackfill = false;
    }

    updateConnectionStatus(status, text) {
        const statusElement = document.getElementById('connection-status');
        if (statusElement) {
            statusElement.title = text;
            statusElement.className = `connection-indicator ${status}`;
        }
        console.log(`WebSocket status: ${text}`);

        // Update connection status in store
        store.setConnectionStatus(status, text, 'websocket');
    }

    async connect() {
        const state = store.getState();
        const station = state.config.station;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${station}`;

        this.updateConnectionStatus('connecting', 'Connecting...');

        this.websocket = new WebSocket(wsUrl);

        this.websocket.onopen = async (event) => {
            console.log('WebSocket connected successfully');
            this.updateConnectionStatus('connected', 'Connected');

            if (this.needsBackfill) {
                try {
                    const gapData = await fillDataGap(station, state.lastObservationTime, state.currentTimeWindowHours, true);
                    if (gapData.length > 0) {
                        store.addWindDataBatch(gapData, 'gap-fill');
                    }
                } catch (error) {
                    console.error('Error filling gap on connection:', error);
                }
            }
        };

        this.websocket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                let data;

                // Handle new format with type and data keys
                if (message.type) {
                    if (message.type === 'ping') {
                        console.log('Received ping from server');
                        this.updateConnectionStatus('connected', 'Connected');
                        return;
                    }

                    if (message.type === 'status_update') {
                        const statusData = message.data;
                        console.log('Received status update:', statusData);

                        // Update scraper status display
                        if (window.scraperStatusManager) {
                            window.scraperStatusManager.updateStatus(statusData);
                        }
                        return;
                    }

                    if (message.type === 'wind') {
                        data = message.data;
                    } else {
                        console.log('Received unknown message type:', message.type);
                        return;
                    }
                } else {
                    // Handle legacy format (direct properties)
                    data = message;
                }

                this.updateConnectionStatus('connected', 'Connected (Live)');

                if (data.timestamp !== undefined) {
                    // Update current conditions in store
                    store.setCurrentConditions({
                        speed_kts: data.speed_kts,
                        direction: data.direction,
                        gust_kts: data.gust_kts,
                        timestamp: data.timestamp
                    }, 'websocket');

                    // Add new wind data point to store
                    const newPoint = [data.timestamp, data.direction, data.speed_kts, data.gust_kts];
                    store.addWindData(newPoint, 'websocket');
                } else {
                    console.log('Received message without timestamp:', data);
                }
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
                console.log('WebSocket message received:', event.data);
                if (window.Sentry) {
                    window.Sentry.captureException(error);
                }
            }
        };

        this.websocket.onclose = (event) => {
            console.log('WebSocket closed:', event.code, event.reason);
            this.updateConnectionStatus('disconnected', 'Disconnected');
            this.needsBackfill = true;

            setTimeout(() => {
                console.log('Attempting to reconnect...');
                this.connect();
            }, 5000);
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus('error', 'Connection Error');
        };
    }

    disconnect() {
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
    }
}
