import { LiveStream, STALE_AFTER_MS } from './stream.js';
import { store } from '../store/store.js';

const HOUR = 3600;
const T0 = Date.UTC(2026, 10, 2, 12, 0, 0) / 1000; // page loaded, 3 h window

// One observation per minute, as /api/wind and backfill events carry them
function obs(from, to) {
    const out = [];
    for (let t = Math.ceil(from / 60) * 60; t <= to; t += 60) out.push([t, 270, 12, 18]);
    return out;
}

function windPoint(t) {
    return { timestamp: t, direction: 250, speed_kts: 14, gust_kts: 20 };
}

class FakeEventSource {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;
    static instances = [];

    constructor(url) {
        this.url = url;
        this.readyState = FakeEventSource.CONNECTING;
        this.listeners = {};
        FakeEventSource.instances.push(this);
    }

    addEventListener(name, fn) {
        (this.listeners[name] ??= []).push(fn);
    }

    close() {
        this.readyState = FakeEventSource.CLOSED;
    }

    // Test helpers, standing in for the server and the browser
    open() {
        this.readyState = FakeEventSource.OPEN;
        this.onopen?.({});
    }

    emit(name, data) {
        for (const fn of this.listeners[name] ?? []) fn({ data: JSON.stringify(data) });
    }

    fail({ gaveUp = false } = {}) {
        this.readyState = gaveUp ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING;
        this.onerror?.({});
    }

    get since() {
        return Number(new URL(this.url, 'http://x').searchParams.get('since'));
    }
}

const latestSource = () => FakeEventSource.instances.at(-1);

function windowSpan() {
    const data = store.getState().windData;
    return {
        points: data.length,
        hours: data.length ? (data.at(-1)[0] - data[0][0]) / HOUR : 0,
    };
}

function setVisibility(state) {
    Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
}

