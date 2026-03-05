from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from extraction.normalize import normalize_company, normalize_role, normalize_subject_for_thread


@dataclass
class ExtractedFields:
    company: str
    company_domain: str
    company_norm: str
    role: str
    role_norm: str
    location: str
    req_id: str
    job_url: str
    source: str
    recruiter_name: str
    recruiter_email: str
    thread_hint: str
    email_thread_link: str
    notes: str


URL_RE = re.compile(r"(https?://[^\s\]>)]+)")
ROLE_SUBJECT_RE = re.compile(r"(?i)\b(for|role|position|opportunity)\b[:\s-]+([^|\n]+)")
COMPANY_SUBJECT_RE = re.compile(r"(?i)\b(at|with|from)\s+([A-Z][\w&.\- ]{1,40})")
LOCATION_RE = re.compile(r"(?i)\b(remote|hybrid|onsite|on-site)\b")


def infer_source(from_domain: str, subject: str) -> str:
    s = subject.lower()
    if "linkedin" in from_domain or "linkedin" in s:
        return "LinkedIn"
    if "indeed" in from_domain or "indeed" in s:
        return "Indeed"
    if "recruit" in s:
        return "Recruiter"
    if "alert" in s:
        return "Job Alert"
    return "Company Site"


def extract_fields(message: dict[str, Any], req_id: str = "", urls: list[str] | None = None) -> ExtractedFields:
    subject = message.get("subject", "")
    body = message.get("body", "")
    from_domain = message.get("from_domain", "")
    from_name = message.get("from_name", "")
    from_email = message.get("from_email", "")

    company = ""
    role = ""
    location = ""
    notes = ""

    c_match = COMPANY_SUBJECT_RE.search(subject)
    if c_match:
        company = c_match.group(2).strip()
    elif from_domain:
        company = from_domain.split(".")[0]

    r_match = ROLE_SUBJECT_RE.search(subject)
    if r_match:
        role = r_match.group(2).strip(" -|:")
    else:
        role = subject.strip()[:120]

    l_match = LOCATION_RE.search(subject + " " + body)
    if l_match:
        location = l_match.group(1).title().replace("-", "")

    found_urls = urls if urls is not None else URL_RE.findall(body)
    job_url = found_urls[0] if found_urls else ""

    thread_hint = message.get("references") or message.get("in_reply_to") or f"{normalize_subject_for_thread(subject)}|{from_domain}"
    thread_hint = str(thread_hint)[:300]
    email_thread_link = f"imap://{message.get('folder', 'INBOX')};uidvalidity={message.get('uidvalidity', 0)};uid={message.get('uid', 0)}"
    source = infer_source(from_domain, subject)

    if not company:
        notes = "Company ambiguous"
    if not role:
        notes = f"{notes}; Role ambiguous".strip("; ")

    return ExtractedFields(
        company=company,
        company_domain=from_domain,
        company_norm=normalize_company(company),
        role=role,
        role_norm=normalize_role(role),
        location=location,
        req_id=req_id,
        job_url=job_url,
        source=source,
        recruiter_name=from_name,
        recruiter_email=from_email,
        thread_hint=thread_hint,
        email_thread_link=email_thread_link,
        notes=notes,
    )
