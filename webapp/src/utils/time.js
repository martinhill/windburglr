export const DIRECTIONS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

export function getDirectionText(degrees) {
    if (degrees === null || degrees === undefined) return '--';
    const index = Math.round(degrees / 22.5) % 16;
    return DIRECTIONS[index];
}

export function formatTime(timestamp, isLive = true, stationTimezone = null) {
  const date = new Date(timestamp * 1000);
  if (!isLive && stationTimezone) {
    return date.toLocaleTimeString([], {
      timeZone: stationTimezone,
      hour12: false,
    });
  } else {
    return date.toLocaleTimeString([], {
      hour12: false,
      timeStyle: "short",
    });
  }
}

export function formatDateTime(timestamp, isLive = true, stationTimezone = null) {
    const date = new Date(timestamp * 1000);
    if (!isLive && stationTimezone) {
        return date.toLocaleString('en-US', {
            timeZone: stationTimezone
        });
    } else {
        return date.toLocaleString();
    }
}

export function getYesterdayDate() {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const year = yesterday.getFullYear();
    const month = String(yesterday.getMonth() + 1).padStart(2, '0');
    const day = String(yesterday.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

export function navigateToDate(date, station) {
    const currentParams = new URLSearchParams(window.location.search);
    const stn = currentParams.get('stn') || station;
    window.location.href = `/day/${date}?stn=${stn}`;
}