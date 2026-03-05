from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from classification.rules_engine import RulesEngine
from connectors.yahoo_imap_connector import YahooIMAPConnector
from export.excel_writer import read_existing_application_overrides, write_excel
from extraction.extract_fields import extract_fields
from matching.matcher import Matcher
from state_machine.status_logic import compute_follow_up_due, next_status
from storage.db import JobTrackerDB, from_iso, to_iso
from utils.datetime_utils import utc_now
from utils.logging import setup_logging


LOGGER = logging.getLogger(__name__)


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yahoo inbox to SQLite/Excel job tracker")
    parser.add_argument("--config", default="config.yml", help="Config file path")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Test IMAP connectivity and list folders")
    doctor.add_argument("--folder", default="Inbox")

    sync = sub.add_parser("sync", help="Fetch new emails and update DB")
    sync.add_argument("--folder", default="Inbox")
    sync.add_argument("--since-days", type=int, default=None, help="Used only for initial sync when no UID checkpoint exists")

    export = sub.add_parser("export", help="Export DB to jobs.xlsx")
    export.add_argument("--folder", default="Inbox")

    run = sub.add_parser("run", help="sync then export")
    run.add_argument("--folder", default="Inbox")
    run.add_argument("--since-days", type=int, default=None)

    validate = sub.add_parser("validate-rules")
    validate.add_argument("--rules", default="classification/rules.yml")
    return parser.parse_args()


def _resolve_account(cfg: dict[str, Any]) -> str:
    env_email = os.getenv("YAHOO_EMAIL", "").strip()
    if env_email:
        return env_email
    fallback = cfg.get("imap", {}).get("username", "").strip()
    if fallback:
        LOGGER.warning("YAHOO_EMAIL not set; falling back to config imap.username")
        return fallback
    raise RuntimeError("Missing YAHOO_EMAIL environment variable")


def build_connector(cfg: dict[str, Any]) -> tuple[YahooIMAPConnector, str]:
    imap = cfg["imap"]
    account = _resolve_account(cfg)
    app_password = os.getenv("YAHOO_APP_PASSWORD", "")
    if not app_password:
        raise RuntimeError("Missing env var YAHOO_APP_PASSWORD for Yahoo app password")
    return (
        YahooIMAPConnector(
            host=imap.get("host", "imap.mail.yahoo.com"),
            port=int(imap.get("port", 993)),
            username=account,
            app_password=app_password,
        ),
        account,
    )


def run_doctor(cfg: dict[str, Any], folder: str) -> int:
    connector, account = build_connector(cfg)
    folders = connector.list_folders()
    print(f"Connected as: {account}")
    print(f"Found {len(folders)} folders")
    for f in folders[:30]:
        print(f"- {f}")
    if folder not in folders:
        print(f"Warning: folder '{folder}' not found in LIST output.")
    return 0


def _is_job_relevant(detected_type: str) -> bool:
    return detected_type in {
        "Opportunity",
        "ApplicationConfirmation",
        "InterviewRequest",
        "Rejection",
        "Offer",
    }


def _opportunity_gate_passed(cfg: dict[str, Any], msg: dict[str, Any]) -> bool:
    gate = cfg.get("classification", {}).get("opportunity_gate", {})
    allowed_domains = [d.lower() for d in gate.get("allowed_domains", [])]
    required_phrases = [p.lower() for p in gate.get("required_phrases", [])]
    blocked_sender_fragments = [b.lower() for b in gate.get("blocked_sender_fragments", [])]

    from_domain = (msg.get("from_domain") or "").lower()
    from_email = (msg.get("from_email") or "").lower()
    text = f"{msg.get('subject', '')}\n{msg.get('body', '')}".lower()

    if any(fragment in from_email for fragment in blocked_sender_fragments):
        return False

    domain_ok = any(from_domain.endswith(d) for d in allowed_domains)
    phrase_ok = any(p in text for p in required_phrases)
    return domain_ok or phrase_ok


