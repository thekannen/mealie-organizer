# Parser Migration

`mealie-parser` behavior is now part of the Web UI workflow.

## Mapping

- Old: standalone parser command/container
- New: queue task `ingredient-parse` from `/organizer`

## Runtime credentials

Use:

- `MEALIE_URL`
- `MEALIE_API_KEY`

## Parser tuning

Tune parser behavior through Web UI environment variable settings:

- `CONFIDENCE_THRESHOLD`
- `PARSER_STRATEGIES`
- `FORCE_PARSER`
- `MAX_RECIPES`
- `AFTER_SLUG`
- `REQUEST_TIMEOUT_SECONDS`
- `REQUEST_RETRIES`
- `REQUEST_BACKOFF_SECONDS`

## Recommended migration path

1. Configure credentials in startup `.env`
2. Open `/organizer`
3. Run `ingredient-parse` with `dry_run=true`
4. Review logs/reports
5. Enable policy bypass only when applying write changes