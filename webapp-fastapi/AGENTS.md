# WindBurglr Development Guidelines

This document contains important guidelines and conventions for maintaining the WindBurglr wind observation application.

## Timezone Handling - CRITICAL RULES

**ALL wind observations are stored in UTC. ALL API parameters must be in UTC. NO EXCEPTIONS.**

### Core Principles:
1. **Database Storage**: All `wind_obs.update_time` values are stored in UTC
2. **API Consistency**: All API query parameters (`from_time`, `to_time`) must be in UTC
3. **No Server-Side Conversion**: The `get_wind_data` API endpoint performs NO timezone conversions
4. **Frontend Responsibility**: Timezone conversion happens ONLY in the frontend for display purposes

### Station Timezone Usage:
- The `stations.timezone` field is used ONLY for:
  - Determining correct UTC start/end timestamps for full-day historical views
  - Frontend display formatting in historical mode
- **NEVER** use station timezone for API parameter conversion

### API Endpoint Rules:

#### `/api/wind` endpoint:
- `from_time` and `to_time` parameters are treated as UTC timestamps
- `hours` parameter uses current UTC time as reference
- Returns `winddata` with UTC timestamps (epoch seconds)
- Station timezone returned in response is for frontend display only

#### Frontend JavaScript:
- `fillDataGap()` sends UTC timestamps using `toISOString()`
- Historical data displays times in station timezone
- Live data displays times in browser local timezone
- Chart time axis respects timezone context (station for historical, local for live)

### Common Mistakes to Avoid:
1. ❌ Converting API parameters from station timezone to UTC in `get_wind_data()`
2. ❌ Assuming `from_time`/`to_time` are in station local time
3. ❌ Performing timezone math in the backend API
4. ❌ Using station timezone for anything other than display and day boundaries

### Testing Timezone Consistency:
When making changes, verify:
- [ ] `fillDataGap()` retrieves correct data after reconnection
- [ ] Historical day views show complete 24-hour periods in station timezone
- [ ] API responses contain UTC timestamps
- [ ] Frontend displays times in appropriate timezone (station for historical, local for live)

## Development Commands

### Linting and Type Checking:
```bash
# Python linting (if available)
ruff check .
ruff format .

# Type checking (if available)
pyright
```

### Testing:
```bash
# Run the application locally
python main.py

# Test with environment variables
DATABASE_URL=your_db_url LOG_LEVEL=DEBUG python main.py
```

### Database:
- Use the provided migration files for schema changes
- Always test timezone-related changes with different station timezones
- Verify that `wind_obs.update_time` remains in UTC after any changes

## Code Style Guidelines

### Python (main.py):
- Use async/await for database operations
- Log important timezone-related operations at DEBUG level
- Keep timezone logic minimal and well-documented
- Use `timezone.utc` for all UTC datetime operations

### JavaScript (templates/index.html):
- Use `toISOString()` for sending timestamps to API
- Use `toLocaleTimeString()` with `timeZone` option for display
- Comment any timezone-related logic clearly
- Maintain separation between UTC data and display formatting

## Architecture Notes

### Data Flow:
1. **Ingestion**: Wind observations → Database (UTC)
2. **API**: Database (UTC) → JSON response (UTC epoch seconds)
3. **Frontend**: UTC data → Display in appropriate timezone
4. **WebSocket**: Real-time updates maintain UTC consistency

### Key Files:
- `main.py`: Contains all API endpoints and timezone logic
- `templates/index.html`: Frontend timezone display logic
- `add_timezone_migration.sql`: Station timezone setup
- `setup_notifications.sql`: Database triggers for real-time updates

## Debugging Timezone Issues

### Common Symptoms:
- `fillDataGap()` not retrieving expected data
- Historical views missing data at day boundaries  
- Time displays showing incorrect values
- WebSocket updates not appearing correctly

### Debug Steps:
1. Check API response timestamps are in UTC
2. Verify frontend is sending UTC parameters
3. Confirm station timezone is correctly configured
4. Test with different browser/system timezones

### Logging:
Enable DEBUG logging to see timezone-related operations:
```bash
LOG_LEVEL=DEBUG python main.py
```

---

**Remember: When in doubt about timezone handling, always default to UTC for data and API operations. Only convert for display purposes in the frontend.**