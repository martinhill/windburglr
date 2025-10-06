# TODO

## Issues
* Historical day view starts at 7am?
* Chart label enable/disable click location is displaced above the label

# Code Quality
* Remove get_db_pool dependency injection. Provide get_db_pool as initialization for services. Try to remove main.make_app and refactor tests accordingly.

## CI/CD
* Github deployment action

## Testing
* populate test db for e2e testing, make some assertions
* multi-modal LLM visual front-end checking
* consider parameterized tests

## UI/UX
* move legend to chart controls area
* optional wind direction arrows in place of right axis point plot
* configure better chart animation
* accessibility testing/improvements
* update time display clock/minutes-ago modes with click/touch toggle
* current conditions details in span title attribute + tooltip
  * full time string in update last-update
  * degrees in direction

## Other Enhancements
* shared cache (redis, litefs)
* /api/wind pagination by date
* /api/wind/<station>/bydate/?date=YYYY-MM-DD
