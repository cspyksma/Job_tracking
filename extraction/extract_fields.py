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
# Only match "at/with/from CompanyName" — NOT "to/in" which is case-insensitive
# and causes "to Data Analyst" to extract the role as the company.
COMPANY_SUBJECT_RE = re.compile(r"(?i)\b(at|with|from)\s+([A-Z][\w&.\- ]{1,40})")
# Matches "Company | Application..." subject format used by Workday / Ashby
COMPANY_PIPE_RE = re.compile(r"^([A-Z][\w&.\- ]{1,40})\s*\|")

# ATS platforms where the real company is in the email local part (zillow@myworkday.com)
_ATS_LOCAL_PART_DOMAINS = {
    "workday.com", "myworkdayjobs.com",
}
# ATS platforms where the real company is in the subdomain (pvrea.hire.trakstar.com)
_ATS_SUBDOMAIN_DOMAINS = {
    "trakstar.com", "icims.com",
}
# All ATS domains (for body-scan trigger)
_ATS_SENDER_DOMAINS = _ATS_LOCAL_PART_DOMAINS | _ATS_SUBDOMAIN_DOMAINS | {
    "greenhouse-mail.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "taleo.net",
}

_JOB_URL_SIGNALS = {"/job", "/jobs", "/career", "/careers", "/opening", "/position", "/apply", "/requisition"}

