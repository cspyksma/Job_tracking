# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
python -m pytest -q tests -p no:cacheprovider

# Run a single test file
python -m pytest -q tests/test_rules_engine.py -p no:cacheprovider

# Run a single test by name
python -m pytest -q tests/test_extract_fields.py::test_extract_role_from_structured_subject -p no:cacheprovider

# Test IMAP connectivity
python main.py --config config.yml doctor --folder Inbox

# Incremental sync (uses UID checkpoints, safe to re-run)
python main.py --config config.yml sync --folder Inbox

# Full backfill (180-day lookback)
python main.py --config config.yml sync --folder Inbox --since-days 180

# Export DB → Excel
python main.py --config config.yml export

# Sync + export combined
python main.py --config config.yml run --folder Inbox

# Verify classification rules YAML is valid
python main.py --config config.yml validate-rules
```

**Environment variables required for sync:**
- `YAHOO_EMAIL` — Yahoo address
- `YAHOO_APP_PASSWORD` — Yahoo app password (not login password)

## Architecture

This is a rule-based ETL pipeline: Yahoo IMAP → SQLite → Excel.

### Data flow

```
Yahoo IMAP
  └─► connectors/yahoo_imap_connector.py   (fetch raw messages)
        └─► classification/rules_engine.py  (score → type + confidence)
              └─► extraction/extract_fields.py (company, role, location, URL, recruiter)
                    └─► matching/matcher.py    (fuzzy-dedup → canonical application record)
                          └─► state_machine/status_logic.py (forward-only status)
                                └─► storage/db.py            (SQLite upsert)
                                      └─► export/excel_writer.py (jobs.xlsx roundtrip)
```

### Storage design (SQLite — `job_tracker.db`)

| Table | Type | Purpose |
|-------|------|---------|
| `email_events` | Append-only | Immutable log of every email processed |
| `applications` | Mutable | One canonical record per job application |
| `status_history` | Append-only | Audit trail of status transitions |
| `sync_state` | Mutable | UIDVALIDITY + last UID checkpoint per folder |

`applications.record_id` is a SHA1 hash of `(company_norm, req_id)` when a req_id is present, or a hash of `(company_norm, role_norm, domain)` otherwise. This makes IDs deterministic and dedup-safe.

### Classification (`classification/`)

`rules.yml` defines keyword/regex scoring per email type. `rules_engine.py` sums scores, applies guardrails (e.g., marketing "offer" must not outscore real Offer patterns), and returns a `ClassificationResult` with `detected_type` and `confidence`. Confidence = `0.45 + score/20`, capped at 0.99. Types in precedence order: Offer > Rejected > Interview > Applied > Opportunity > Ad > Other.

**Opportunity gate** in `config.yml` is a noise filter: an Opportunity classification only sticks if the sender domain is in `allowed_domains` OR the body contains one of the `required_phrases`. This prevents newsletter-style recruiter blasts from entering the tracker.

### Matching (`matching/matcher.py`)

Three-tier lookup before creating a new record:
1. **req_id hash** — exact match if requisition ID extracted
2. **Thread match** — References/In-Reply-To headers
3. **Fuzzy score** — SequenceMatcher on 45% company + 45% role + 10% domain; ≥0.84 = confident, 0.65–0.84 = NeedsReview

### Status machine (`state_machine/status_logic.py`)

Status is forward-only (never downgrades). Precedence: `Offer(6) > Rejected(5) > Interview(4) > Applied(3) > Opportunity(2) > NeedsReview(1) > Closed(0)`. Applications with no email activity for 45 days are auto-closed on next sync.

### Excel roundtrip (`export/excel_writer.py`)

The workbook at `config.yml → export.xlsx_path` is read before each export to preserve manual edits in three columns: **Status**, **Notes**, **NextStep**. If the user has set `user_lock_*` flags (written back by a prior export), those columns are not overwritten by the pipeline. Two sheets: **Applications** and **EmailLog** (capped at 500 rows).

### Key config knobs (`config.yml`)

| Key | Default | Effect |
|-----|---------|--------|
| `sync.initial_backfill_days` | 180 | Lookback window on first sync (no checkpoint) |
| `sync.max_messages_per_run` | 500 | IMAP batch size |
| `classification.min_confident_score` | 5 | Minimum score to assign a type (else Other) |
| `classification.needs_review_confidence_threshold` | 0.55 | Below this → NeedsReview flag |
| `matching.fuzzy_high_threshold` | 0.84 | Confident dedup match |
| `matching.fuzzy_low_threshold` | 0.65 | Ambiguous dedup (NeedsReview) |
| `status.auto_close_days` | 45 | Days of silence before auto-close |

### Normalization (`extraction/normalize.py`)

`normalize_company()` strips legal suffixes (Inc, LLC, Ltd, Corp, …) before hashing/matching. `normalize_role()` strips seniority tokens (Sr, Jr, Lead, Principal, …). These normalizations must stay in sync with the matching logic — changes here affect record deduplication and existing DB IDs.
