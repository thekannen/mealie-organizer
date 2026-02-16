# Parser Migration

[Overview](../README.md) | [Install](INSTALL.md) | [Update](UPDATE.md) | [Tasks](TASKS.md)

`mealie-parser` functionality is now integrated into `mealie-organizer` as `ingredient-parse` and `data-maintenance`.

## Old to New Mapping

- Old repo command:
  - `python -m mealie_parser`
- New repo command:
  - `python -m mealie_organizer.ingredient_parser`

- Docker old:
  - `TASK` not available (separate parser container)
- Docker new:
  - `TASK=ingredient-parse`
  - or `TASK=data-maintenance`

## Environment Variable Compatibility

Primary variables:

- `MEALIE_URL`
- `MEALIE_API_KEY`

Legacy parser aliases are still accepted (with deprecation warning):

- `MEALIE_BASE_URL` -> `MEALIE_URL`
- `MEALIE_API_TOKEN` -> `MEALIE_API_KEY`

## Parser Options

Most parser tuning flags remain available as env overrides:

- `CONFIDENCE_THRESHOLD`
- `PARSER_STRATEGIES`
- `FORCE_PARSER`
- `MAX_RECIPES`
- `AFTER_SLUG`
- `REQUEST_TIMEOUT_SECONDS`
- `REQUEST_RETRIES`
- `REQUEST_BACKOFF_SECONDS`

## Recommended Migration Path

1. Switch credentials to `MEALIE_URL` and `MEALIE_API_KEY`.
2. Run `TASK=ingredient-parse` in `DRY_RUN=true`.
3. Move to `TASK=data-maintenance` for unified operations.
4. Decommission standalone parser scheduling once validated.
