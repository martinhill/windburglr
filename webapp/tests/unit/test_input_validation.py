"""Test /api/wind input limits and escaping of values the templates put into scripts."""

import json
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.config import ISO_FORMAT, MAX_QUERY_HOURS, _sample_rate, get_sentry_config


def _iso(dt: datetime) -> str:
    return dt.strftime(ISO_FORMAT)


@pytest.mark.parametrize("hours", [0, -1, MAX_QUERY_HOURS + 1, "abc"])
def test_api_wind_rejects_bad_hours(test_client, hours):
    response = test_client.get(f"/api/wind?hours={hours}")
    assert response.status_code == 422


def test_api_wind_accepts_max_hours(test_client):
    response = test_client.get(f"/api/wind?hours={MAX_QUERY_HOURS}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        "from_time=yesterday&to_time=2025-01-01T00:00:00",
        "from_time=2025-01-01T00:00:00&to_time=2025-01-01",
        "from_time=2025-13-01T00:00:00&to_time=2025-12-02T00:00:00",
        "from_time=2025-01-01T00:00:00Z&to_time=2025-01-02T00:00:00",
    ],
)
def test_api_wind_rejects_malformed_times(test_client, params):
    response = test_client.get(f"/api/wind?{params}")
    assert response.status_code == 400
    assert "Invalid from_time or to_time" in response.json()["detail"]


@pytest.mark.parametrize(
    "params", ["from_time=2025-01-01T00:00:00", "to_time=2025-01-01T00:00:00"]
)
def test_api_wind_requires_both_times(test_client, params):
    response = test_client.get(f"/api/wind?{params}")
    assert response.status_code == 400


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(hours=-1)])
def test_api_wind_rejects_empty_or_reversed_range(test_client, offset):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    response = test_client.get(
        f"/api/wind?from_time={_iso(start)}&to_time={_iso(start + offset)}"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "from_time must be before to_time"


def test_api_wind_rejects_range_over_limit(test_client):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=MAX_QUERY_HOURS, seconds=1)
    response = test_client.get(f"/api/wind?from_time={_iso(start)}&to_time={_iso(end)}")
    assert response.status_code == 400
    assert str(MAX_QUERY_HOURS) in response.json()["detail"]


def test_api_wind_accepts_range_at_limit(test_client, mock_test_db_manager):
    mock_test_db_manager.create_test_data(station_name="CYTZ", days=1)
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(hours=MAX_QUERY_HOURS)
    response = test_client.get(f"/api/wind?from_time={_iso(start)}&to_time={_iso(end)}")
    assert response.status_code == 200
    data = response.json()
    assert data["start_time"] == start.isoformat()
    assert data["end_time"] == end.isoformat()
    assert len(data["winddata"]) > 0


# A station name that would break out of a quoted JS string or the script element
NASTY_STATION = "a\\'b\"c\n</script><script>alert(1)</script>"


def _script_value(html: str, name: str):
    """Parse the JSON literal assigned to window.<name> in the page."""
    match = re.search(rf"window\.{name} = (.*);$", html, re.MULTILINE)
    assert match, f"window.{name} not found"
    return json.loads(match.group(1))


def test_index_script_values_are_json_encoded(test_client):
    response = test_client.get("/", params={"stn": NASTY_STATION, "hours": 6})
    assert response.status_code == 200
    html = response.text
    assert "<script>alert(1)" not in html
    assert _script_value(html, "STATION") == NASTY_STATION
    assert _script_value(html, "IS_LIVE") is True
    assert _script_value(html, "HOURS") == 6


def test_day_script_values_are_json_encoded(test_client):
    response = test_client.get("/day/2025-03-09", params={"stn": NASTY_STATION})
    assert response.status_code == 200
    html = response.text
    assert "<script>alert(1)" not in html
    assert _script_value(html, "STATION") == NASTY_STATION
    assert _script_value(html, "IS_LIVE") is False
    tz = ZoneInfo(_script_value(html, "STATION_TIMEZONE"))
    day_start = datetime(2025, 3, 9, tzinfo=tz)
    assert _script_value(html, "DATE_START") == _iso(day_start.astimezone(UTC))
    assert _script_value(html, "DATE_END") == _iso(
        (day_start + timedelta(days=1)).astimezone(UTC)
    )


def test_sentry_browser_config_is_json_encoded(test_client):
    html = test_client.get("/").text
    match = re.search(r"Sentry\.init\(\{(.*?)\}\);", html, re.DOTALL)
    assert match
    init = match.group(1)
    assert re.search(r'environment: "[^"\n]*",', init)
    assert re.search(r'release: "[^"\n]*",', init)
    rate = get_sentry_config()["traces_sample_rate"]
    assert f"tracesSampleRate: {json.dumps(rate)}," in init


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 0.1), ("", 0.1), ("0.25", 0.25), ("1", 1.0), ("2", 1.0), ("-1", 0.0), ("x", 0.1)],
)
def test_sentry_sample_rate_from_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)
    else:
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", value)
    assert _sample_rate("SENTRY_TRACES_SAMPLE_RATE", 0.1) == expected
