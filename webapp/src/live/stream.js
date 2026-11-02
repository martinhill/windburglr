import { store } from '../store/store.js';

// The server sends a heartbeat on an idle stream every 15 s (LIVE_HEARTBEAT_INTERVAL
// in app/config.py). A stream silent for longer than this is dead even if the browser
// hasn't noticed, as happens after the device sleeps.
export const STALE_AFTER_MS = 45_000;
const RETRY_MIN_MS = 1_000;
const RETRY_MAX_MS = 60_000;

/**
 * Live updates for the current station over Server-Sent Events.
 *
 * The browser reconnects a dropped stream on its own, sending the id of the last
 * event it got, and the server replays whatever was missed. This class only steps in
 * when the browser can't: the stream went silent without an error (device asleep,
 * network changed) or the browser gave up (an error response). Then it opens a new
 * stream from the newest observation in the store, which the server also replays from.
 */
export class LiveStream {
    constructor() {
        this.source = null;
        this.lastEventAt = 0;
        this.retryDelay = RETRY_MIN_MS;
        this.retryTimer = null;
        this.watchdogTimer = null;
        this.checkAlive = this.checkAlive.bind(this);
        this.onResume = this.onResume.bind(this);
    }

    start() {
        document.addEventListener('visibilitychange', this.onResume);
        window.addEventListener('online', this.onResume);
        window.addEventListener('pageshow', this.onResume);
        this.watchdogTimer = setInterval(this.checkAlive, STALE_AFTER_MS / 3);
        this.open();
    }

    stop() {
        document.removeEventListener('visibilitychange', this.onResume);
        window.removeEventListener('online', this.onResume);
        window.removeEventListener('pageshow', this.onResume);
        clearInterval(this.watchdogTimer);
        clearTimeout(this.retryTimer);
        this.watchdogTimer = this.retryTimer = null;
        this.closeSource();
    }

    isStale() {
        return Date.now() - this.lastEventAt > STALE_AFTER_MS;
    }

    /** Periodically: reconnect if the stream has been silent too long. */
    checkAlive() {
        if (document.visibilityState === 'hidden' || this.retryTimer || !this.isStale()) {
            return;
        }
        console.log('Live stream went silent, reconnecting');
        this.open();
    }

    /** The page is visible again or back online: don't wait to find out. */
    onResume() {
        if (document.visibilityState === 'hidden') {
            return;
        }
        if (this.retryTimer || this.isStale()) {
            console.log('Page resumed, reconnecting live stream');
            this.open();
        }
    }

    open() {
        this.closeSource();
        clearTimeout(this.retryTimer);
        this.retryTimer = null;

        const { config, lastObservationTime, currentTimeWindowHours } = store.getState();
        // Resume from the newest observation we have; with none (the initial load
        // failed), have the stream fill the window
        const since = lastObservationTime ?? Date.now() / 1000 - currentTimeWindowHours * 3600;
        const url = `/api/live/${encodeURIComponent(config.station)}?since=${since}`;

        this.setStatus('connecting', 'Connecting...');
        const source = new EventSource(url);
        this.source = source;
        this.lastEventAt = Date.now();

        source.onopen = () => {
            this.lastEventAt = Date.now();
            this.retryDelay = RETRY_MIN_MS;
            this.setStatus('connected', 'Connected');
        };

        source.onerror = () => {
            if (source !== this.source) {
                return;
            }
            if (source.readyState === EventSource.CLOSED) {
                // The browser gave up, e.g. on an error response: retry with backoff
                this.closeSource();
                this.setStatus('disconnected', 'Disconnected');
                this.scheduleRetry();
            } else {
                // The browser is reconnecting, and will resume from the last event
                this.setStatus('connecting', 'Reconnecting...');
            }
        };

        this.on(source, 'heartbeat', () => {});
        this.on(source, 'status', (status) => {
            window.scraperStatusManager?.updateStatus(status);
        });
        this.on(source, 'backfill', (points) => {
            if (points.length === 0) {
                return;
            }
            console.log(`Live stream replayed ${points.length} missed observations`);
            store.addWindDataBatch(points, 'backfill');
            const [timestamp, direction, speed_kts, gust_kts] = points[points.length - 1];
            store.setCurrentConditions({ speed_kts, direction, gust_kts, timestamp }, 'backfill');
            this.setStatus('connected', 'Connected (Live)');
        });
        this.on(source, 'wind', (point) => {
            store.setCurrentConditions({
                speed_kts: point.speed_kts,
                direction: point.direction,
                gust_kts: point.gust_kts,
                timestamp: point.timestamp
            }, 'live');
            store.addWindData([point.timestamp, point.direction, point.speed_kts, point.gust_kts], 'live');
            this.setStatus('connected', 'Connected (Live)');
        });
    }

    on(source, eventName, handler) {
        source.addEventListener(eventName, (event) => {
            if (source !== this.source) {
                return;
            }
            this.lastEventAt = Date.now();
            try {
                handler(JSON.parse(event.data));
            } catch (error) {
                console.error(`Error handling live ${eventName} event:`, error, event.data);
                window.Sentry?.captureException(error);
            }
        });
    }

    scheduleRetry() {
        // Jitter, so clients don't all come back at once after a deploy
        const delay = this.retryDelay * (0.5 + Math.random() / 2);
        this.retryDelay = Math.min(this.retryDelay * 2, RETRY_MAX_MS);
        this.retryTimer = setTimeout(() => this.open(), delay);
    }

    closeSource() {
        if (this.source) {
            this.source.close();
            this.source = null;
        }
    }

    setStatus(status, text) {
        const indicator = document.getElementById('connection-status');
        if (indicator) {
            indicator.title = text;
            indicator.className = `connection-indicator ${status}`;
        }
        if (store.getState().connectionText !== text) {
            store.setConnectionStatus(status, text, 'live');
        }
    }
}
