export function filterOldObservations(data, isLive, currentTimeWindowHours) {
    if (!isLive || currentTimeWindowHours <= 0) {
        return data;
    }

    const now = Date.now() / 1000;
    const cutoffTime = now - (currentTimeWindowHours * 3600);
    return data.filter(point => point[0] >= cutoffTime);
}

/** The API answered, but not with a usable wind data response. */
export class HistoricalDataError extends Error {
    constructor(message, { url, status } = {}) {
        super(message);
        this.name = 'HistoricalDataError';
        this.url = url;
        this.status = status;
    }
}

/**
 * fetch() rejects with a TypeError when the request never got a response:
 * offline, connection reset, CORS, or an embedding WebView that blocks loads
 * (the macOS link-preview renderer does this). The message differs per engine:
 * "Load failed" (WebKit), "Failed to fetch" (Chromium), "NetworkError when
 * attempting to fetch resource." (Firefox).
 */
function isNetworkFailure(error) {
    return error instanceof TypeError;
}

function report(error, level, url) {
    if (!window.Sentry) {
        return;
    }
    window.Sentry.captureException(error, {
        level,
        tags: { 'fetch.url': url.split('?')[0] },
        extra: { url },
    });
}

export async function loadHistoricalData(station, hours, isLive, dateStart = null, dateEnd = null) {
    let url;
    if (isLive) {
        url = `/api/wind?stn=${station}&hours=${hours}`;
        console.log(`Loading historical data: ${url}`);
    } else {
        url = `/api/wind?stn=${station}&from_time=${dateStart}&to_time=${dateEnd}`;
    }

    let response;
    try {
        response = await fetch(url);
    } catch (error) {
        if (error?.name === 'AbortError') {
            throw error;
        }
        if (isNetworkFailure(error)) {
            // No response at all: a client-side condition, not a server fault.
            console.warn(`Network error loading historical data from ${url}:`, error);
            report(error, 'warning', url);
        } else {
            console.error('Error loading historical data:', error);
            report(error, 'error', url);
        }
        throw error;
    }

    try {
        if (!response.ok) {
            throw new HistoricalDataError(
                `Historical data request failed: HTTP ${response.status}`,
                { url, status: response.status },
            );
        }
        const data = await response.json();
        if (!Array.isArray(data?.winddata)) {
            throw new HistoricalDataError(
                'Historical data response has no winddata array',
                { url, status: response.status },
            );
        }
        return data.winddata;
    } catch (error) {
        console.error('Error loading historical data:', error);
        report(error, 'error', url);
        throw error;
    }
}
