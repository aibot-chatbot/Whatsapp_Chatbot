# Subscription Lifecycle Operations

This document describes the production operation of the subscription expiry
and renewal processing system.

## Lifecycle Command

The expiry processor is a standalone CLI command that checks all subscriptions
whose billing period or trial has ended and transitions them to `expired`.

### Command

```bash
python -m app.jobs.process_subscription_lifecycle [--batch-size N] [--dry-run]
```

### Arguments

| Argument       | Default | Description |
|----------------|---------|-------------|
| `--batch-size` | 100     | Maximum subscriptions to process per run. Must be a positive integer. |
| `--dry-run`    | false   | Log what would be done without modifying any data. Batch size capped at 10. |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0    | Completed successfully. Per-company errors are logged but do not change the exit code. |
| 1    | Unrecoverable setup failure (configuration error, DB initialization failure, etc.). |

### Recommended Frequency

Every **5–15 minutes** is sufficient. The command is idempotent -- subscriptions
already in `expired` status are skipped.

## Example Scheduler Configurations

### Linux Crontab

```cron
*/10 * * * * cd /path/to/project && /usr/bin/python -m app.jobs.process_subscription_lifecycle --batch-size 100 >> /var/log/subscription_lifecycle.log 2>&1
```

### Windows Task Scheduler

```
Program/script:   C:\path\to\python.exe
Arguments:        -m app.jobs.process_subscription_lifecycle --batch-size 100
Start in:         C:\path\to\project
```

### Hosting Platform (Render / Heroku / etc.)

Create a **Cron Job** or **Scheduled Task** that runs:

```bash
python -m app.jobs.process_subscription_lifecycle
```

## Required Environment Variables

The same environment as the main application:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SECRET_KEY`

No additional environment variables are required specifically for this command.

## Log Messages

The command logs structured messages at `INFO` level:

```
2026-07-09 12:00:00 UTC [INFO] ...: Starting subscription lifecycle processing (batch_size=100)
2026-07-09 12:00:01 UTC [INFO] ...: Found 5 due subscription(s) for expiry processing
2026-07-09 12:00:01 UTC [INFO] ...: Expired subscription 42 (company 7): trialing -> expired (Trial period ended)
2026-07-09 12:00:01 UTC [INFO] ...: Expired subscription 43 (company 8): active -> expired (Billing period ended)
2026-07-09 12:00:01 UTC [INFO] ...: Lifecycle processing complete: 5 scanned, 2 expired, 3 unchanged, 0 failed
```

Errors are logged at `WARNING` level:

```
2026-07-09 12:00:01 UTC [WARNING] ...: Failed: company=9, error=Subscription not found
```

## Verification

### Check that the job ran

Search logs for:

```
Lifecycle processing complete
```

### Check current subscription statuses

Query the database:

```sql
SELECT company_id, status, current_period_end, trial_ends_at
FROM company_subscriptions
WHERE status IN ('trialing', 'active', 'past_due')
  AND (current_period_end <= NOW() OR trial_ends_at <= NOW());
```

If this returns rows, the job needs to run (or is within the scheduling window).

### Safe to rerun

Yes. The command is fully idempotent. Subscriptions that are already `expired`
or whose billing period has not yet ended are skipped. Running it multiple times
in quick succession is safe.

## Scheduler Not Configured Warning

The system includes scheduler-safe guards in:

- **AI access policy**: checks `current_period_end` even when status is `active`,
  denying access if the period has ended but the scheduled job has not yet
  transitioned the subscription to `expired`.
- **Billing guard**: checks `current_period_end` for creation-action enforcement
  when the subscription is still marked `active`.

These guards protect the system if the cron job is delayed or not yet configured.
However, the scheduled job should still be deployed for correct database status
tracking and clean audit trails.

## Dry Run

Use `--dry-run` to preview which subscriptions would be affected:

```bash
python -m app.jobs.process_subscription_lifecycle --dry-run
```

Dry run mode:
- Caps batch size to 10
- Never modifies data
- Logs each due subscription with its current status and expiry timestamps
- Exits with code 0
