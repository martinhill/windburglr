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

export async function fillDataGap(station, lastObservationTime, hours, isLive) {
    if (!isLive) {
        console.log('No gap filling needed - no last observation time or not in live mode');
        return [];
    }

    try {
        var url;
        if (!lastObservationTime) {
          console.log(`Reloading data: ${hours} hours`);
          url = `/api/wind?stn=${station}&hours=${hours}`;
        }
        else {
          console.log(`Filling data gap since: ${new Date(lastObservationTime * 1000)}`);
          const fromTime = new Date(lastObservationTime * 1000).toISOString().slice(0, 19);
          const toTime = new Date().toISOString().slice(0, 19);

          url = `/api/wind?stn=${station}&from_time=${fromTime}&to_time=${toTime}`;
        }
        const response = await fetch(url);
        const data = await response.json();

        if (data.winddata && data.winddata.length > 0) {
            console.log(`Retrieved ${data.winddata.length} data points to fill gap`);
            return data.winddata;
        }

        return [];
    } catch (error) {
        console.error('Error filling data gap:', error);
        if (window.Sentry) {
            window.Sentry.captureException(error);
        }
        return [];
    }
}