def run_sync(cfg: dict[str, Any], folder: str, since_days: int | None = None) -> dict[str, int]:
    db = JobTrackerDB()
    db.init_schema()
    rules = RulesEngine("classification/rules.yml", cfg)
    matcher = Matcher(db, cfg)
    connector, account = build_connector(cfg)

    sync_row = db.get_sync_state(account, folder)
    known_uidvalidity = int(sync_row["uidvalidity"] or 0) if sync_row else 0
    last_seen_uid = int(sync_row["last_seen_uid"] or 0) if sync_row else 0
    effective_since_days = since_days if since_days is not None else int(cfg.get("sync", {}).get("initial_backfill_days", 180))
    max_messages = int(cfg.get("sync", {}).get("max_messages_per_run", 500))
    snippet_len = int(cfg.get("export", {}).get("snippet_length", 280))
    threshold = float(cfg.get("classification", {}).get("needs_review_confidence_threshold", 0.55))
    follow_up_days = cfg.get("status", {}).get("follow_up_days", {})

    result = connector.fetch_incremental_messages(
        folder=folder,
        last_seen_uid=last_seen_uid,
        known_uidvalidity=known_uidvalidity,
        since_days=effective_since_days,
        max_messages=max_messages,
    )
    uidvalidity = int(result["uidvalidity"] or 0)
    messages = result["messages"]

    if known_uidvalidity and uidvalidity and known_uidvalidity != uidvalidity:
        LOGGER.warning(
            "UIDVALIDITY changed for account=%s folder=%s old=%s new=%s. Resetting checkpoint.",
            account,
            folder,
            known_uidvalidity,
            uidvalidity,
        )
        last_seen_uid = 0

    if not messages:
        db.upsert_sync_state(account, folder, uidvalidity, last_seen_uid)
        LOGGER.info("No new messages found for account=%s folder=%s", account, folder)
        return {"processed": 0, "created": 0, "updated": 0, "events": 0}

    created = 0
    updated = 0
    events = 0
    max_uid_seen = last_seen_uid

    for msg in messages:
        uid = int(msg["uid"])
        max_uid_seen = max(max_uid_seen, uid)
        subject = msg.get("subject", "")
        body = msg.get("body", "")

        cls = rules.classify(subject, body, msg.get("from_domain", ""))
        urls = rules.extract_urls(body)
        req_id = rules.extract_req_id(subject + "\n" + body)

        msg_context = dict(msg)
        msg_context["folder"] = folder
        msg_context["uidvalidity"] = uidvalidity
        fields = extract_fields(msg_context, req_id=req_id, urls=urls)
        snippet = (body or subject)[:snippet_len]

        linked_record_id = None
        status_change = ""
        app_was_created = False
        raw_meta: dict[str, Any] = {
            "signals": cls.signals,
            "req_id": req_id,
            "urls": urls,
        }

        if cls.detected_type == "Ad":
            detected_type = "Other"
            raw_meta["filtered_reason"] = "ad/newsletter"
        else:
            detected_type = cls.detected_type

        if detected_type == "Opportunity" and not _opportunity_gate_passed(cfg, msg):
            raw_meta["opportunity_gate"] = "blocked"
            detected_type = "Other"

        # Hard rule: "Other" never creates/updates canonical application records.
        should_link = detected_type != "Other" and _is_job_relevant(detected_type)
        if should_link:
            match = matcher.match_or_create(
                company_norm=fields.company_norm,
                company_domain=fields.company_domain,
                role_norm=fields.role_norm,
                req_id=fields.req_id,
                thread_hint=fields.thread_hint,
                first_seen=msg["internal_date"],
            )
            linked_record_id = match.record_id
            current = db.get_application(match.record_id)
            current_status = current["status"] if current else None
            target_status = next_status(current_status, detected_type, cls.confidence, threshold)
            if match.ambiguous and not current:
                target_status = "NeedsReview"
                raw_meta["ambiguity"] = match.ambiguity_reason

            status_date = msg["internal_date"] if target_status != current_status else (from_iso(current["status_date"]) if current else msg["internal_date"])
            status_date = status_date or msg["internal_date"]
            date_applied = (
                msg["internal_date"]
                if detected_type == "ApplicationConfirmation" and (not current or not current["date_applied"])
                else (from_iso(current["date_applied"]) if current else None)
            )
            follow_up_due = compute_follow_up_due(target_status, status_date, follow_up_days)

            app_payload = {
                "record_id": match.record_id,
                "company": fields.company,
                "company_domain": fields.company_domain,
                "role": fields.role,
                "location": fields.location,
                "req_id": fields.req_id,
                "job_url": fields.job_url,
                "source": fields.source,
                "date_first_seen": (current["date_first_seen"] if current else None) or to_iso(msg["internal_date"]),
                "date_applied": to_iso(date_applied),
                "status": target_status if target_status else "NeedsReview",
                "status_date": to_iso(status_date),
                "last_email_date": to_iso(msg["internal_date"]),
                "email_thread_link": fields.email_thread_link,
                "last_uid": uid,
                "last_message_id_header": msg["message_id_header"],
                "notes": (current["notes"] if current else "") or fields.notes,
                "next_step": current["next_step"] if current else "",
                "follow_up_due": to_iso(follow_up_due),
                "confidence": cls.confidence if not current else max(float(current["confidence"] or 0), cls.confidence),
                "matched_by": cls.matched_by,
                "raw_meta_json": json.dumps(
                    {
                        **raw_meta,
                        "thread_hint": fields.thread_hint,
                        "match": {"matched_by": match.matched_by, "confidence": match.confidence, "ambiguous": match.ambiguous},
                    }
                ),
                "company_norm": fields.company_norm,
                "role_norm": fields.role_norm,
                "recruiter_name": fields.recruiter_name,
                "recruiter_email": fields.recruiter_email,
            }
            app_was_created = db.upsert_application(app_payload)
            created += 1 if app_was_created else 0
            updated += 0 if app_was_created else 1
            if current_status != app_payload["status"]:
                status_change = f"{current_status or '(new)'} -> {app_payload['status']}"

        event_id = db.append_email_event(
            {
                "account": account,
                "folder": folder,
                "uidvalidity": uidvalidity,
                "uid": uid,
                "internal_date": to_iso(msg["internal_date"]),
                "from_email": msg["from_email"],
                "from_domain": msg["from_domain"],
                "subject": subject,
                "message_id_header": msg["message_id_header"],
                "snippet": snippet,
                "detected_type": detected_type,
                "confidence": cls.confidence,
                "matched_by": cls.matched_by,
                "linked_record_id": linked_record_id,
                "thread_hint": fields.thread_hint,
                "raw_meta_json": json.dumps(raw_meta),
            }
        )
        if event_id is not None:
            events += 1

        LOGGER.info(
            "email_processed uid=%s detected_type=%s confidence=%.2f linked_record_id=%s status_change=%s",
            uid,
            detected_type,
            cls.confidence,
            linked_record_id,
            status_change or "none",
        )

    auto_close_days = int(cfg.get("status", {}).get("auto_close_days", 45))
    db.apply_auto_close(utc_now() - timedelta(days=auto_close_days))
    db.upsert_sync_state(account, folder, uidvalidity, max_uid_seen)

    LOGGER.info(
        "Sync complete account=%s folder=%s processed=%s created=%s updated=%s events=%s",
        account,
        folder,
        len(messages),
        created,
        updated,
        events,
    )
    return {"processed": len(messages), "created": created, "updated": updated, "events": events}


