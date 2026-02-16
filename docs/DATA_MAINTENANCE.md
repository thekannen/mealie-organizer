# Data Maintenance Pipeline

`data-maintenance` runs staged cleanup flow:

`parse -> foods -> units -> taxonomy -> categorize -> cookbooks -> audit`

## Web UI Flow

1. Open `/cookdex`
2. Run `data-maintenance` with `dry_run=true`
3. Review run logs/reports
4. Enable task policy bypass only if write actions are needed
5. Re-run with `apply_cleanups=true`

## Scheduling

Create interval/cron schedules in the Web UI for recurring maintenance runs.