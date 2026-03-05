# Job Tracking Inbox Sync

Yahoo IMAP -> SQLite (source of truth) -> Excel (`jobs.xlsx`) exporter.

## Architecture

- `email_events` (append-only immutable ingestion log)
- `applications` (canonical current record per job)
- `status_history` (status transition audit trail)
- `sync_state` (per `account+folder` checkpoint with `uidvalidity + last_seen_uid`)

Excel is a view/export only. DB is authoritative.

## Environment Variables

Required:

- `YAHOO_EMAIL`
- `YAHOO_APP_PASSWORD`

Optional:

- `imap.username` in `config.yml` can be used as fallback if `YAHOO_EMAIL` is not set.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```powershell
$env:YAHOO_EMAIL="your@yahoo.com"
$env:YAHOO_APP_PASSWORD="your-app-password"
```

## CLI

Connectivity check:

```powershell
python main.py --config config.yml doctor --folder Inbox
```

Incremental sync:

```powershell
python main.py --config config.yml sync --folder Inbox
```

Initial sync/backfill window (only used when no checkpoint exists):

```powershell
python main.py --config config.yml sync --folder Inbox --since-days 180
```

Export DB -> Excel:

```powershell
python main.py --config config.yml export
```

Run sync then export:

```powershell
python main.py --config config.yml run --folder Inbox --since-days 180
```

Validate rules:

```powershell
python main.py --config config.yml validate-rules
```

## Workbook

- `Applications`: one row per canonical application record.
- `EmailLog`: one row per `email_events` record (up to `export.email_log_limit`).

Status values:

`Opportunity, Applied, Interview, Offer, Rejected, Closed, NeedsReview`

## Roundtrip manual edits

On `export`/`run`, existing `jobs.xlsx` `Applications` rows are read first:

- If `Status`/`Notes`/`NextStep` changed by user, corresponding lock is enabled.
- `user_lock_status`, `user_lock_notes`, `user_lock_next_step` are respected in DB updates.

## Noise Filtering

- `Other` emails never create/update canonical application records.
- `Opportunity` emails must pass sender/phrase gating (`classification.opportunity_gate` in `config.yml`).
- This keeps ads/promotions/newsletters out of your tracker.

## Rebuild (Reclassify Old Emails)

If you change rules and want to clean old data:

```powershell
cd C:\Users\coles\OneDrive\Desktop\Job_tracking
Copy-Item .\job_tracker.db .\job_tracker.db.bak
Copy-Item .\jobs.xlsx .\jobs.xlsx.bak
Remove-Item .\job_tracker.db, .\jobs.xlsx
python main.py --config config.yml run --folder Inbox --since-days 180
```

## Tests

```powershell
python -m pytest -q tests -p no:cacheprovider
```