def run_export(cfg: dict[str, Any]) -> None:
    db = JobTrackerDB()
    db.init_schema()
    xlsx_path = cfg["export"]["xlsx_path"]
    overrides = read_existing_application_overrides(xlsx_path)
    db.apply_manual_overrides(overrides)
    write_excel(
        xlsx_path,
        db.list_applications(),
        db.list_email_events(limit=int(cfg.get("export", {}).get("email_log_limit", 5000))),
        email_log_limit=int(cfg.get("export", {}).get("email_log_limit", 5000)),
    )
    LOGGER.info("Exported workbook to %s", xlsx_path)


def run_validate_rules(cfg: dict[str, Any], rules_path: str) -> int:
    rules = RulesEngine(rules_path, cfg)
    ok, errors = rules.validate()
    if ok:
        print("rules.yml is valid")
        return 0
    for err in errors:
        print(f"- {err}")
    return 1


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg["logging"]["level"], cfg["logging"]["file"])
    Path("logs").mkdir(exist_ok=True)

    if args.command == "doctor":
        return run_doctor(cfg, args.folder)
    if args.command == "sync":
        run_sync(cfg, folder=args.folder, since_days=args.since_days)
        return 0
    if args.command == "export":
        run_export(cfg)
        return 0
    if args.command == "run":
        run_sync(cfg, folder=args.folder, since_days=args.since_days)
        run_export(cfg)
        return 0
    if args.command == "validate-rules":
        return run_validate_rules(cfg, args.rules)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