_DOMAIN_NOISE_PREFIXES = {
    "mail", "noreply", "no-reply", "notifications", "notification",
    "alerts", "alert", "info", "support", "do-not-reply", "donotreply",
    "mailer", "smtp", "bounce", "auto", "news", "reply", "replies",
    "email", "emails", "hello", "hi", "contact", "team",
}
# Words stripped from sender display names when deriving company
_SENDER_NOISE_WORDS = {
    "hiring", "team", "recruiting", "recruitment", "talent", "acquisition",
    "careers", "career", "workday", "greenhouse", "ashby", "lever",
    "inc", "llc", "corp", "ltd",
}
LOCATION_RE = re.compile(r"(?i)\b(remote|hybrid|onsite|on-site)\b")
ROLE_PATTERNS = [
    re.compile(r'(?i)\b(?:role|position|title)\s*[:\-]\s*[""]?([^"\n|@]{3,80})'),
    re.compile(r'(?i)\bfor\s+(?!applying\b)[""]?([A-Za-z0-9/&,\-\s]{3,80})\s+\b(?:role|position)\b'),
    re.compile(r'(?i)\binterview\s+(?:for|with)\s+[""]?([A-Za-z0-9/&,\-\s]{3,80})'),
    re.compile(r'(?i)\byour application to\s+[""]?([A-Za-z0-9/&,\-\s]{3,80})'),
    re.compile(r'(?i)\bapplication (?:for|to)\s+[""]?([A-Za-z0-9/&,\-\s]{3,80})\b(?:at|with)\b'),
    re.compile(r'(?i)\bregarding (?:the )?[""]?([A-Za-z0-9/&,\-\s]{3,80})\s+\b(?:role|position)\b'),
    re.compile(r'(?i)\binterview invitation[:\-\s]+[""]?([A-Za-z0-9/&,\-\s]{3,80})'),
    re.compile(r'(?i)\b(?:job|position)\s*title\s*[:\-]\s*[""]?([^"\n|@]{3,80})'),
    re.compile(r'(?i)\byou(?:\'ve| have| ?) applied (?:for|to)\s+[""]?([A-Za-z0-9/&,\-\s]{3,80})'),
    re.compile(r'(?i)\b(?:the\s+)?([A-Za-z0-9/&,\-\s]{3,60})\s+(?:role|position)\s+at\b'),
    re.compile(r'(?i)\bapplication\s+(?:status|update)\s*[:\-]\s*[""]?([^"\n|@]{3,80})'),
    re.compile(r'(?i)\bopening\s+for\s+(?:a\s+)?[""]?([A-Za-z0-9/&,\-\s]{3,80})'),
    # "applying at/to Company - [reqid] Role" (e.g. CBRE confirmation subjects)
    re.compile(r'(?i)\bapplying (?:at|to|with)\s+[A-Za-z0-9& ]{1,40}\s*[-–]\s*\d*\s*([A-Za-z][A-Za-z0-9/&,\-\s]{2,79})'),
    # "Application Received/Submitted/Confirmation - Role" or "Application Update | reqid Role"
    re.compile(r'(?i)\bapplication (?:received|submitted|update|sent|confirmation)\s*[-–|]\s*(?:[A-Z]\d{3,}\s+)?([A-Za-z][A-Za-z0-9/&,\-\s]{2,79})'),
    # "job opportunity as/for Role"
    re.compile(r'(?i)\bjob opportunity (?:for|as|in)\s+(?:a\s+)?[""]?([A-Za-z0-9/&,\-\s]{3,80})'),
    # Req-ID prefix: "| R25345 Role Title" or "- R25345 Role Title"
    re.compile(r'(?i)[-|]\s*[A-Z]\d{4,}\s+([A-Za-z][A-Za-z0-9/&,\-\s]{3,80})'),
    # Phone/video screen subjects: "Company Phone Call - Role Title"
    re.compile(r'(?i)\b(?:phone|video|zoom)\s+(?:call|screen|interview)\s*[-–]\s*([A-Za-z][A-Za-z0-9/&,\-\s]{3,80})'),
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
GENERIC_NON_ROLE_PHRASES = {
    "your application",
    "application update",
    "next steps",
    "thank you",
    "job alert",
    "new roles",
    "opportunity update",
}
ROLE_HINT_WORDS = {
    "engineer",
    "developer",
    "analyst",
    "scientist",
    "manager",
    "director",
    "architect",
    "administrator",
    "consultant",
    "designer",
    "specialist",
    "coordinator",
    "associate",
    "intern",
    "officer",
    "lead",
    "principal",
    "recruiter",
    "technician",
    "writer",
    "editor",
    "accountant",
    "auditor",
    "strategist",
    "planner",
    "researcher",
    "operator",
    "representative",
    "agent",
    "advisor",
    "executive",
    "president",
    "vp",
    "cto",
    "cfo",
    "coo",
    "head",
    "support",
    "dev",
    "ops",
}


def _clean_role_candidate(text: str, company: str) -> str:
    role = (text or "").strip().strip("|:- ").strip('"').strip("'")
    role = re.sub(r"\s+", " ", role)
    # Strip trailing legal suffixes so they don't block the company-name suffix strip
    role = re.sub(r",\s*(?:Inc|LLC|Corp|Ltd)\.?\s*$", "", role, flags=re.I).strip()
    role = re.sub(r"\b(at|with|from)\s+[A-Z][\w&.\- ]{1,40}$", "", role, flags=re.I).strip()
    if company:
        role = re.sub(re.escape(company), "", role, flags=re.I).strip(" -,:")
    # Strip leading articles
    role = re.sub(r"(?i)^\s*(?:the|a|an)\s+", "", role).strip()
    # Strip trailing confirmation/noise suffixes
    role = re.sub(r"(?i)\s+(?:confirmation|scheduled|follow.up)\s*$", "", role).strip()
    if len(role) < 3 or len(role) > 80:
        return ""
    # Reject URL-encoded text
    if "%" in role and re.search(r"%[0-9A-Fa-f]{2}", role):
        return ""
    # Reject image/document file extensions
    if re.search(r"\.(png|jpg|gif|svg|webp|pdf|dtd|html|xml)\b", role, re.I):
        return ""
    # Reject HTML tags leaked from body parsing
    if re.search(r"<[a-z/][^>]*>", role, re.I):
        return ""
    # Reject tracking IDs or base64 (long token, no spaces, mixed case+digits)
    tokens = role.split()
    if len(tokens) <= 2 and any(len(t) > 20 and re.search(r"[0-9]", t) for t in tokens):
        return ""
    low = role.lower()
    if any(tok in low for tok in NOISY_ROLE_TOKENS):
        return ""
    if "http://" in low or "https://" in low:
        return ""
    if low in GENERIC_NON_ROLE_PHRASES:
        return ""
    # Avoid pure sentence fragments that aren't title-like.
    if re.search(r"\b(we|you|your|our|this|that)\b", low) and len(role.split()) > 6:
        return ""
    # Require at least one alphabetic word-like token.
    if not re.search(r"[a-zA-Z]{2,}", role):
        return ""
    # Stronger role-likeness check to avoid random snippets.
    role_words = set(re.findall(r"[a-zA-Z]+", low))
    if not (role_words & ROLE_HINT_WORDS):
        # fallback: accept short title-case-ish phrases (e.g. "Data Platform Engineer")
        if len(role.split()) > 5:
            return ""
    return role


def _clean_company_candidate(company: str) -> str:
    """Strip req IDs, leading articles, and trailing punctuation from a company candidate."""
    # Strip req ID / role suffixes: "CBRE - 263358 Transaction Analyst" → "CBRE"
    company = re.sub(r"\s*[-–]\s*\d[\w\-]*.*$", "", company).strip()
    company = company.strip(".,;:")
    first_word = company.split()[0].lower() if company.split() else ""
    if first_word in {"the", "our", "your", "a", "an", "this", "that", "we", "i", "my"}:
        return ""
    return company


def _extract_role_from_url(url: str, company: str) -> str:
    """
    Try deriving role from common job URL slug patterns.
    Example: /jobs/senior-data-analyst-12345
    """
    if not url:
        return ""
    path = re.sub(r"https?://[^/]+/", "", url)
    path = path.split("?", 1)[0].split("#", 1)[0]
    candidates = re.split(r"[/_]", path)
    best = ""
    for token in candidates:
        token = token.strip()
        if not token:
            continue
        # slug-like role token
        if "-" in token and re.search(r"[a-zA-Z]", token):
            cleaned = re.sub(r"-\d+$", "", token)
            cleaned = cleaned.replace("-", " ")
            cleaned = re.sub(r"\b(job|jobs|careers|position|opening|apply|details|view)\b", "", cleaned, flags=re.I).strip()
            c = _clean_role_candidate(cleaned.title(), company)
            if c and len(c) > len(best):
                best = c
    return best


def _extract_role(subject: str, body_lines: list[str], company: str) -> str:
    candidates: list[str] = []
    # Subject: try all patterns
    for pattern in ROLE_PATTERNS:
        for m in pattern.finditer(subject):
            candidates.append(m.group(1))
    # Body: try all patterns on first 80 lines (not just the structured "position: X" format)
    for ln in body_lines[:80]:
        for pattern in ROLE_PATTERNS:
            for m in pattern.finditer(ln):
                candidates.append(m.group(1))

    for c in candidates:
        cleaned = _clean_role_candidate(c, company)
        if cleaned:
            return cleaned
    return ""


def _company_from_ats_email(from_email: str, from_domain: str) -> str:
    """Extract company from ATS sender.

    - Local-part ATS (myworkday): company is the email username.
    - Subdomain ATS (trakstar, icims): company is the first meaningful subdomain label.
    """
    # Local-part ATS: zillow@myworkday.com → "Zillow"
    for ats in _ATS_LOCAL_PART_DOMAINS:
        if from_domain.endswith(ats):
            local = from_email.split("@")[0].strip().lower()
            if local and local not in _DOMAIN_NOISE_PREFIXES:
                return local.replace("-", " ").replace(".", " ").title()
    # Subdomain ATS: pvrea.hire.trakstar.com → "Pvrea"
    for ats in _ATS_SUBDOMAIN_DOMAINS:
        suffix = "." + ats
        if from_domain.endswith(suffix):
            prefix = from_domain[: -len(suffix)]
            labels = [l for l in prefix.split(".") if l and l not in {"hire", "jobs", "mail", "apply", "us"}]
            if labels:
                return labels[-1].replace("-", " ").title()
    return ""


def _company_from_sender_name(from_name: str) -> str:
    """Extract company from sender display name.

    Handles two formats:
    - "Person Name | Company Name" → returns "Company Name"
    - "Company Hiring Team" → strips recruiting noise words → "Company"
    """
    if not from_name:
        return ""
    name = from_name.strip('"\'').strip()
    # Reject display names that are actually email addresses
    if "@" in name:
        return ""
    # "Recruiter Name | Company Name" pattern
    if "|" in name:
        parts = [p.strip() for p in name.split("|")]
        candidate = parts[-1].strip()
        if len(candidate) > 2:
            return candidate
    # Strip trailing recruiting noise words
    words = name.split()
    while words and words[-1].lower().strip(".,\"'") in _SENDER_NOISE_WORDS:
        words.pop()
    if not words:
        return ""
    return " ".join(words).strip(".,\"'")


def _pick_job_url(urls: list[str]) -> str:
    """Return the first URL that looks like a job posting page."""
    for url in urls:
        path = url.split("?")[0].lower()
        if any(sig in path for sig in _JOB_URL_SIGNALS):
            return url
        if any(path.endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg", ".webp", ".pdf")):
            continue
    return ""


def _company_from_domain(domain: str) -> str:
    """Return a readable company name from an email sender domain.

    Strips TLD and infrastructure noise prefixes, then picks the longest
    remaining label as the most meaningful company identifier.
    e.g. "sap.hr.ext.seagate.com" → "Seagate"
    """
    if not domain:
        return ""
    labels = domain.lower().split(".")
    if len(labels) >= 2:
        labels = labels[:-1]  # strip TLD
    # Strip leading noise prefixes.
    while labels and labels[0] in _DOMAIN_NOISE_PREFIXES:
        labels = labels[1:]
    if not labels:
        return ""
    # Pick the longest label that isn't a known noise prefix.
    best = max(
        (l for l in labels if l not in _DOMAIN_NOISE_PREFIXES),
        key=len,
        default=labels[0],
    )
    return best.title()


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

    body_lines = [ln.strip() for ln in body.splitlines() if ln.strip()]

    # --- Company extraction (in priority order) ---

    # 1. Subject: "Company | Application..." format (Workday, Ashby)
    pipe_match = COMPANY_PIPE_RE.search(subject)
    if pipe_match:
        company = _clean_company_candidate(pipe_match.group(1).strip())

    # 2. Subject: "...at/with/from CompanyName"
    c_match = None
    if not company:
        c_match = COMPANY_SUBJECT_RE.search(subject)
        if c_match:
            company = _clean_company_candidate(c_match.group(2).strip())

    # 3. ATS email address extraction (local part or subdomain)
    _company_from_ats = False
    _company_from_subdomain = False
    if not company:
        ats_company = _company_from_ats_email(from_email, from_domain)
        if ats_company:
            company = ats_company
            _company_from_ats = True
            _company_from_subdomain = any(
                from_domain.endswith("." + ats) for ats in _ATS_SUBDOMAIN_DOMAINS
            )
    # Subdomain ATS often yields short abbreviations (e.g. "Pvrea") — prefer sender name if longer
    if _company_from_subdomain:
        sender_override = _company_from_sender_name(from_name)
        if sender_override and len(sender_override) > len(company):
            company = sender_override

    # 4. Body scan: run when company is still missing/noisy, or ATS domain with no local-part extraction
    _is_ats_domain = any(from_domain.endswith(ats) for ats in _ATS_SENDER_DOMAINS)
    needs_body_scan = (
        not company
        or company.lower() in _DOMAIN_NOISE_PREFIXES
        or len(company) <= 4
        or (_is_ats_domain and not pipe_match and not c_match and not _company_from_ats)
    )
    if needs_body_scan:
        for ln in body_lines[:30]:
            m = COMPANY_SUBJECT_RE.search(ln)
            if m:
                candidate = _clean_company_candidate(re.split(r"[.,!?;]", m.group(2))[0].strip())
                if len(candidate) > 2:
                    company = candidate
                    break

    # 5. Sender display name fallback ("Crusoe Hiring Team" → "Crusoe")
    #    then domain as last resort — nested so domain doesn't overwrite a good sender-name result
    if not company or company.lower() in _DOMAIN_NOISE_PREFIXES or len(company) <= 4:
        sender_company = _company_from_sender_name(from_name)
        if sender_company:
            company = sender_company
        else:
            company = _company_from_domain(from_domain)

    # --- Role, location, URL ---

    role = _extract_role(subject, body_lines, company)

    l_match = LOCATION_RE.search(subject + " " + body)
    if l_match:
        location = l_match.group(1).title().replace("-", "")

    found_urls = urls if urls is not None else URL_RE.findall(body)
    job_url = _pick_job_url(found_urls)
    if not role and job_url:
        role = _extract_role_from_url(job_url, company)

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