describe('LiveStream', () => {
    let stream;

    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(T0 * 1000);
        window.matchMedia = () => ({ matches: false, addEventListener() {} });
        global.EventSource = FakeEventSource;
        FakeEventSource.instances = [];
        setVisibility('visible');
        store.state.windData = [];
        store.state.lastObservationTime = null;
        store.state.connectionText = '';
        store.initialize({ station: 'CYTZ', isLive: true, hours: 3 });
    });

    afterEach(() => {
        stream?.stop();
        stream = null;
        vi.useRealTimers();
        delete window.scraperStatusManager;
    });

    function startWithInitialLoad() {
        store.setWindData(obs(T0 - 3 * HOUR, T0), 'initial-load');
        stream = new LiveStream();
        stream.start();
        latestSource().open();
        return latestSource();
    }

    it('opens a stream for the station from the newest observation it has', () => {
        const source = startWithInitialLoad();
        expect(source.url).toBe(`/api/live/CYTZ?since=${T0 - (T0 % 60)}`);
        expect(store.getState().connectionStatus).toBe('connected');
    });

    it('fills the window from the stream when the initial load failed', () => {
        stream = new LiveStream();
        stream.start();
        expect(latestSource().since).toBe(T0 - 3 * HOUR);
    });

    it('adds live observations and updates current conditions', () => {
        const source = startWithInitialLoad();
        source.emit('wind', windPoint(T0 + 60));

        expect(store.getState().windData.at(-1)).toEqual([T0 + 60, 250, 14, 20]);
        expect(store.getState().currentConditions).toEqual(windPoint(T0 + 60));
        expect(store.getState().connectionText).toBe('Connected (Live)');
    });

    it('passes scraper status to the status banner', () => {
        window.scraperStatusManager = { updateStatus: vi.fn() };
        const source = startWithInitialLoad();
        source.emit('status', { station_name: 'CYTZ', status: 'error' });
        expect(window.scraperStatusManager.updateStatus).toHaveBeenCalledWith({
            station_name: 'CYTZ',
            status: 'error',
        });
    });

    describe('resuming after the device slept longer than the window (3 h window, 5 h asleep)', () => {
        const WAKE = T0 + 5 * HOUR;

        it('browser reconnects on its own: the replay restores the whole window', () => {
            const source = startWithInitialLoad();
            vi.setSystemTime(WAKE * 1000);
            source.fail(); // dropped; the browser reconnects with Last-Event-ID
            source.open();
            source.emit('backfill', obs(WAKE - 24 * HOUR, WAKE).filter(([t]) => t > T0));
            source.emit('wind', windPoint(WAKE + 60));

            expect(windowSpan().hours).toBeGreaterThan(2.9);
            expect(store.getState().currentConditions.timestamp).toBe(WAKE + 60);
        });

        it('stream went silent without an error: reconnects from the last observation', () => {
            const before = startWithInitialLoad();
            vi.setSystemTime(WAKE * 1000);
            vi.advanceTimersByTime(STALE_AFTER_MS / 3); // the watchdog's next check

            const after = latestSource();
            expect(after).not.toBe(before);
            expect(before.readyState).toBe(FakeEventSource.CLOSED);
            expect(after.since).toBe(T0 - (T0 % 60));

            after.open();
            after.emit('backfill', obs(after.since + 1, WAKE));
            expect(windowSpan().hours).toBeGreaterThan(2.9);
            expect(store.getState().currentConditions.timestamp).toBe(WAKE - (WAKE % 60));
        });

        it('becoming visible reconnects at once', () => {
            const before = startWithInitialLoad();
            vi.setSystemTime(WAKE * 1000);
            document.dispatchEvent(new Event('visibilitychange'));
            expect(latestSource()).not.toBe(before);
        });
    });

    it('ignores events from a stream it has replaced', () => {
        const before = startWithInitialLoad();
        vi.setSystemTime((T0 + STALE_AFTER_MS / 1000 + 1) * 1000);
        window.dispatchEvent(new Event('online'));
        expect(latestSource()).not.toBe(before);

        before.emit('wind', windPoint(T0 + 120));
        expect(store.getState().windData.at(-1)[0]).toBe(T0 - (T0 % 60));
    });

    it('does not reconnect a stream that is alive', () => {
        const source = startWithInitialLoad();
        for (let i = 0; i < 10; i++) {
            vi.advanceTimersByTime(15_000);
            source.emit('heartbeat', {});
        }
        window.dispatchEvent(new Event('online'));
        expect(FakeEventSource.instances).toHaveLength(1);
    });

    it('leaves a hidden page alone until it is visible again', () => {
        const before = startWithInitialLoad();
        setVisibility('hidden');
        vi.advanceTimersByTime(5 * STALE_AFTER_MS);
        expect(latestSource()).toBe(before);

        setVisibility('visible');
        document.dispatchEvent(new Event('visibilitychange'));
        expect(latestSource()).not.toBe(before);
    });

    it('retries with growing delays when the browser gives up', () => {
        const random = vi.spyOn(Math, 'random').mockReturnValue(1); // no jitter
        startWithInitialLoad().fail({ gaveUp: true });
        expect(store.getState().connectionStatus).toBe('disconnected');

        const delays = [];
        for (let i = 0; i < 8; i++) {
            const count = FakeEventSource.instances.length;
            let waited = 0;
            while (FakeEventSource.instances.length === count) {
                vi.advanceTimersByTime(500);
                waited += 500;
            }
            delays.push(waited);
            latestSource().fail({ gaveUp: true });
        }
        expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 32000, 60000, 60000]);
        random.mockRestore();
    });

    it('a retry resumes from observations received meanwhile', () => {
        const source = startWithInitialLoad();
        source.emit('wind', windPoint(T0 + 60));
        source.fail({ gaveUp: true });
        vi.advanceTimersByTime(1000);
        expect(latestSource().since).toBe(T0 + 60);
    });

    it('coming back online skips the rest of a retry delay', () => {
        startWithInitialLoad().fail({ gaveUp: true });
        const count = FakeEventSource.instances.length;
        window.dispatchEvent(new Event('online'));
        expect(FakeEventSource.instances.length).toBe(count + 1);
    });

    it('stop closes the stream and stops reconnecting', () => {
        const source = startWithInitialLoad();
        stream.stop();
        expect(source.readyState).toBe(FakeEventSource.CLOSED);

        vi.setSystemTime((T0 + 5 * HOUR) * 1000);
        vi.advanceTimersByTime(5 * STALE_AFTER_MS);
        window.dispatchEvent(new Event('online'));
        expect(FakeEventSource.instances).toHaveLength(1);
    });
});
