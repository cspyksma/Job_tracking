from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


ISO = "%Y-%m-%dT%H:%M:%S%z"


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(ISO)


def from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = str(value).strip()
    try:
        return datetime.strptime(value, ISO)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


class JobTrackerDB:
    def __init__(self, db_path: str = "job_tracker.db") -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _table_exists(self, table: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _table_columns(self, table: str) -> set[str]:
        if not self._table_exists(table):
            return set()
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        if column not in self._table_columns(table):
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_sync_state(self) -> None:
        if self._table_exists("sync_state"):
            cols = self._table_columns("sync_state")
            if {"account", "folder", "uidvalidity", "last_seen_uid", "last_sync_at"} <= cols:
                return
            # Legacy single-row sync state table exists; preserve it and create new schema.
            self.conn.execute("ALTER TABLE sync_state RENAME TO sync_state_legacy")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
              account TEXT NOT NULL,
              folder TEXT NOT NULL,
              uidvalidity INTEGER,
              last_seen_uid INTEGER DEFAULT 0,
              last_sync_at TEXT,
              PRIMARY KEY (account, folder)
            )
            """
        )

    def init_schema(self) -> None:
        with self.tx():
            self._migrate_sync_state()

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account TEXT NOT NULL,
                  folder TEXT NOT NULL,
                  uidvalidity INTEGER NOT NULL,
                  uid INTEGER NOT NULL,
                  internal_date TEXT,
                  from_email TEXT,
                  from_domain TEXT,
                  subject TEXT,
                  message_id_header TEXT,
                  snippet TEXT,
                  detected_type TEXT,
                  confidence REAL,
                  matched_by TEXT,
                  linked_record_id TEXT,
                  thread_hint TEXT,
                  raw_meta_json TEXT,
                  ingested_at TEXT NOT NULL,
                  UNIQUE (account, folder, uidvalidity, uid)
                )
                """
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_email_events_uid ON email_events(account, folder, uid)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_email_events_record ON email_events(linked_record_id)")

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                  record_id TEXT PRIMARY KEY,
                  company TEXT,
                  company_domain TEXT,
                  role TEXT,
                  location TEXT,
                  req_id TEXT,
                  job_url TEXT,
                  source TEXT,
                  date_first_seen TEXT,
                  date_applied TEXT,
                  status TEXT,
                  status_date TEXT,
                  last_email_date TEXT,
                  email_thread_link TEXT,
                  last_uid INTEGER,
                  last_message_id_header TEXT,
                  notes TEXT,
                  next_step TEXT,
                  follow_up_due TEXT,
                  user_lock_status INTEGER DEFAULT 0,
                  user_lock_notes INTEGER DEFAULT 0,
                  user_lock_next_step INTEGER DEFAULT 0,
                  confidence REAL,
                  matched_by TEXT,
                  raw_meta_json TEXT
                )
                """
            )
            required_columns = {
                "company": "TEXT",
                "company_domain": "TEXT",
                "role": "TEXT",
                "location": "TEXT",
                "req_id": "TEXT",
                "job_url": "TEXT",
                "source": "TEXT",
                "date_first_seen": "TEXT",
                "date_applied": "TEXT",
                "status": "TEXT",
                "status_date": "TEXT",
                "last_email_date": "TEXT",
                "email_thread_link": "TEXT",
                "last_uid": "INTEGER",
                "last_message_id_header": "TEXT",
                "notes": "TEXT",
                "next_step": "TEXT",
                "follow_up_due": "TEXT",
                "user_lock_status": "INTEGER DEFAULT 0",
                "user_lock_notes": "INTEGER DEFAULT 0",
                "user_lock_next_step": "INTEGER DEFAULT 0",
                "confidence": "REAL",
                "matched_by": "TEXT",
                "raw_meta_json": "TEXT",
            }
            for col, definition in required_columns.items():
                self._ensure_column("applications", col, definition)

            # Compatibility columns from earlier implementation/matching.
            self._ensure_column("applications", "company_norm", "TEXT")
            self._ensure_column("applications", "role_norm", "TEXT")
            self._ensure_column("applications", "recruiter_name", "TEXT")
            self._ensure_column("applications", "recruiter_email", "TEXT")

            # If old columns exist, copy forward once where new columns are empty.
            cols = self._table_columns("applications")
            if "company_raw" in cols:
                self.conn.execute(
                    "UPDATE applications SET company = COALESCE(NULLIF(company, ''), company_raw) WHERE company_raw IS NOT NULL"
                )
            if "role_raw" in cols:
                self.conn.execute(
                    "UPDATE applications SET role = COALESCE(NULLIF(role, ''), role_raw) WHERE role_raw IS NOT NULL"
                )
            if "last_message_id" in cols:
                self.conn.execute(
                    "UPDATE applications SET last_message_id_header = COALESCE(NULLIF(last_message_id_header, ''), last_message_id) WHERE last_message_id IS NOT NULL"
                )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS status_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  record_id TEXT NOT NULL,
                  old_status TEXT,
                  new_status TEXT,
                  changed_at TEXT NOT NULL,
                  cause_event_id INTEGER
                )
                """
            )

    def get_sync_state(self, account: str, folder: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM sync_state WHERE account = ? AND folder = ?",
            (account, folder),
        ).fetchone()

    def upsert_sync_state(
        self,
        account: str,
        folder: str,
        uidvalidity: int,
        last_seen_uid: int,
    ) -> None:
        with self.tx():
            self.conn.execute(
                """
                INSERT INTO sync_state(account, folder, uidvalidity, last_seen_uid, last_sync_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account, folder) DO UPDATE SET
                  uidvalidity = excluded.uidvalidity,
                  last_seen_uid = excluded.last_seen_uid,
                  last_sync_at = excluded.last_sync_at
                """,
                (account, folder, uidvalidity, last_seen_uid, to_iso(datetime.now(timezone.utc))),
            )

    def append_email_event(self, event: dict[str, Any]) -> Optional[int]:
        """Append-only insert. Returns event row id, or None if duplicate UID already ingested."""
        with self.tx():
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO email_events (
                  account, folder, uidvalidity, uid, internal_date, from_email, from_domain, subject,
                  message_id_header, snippet, detected_type, confidence, matched_by, linked_record_id,
                  thread_hint, raw_meta_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["account"],
                    event["folder"],
                    event["uidvalidity"],
                    event["uid"],
                    event.get("internal_date"),
                    event.get("from_email", ""),
                    event.get("from_domain", ""),
                    event.get("subject", ""),
                    event.get("message_id_header", ""),
                    event.get("snippet", ""),
                    event.get("detected_type", "Other"),
                    float(event.get("confidence", 0.0)),
                    event.get("matched_by", ""),
                    event.get("linked_record_id"),
                    event.get("thread_hint"),
                    event.get("raw_meta_json", "{}"),
                    to_iso(datetime.now(timezone.utc)),
                ),
            )
            if cur.rowcount == 0:
                return None
            return int(cur.lastrowid)

    def list_email_events(self, limit: Optional[int] = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM email_events ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            return self.conn.execute(sql, (limit,)).fetchall()
        return self.conn.execute(sql).fetchall()

    def get_application(self, record_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM applications WHERE record_id = ?", (record_id,)).fetchone()

    def get_application_by_req(self, company_norm: str, req_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM applications WHERE company_norm = ? AND req_id = ?",
            (company_norm, req_id),
        ).fetchone()

    def get_application_by_thread_hint(self, thread_hint: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM applications
            WHERE raw_meta_json LIKE ?
            ORDER BY last_email_date DESC
            LIMIT 1
            """,
            (f'%{thread_hint}%',),
        ).fetchone()

    def find_candidates(self, company_norm: str, role_norm: str, sender_domain: str) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM applications
            WHERE company_norm = ?
               OR role_norm = ?
               OR company_domain = ?
            ORDER BY last_email_date DESC
            LIMIT 100
            """,
            (company_norm, role_norm, sender_domain or ""),
        ).fetchall()

    def upsert_application(self, app: dict[str, Any], cause_event_id: Optional[int] = None) -> bool:
        old = self.get_application(app["record_id"])
        created = old is None

        if old and int(old["user_lock_status"] or 0) == 1:
            app["status"] = old["status"]
            app["status_date"] = old["status_date"]

        with self.tx():
            self.conn.execute(
                """
                INSERT INTO applications (
                  record_id, company, company_domain, role, location, req_id, job_url, source, date_first_seen,
                  date_applied, status, status_date, last_email_date, email_thread_link, last_uid,
                  last_message_id_header, notes, next_step, follow_up_due, user_lock_status, user_lock_notes,
                  user_lock_next_step, confidence, matched_by, raw_meta_json, company_norm, role_norm,
                  recruiter_name, recruiter_email
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                  company = excluded.company,
                  company_domain = excluded.company_domain,
                  role = excluded.role,
                  location = excluded.location,
                  req_id = excluded.req_id,
                  job_url = CASE WHEN COALESCE(applications.job_url, '') = '' THEN excluded.job_url ELSE applications.job_url END,
                  source = excluded.source,
                  date_applied = COALESCE(applications.date_applied, excluded.date_applied),
                  status = excluded.status,
                  status_date = excluded.status_date,
                  last_email_date = excluded.last_email_date,
                  email_thread_link = CASE WHEN COALESCE(applications.email_thread_link, '') = '' THEN excluded.email_thread_link ELSE applications.email_thread_link END,
                  last_uid = excluded.last_uid,
                  last_message_id_header = excluded.last_message_id_header,
                  notes = CASE WHEN applications.user_lock_notes = 1 THEN applications.notes ELSE excluded.notes END,
                  next_step = CASE WHEN applications.user_lock_next_step = 1 THEN applications.next_step ELSE excluded.next_step END,
                  follow_up_due = excluded.follow_up_due,
                  confidence = excluded.confidence,
                  matched_by = excluded.matched_by,
                  raw_meta_json = excluded.raw_meta_json,
                  company_norm = excluded.company_norm,
                  role_norm = excluded.role_norm,
                  recruiter_name = excluded.recruiter_name,
                  recruiter_email = excluded.recruiter_email
                """,
                (
                    app["record_id"],
                    app.get("company", ""),
                    app.get("company_domain", ""),
                    app.get("role", ""),
                    app.get("location", ""),
                    app.get("req_id", ""),
                    app.get("job_url", ""),
                    app.get("source", ""),
                    app.get("date_first_seen"),
                    app.get("date_applied"),
                    app.get("status", "NeedsReview"),
                    app.get("status_date"),
                    app.get("last_email_date"),
                    app.get("email_thread_link", ""),
                    app.get("last_uid"),
                    app.get("last_message_id_header", ""),
                    app.get("notes", ""),
                    app.get("next_step", ""),
                    app.get("follow_up_due"),
                    int(app.get("user_lock_status", old["user_lock_status"] if old else 0)),
                    int(app.get("user_lock_notes", old["user_lock_notes"] if old else 0)),
                    int(app.get("user_lock_next_step", old["user_lock_next_step"] if old else 0)),
                    float(app.get("confidence", 0.0)),
                    app.get("matched_by", ""),
                    app.get("raw_meta_json", "{}"),
                    app.get("company_norm", ""),
                    app.get("role_norm", ""),
                    app.get("recruiter_name", ""),
                    app.get("recruiter_email", ""),
                ),
            )

            old_status = old["status"] if old else None
            new_status = app.get("status")
            if old_status != new_status:
                self.conn.execute(
                    """
                    INSERT INTO status_history(record_id, old_status, new_status, changed_at, cause_event_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (app["record_id"], old_status, new_status, to_iso(datetime.now(timezone.utc)), cause_event_id),
                )
        return created

    def list_applications(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM applications
            ORDER BY COALESCE(last_email_date, date_first_seen) DESC
            """
        ).fetchall()

    def apply_manual_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        if not overrides:
            return
        with self.tx():
            for record_id, ov in overrides.items():
                row = self.get_application(record_id)
                if not row:
                    continue
                lock_status = int(ov.get("UserLockStatus", 0))
                lock_notes = int(ov.get("UserLockNotes", 0))
                lock_next_step = int(ov.get("UserLockNextStep", 0))
                status = ov.get("Status", row["status"])
                notes = ov.get("Notes", row["notes"])
                next_step = ov.get("NextStep", row["next_step"])

                # If user changed values, auto-lock that field.
                if status != row["status"]:
                    lock_status = 1
                if (notes or "") != (row["notes"] or ""):
                    lock_notes = 1
                if (next_step or "") != (row["next_step"] or ""):
                    lock_next_step = 1

                self.conn.execute(
                    """
                    UPDATE applications
                    SET status = CASE WHEN ? = 1 THEN ? ELSE status END,
                        status_date = CASE WHEN ? = 1 THEN ? ELSE status_date END,
                        notes = CASE WHEN ? = 1 THEN ? ELSE notes END,
                        next_step = CASE WHEN ? = 1 THEN ? ELSE next_step END,
                        user_lock_status = ?,
                        user_lock_notes = ?,
                        user_lock_next_step = ?
                    WHERE record_id = ?
                    """,
                    (
                        lock_status,
                        status,
                        lock_status,
                        to_iso(datetime.now(timezone.utc)),
                        lock_notes,
                        notes,
                        lock_next_step,
                        next_step,
                        lock_status,
                        lock_notes,
                        lock_next_step,
                        record_id,
                    ),
                )

    def apply_auto_close(self, cutoff: datetime) -> int:
        with self.tx():
            cur = self.conn.execute(
                """
                UPDATE applications
                SET status = 'Closed',
                    status_date = ?
                WHERE status IN ('Opportunity', 'Applied', 'Interview', 'NeedsReview')
                  AND COALESCE(last_email_date, date_first_seen) < ?
                  AND user_lock_status = 0
                """,
                (to_iso(datetime.now(timezone.utc)), to_iso(cutoff)),
            )
            return cur.rowcount

    def summarize(self) -> dict[str, int]:
        tables = ["email_events", "applications", "status_history", "sync_state"]
        out: dict[str, int] = {}
        for t in tables:
            if self._table_exists(t):
                out[t] = int(self.conn.execute(f"SELECT COUNT(*) as n FROM {t}").fetchone()["n"])
        return out

    def debug_dump_application_meta(self, record_id: str) -> dict[str, Any]:
        row = self.get_application(record_id)
        if not row:
            return {}
        try:
            return json.loads(row["raw_meta_json"] or "{}")
        except json.JSONDecodeError:
            return {}
