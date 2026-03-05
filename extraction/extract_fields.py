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
COMPANY_SUBJECT_RE = re.compile(r"(?i)\b(at|with|from)\s+([A-Z][\w&.\- ]{1,40})")
LOCATION_RE = re.compile(r"(?i)\b(remote|hybrid|onsite|on-site)\b")
ROLE_PATTERNS = [
    re.compile(r'(?i)\b(?:role|position|title)\s*[:\-]\s*["“]?([^"\n|@]{3,80})'),
    re.compile(r'(?i)\bfor\s+["“]?([A-Za-z0-9/&,\-\s]{3,80})\s+\b(?:role|position)\b'),
    re.compile(r'(?i)\binterview\s+(?:for|with)\s+["“]?([A-Za-z0-9/&,\-\s]{3,80})'),
    re.compile(r'(?i)\byour application to\s+["“]?([A-Za-z0-9/&,\-\s]{3,80})'),
]
NOISY_ROLE_TOKENS = {
    "unsubscribe",
    "newsletter",
    "promo",
    "discount",
    "limited time",
    "receipt",
    "invoice",
    "verification",
    "security alert",
    "otp",
    "code",
    "sale",
    "offer expires",
}


def _clean_role_candidate(text: str, company: str) -> str:
    role = (text or "").strip().strip("|:- ").strip('"').strip("'")
    role = re.sub(r"\s+", " ", role)
    role = re.sub(r"\b(at|with|from)\s+[A-Z][\w&.\- ]{1,40}$", "", role, flags=re.I).strip()
    if company:
        role = re.sub(re.escape(company), "", role, flags=re.I).strip(" -,:")
    if len(role) < 3 or len(role) > 80:
        return ""
    low = role.lower()
    if any(tok in low for tok in NOISY_ROLE_TOKENS):
        return ""
    if "http://" in low or "https://" in low:
        return ""
    # Require at least one alphabetic word-like token.
    if not re.search(r"[a-zA-Z]{2,}", role):
        return ""
    return role


def _extract_role(subject: str, body: str, company: str) -> str:
    candidates: list[str] = []
    for pattern in ROLE_PATTERNS:
        for m in pattern.finditer(subject):
            candidates.append(m.group(1))
    # Backup signals from body for confirmations/interviews.
    body_lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    for ln in body_lines[:40]:
        m = re.search(r'(?i)\b(?:position|role|title)\s*[:\-]\s*["“]?([^"\n|@]{3,80})', ln)
        if m:
            candidates.append(m.group(1))

    for c in candidates:
        cleaned = _clean_role_candidate(c, company)
        if cleaned:
            return cleaned
    return ""


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

    role = _extract_role(subject, body, company)

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
