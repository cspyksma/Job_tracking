from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EmailRecord:
    message_id: str
    imap_uid: int
    thread_key: Optional[str]
    received_at: datetime
    from_name: str
    from_email: str
    from_domain: str
    subject: str
    snippet: str
    raw_hash: str
    detected_type: str
    classification_confidence: float
    matched_by: str
    linked_record_id: Optional[str]
    extractor_notes: str


@dataclass
class ApplicationRecord:
    record_id: str
    company_raw: str
    company_norm: str
    role_raw: str
    role_norm: str
    location: str
    req_id: str
    job_url: str
    source: str
    date_first_seen: datetime
    date_applied: Optional[datetime]
    status: str
    status_date: datetime
    last_email_date: datetime
    recruiter_name: str
    recruiter_email: str
    next_step: str
    follow_up_due: Optional[datetime]
    notes: str
    email_thread_link: str
    last_message_id: str
    confidence: float
    matched_by: str
