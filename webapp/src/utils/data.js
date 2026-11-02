export function filterOldObservations(data, isLive, currentTimeWindowHours) {
    if (!isLive || currentTimeWindowHours <= 0) {
        return data;
    }

    const now = Date.now() / 1000;
    const cutoffTime = now - (currentTimeWindowHours * 3600);
    return data.filter(point => point[0] >= cutoffTime);
}

export async function loadHistoricalData(station, hours, isLive, dateStart = null, dateEnd = null) {
    try {
        let url;
        if (isLive) {
            url = `/api/wind?stn=${station}&hours=${hours}`;
            console.log(`Loading historical data: ${url}`);
        } else {
            url = `/api/wind?stn=${station}&from_time=${dateStart}&to_time=${dateEnd}`;
        }

        const response = await fetch(url);
        const data = await response.json();
        return data.winddata;
    } catch (error) {
        console.error('Error loading historical data:', error);
        if (window.Sentry) {
            window.Sentry.captureException(error);
        }
        throw error;
    }
}
