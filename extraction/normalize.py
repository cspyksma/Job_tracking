from __future__ import annotations

import re


_NONALNUM_RE = re.compile(r"[^a-zA-Z0-9\s]")
_SUBJECT_PREFIX_RE = re.compile(r"^(re|fw|fwd)\s*:\s*")
_WHITESPACE_RE = re.compile(r"\s+")

COMPANY_SUFFIXES = {
    "inc",
    "inc.",
    "llc",
    "l.l.c",
    "ltd",
    "ltd.",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "plc",
    "gmbh",
    "sa",
}

SENIORITY_TOKENS = {"sr", "senior", "jr", "junior", "ii", "iii", "iv", "lead", "principal"}


def normalize_company(name: str) -> str:
    text = _NONALNUM_RE.sub(" ", (name or "").lower()).strip()
    tokens = [t for t in text.split() if t and t not in COMPANY_SUFFIXES]
    return " ".join(tokens)


def normalize_role(role: str) -> str:
    text = _NONALNUM_RE.sub(" ", (role or "").lower()).strip()
    tokens = [t for t in text.split() if t and t not in SENIORITY_TOKENS]
    return " ".join(tokens)


def normalize_subject_for_thread(subject: str) -> str:
    text = _SUBJECT_PREFIX_RE.sub("", (subject or "").strip().lower())
    return _WHITESPACE_RE.sub(" ", text).strip()
