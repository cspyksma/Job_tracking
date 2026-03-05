from __future__ import annotations

import re


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
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", (name or "").lower()).strip()
    tokens = [t for t in text.split() if t and t not in COMPANY_SUFFIXES]
    return " ".join(tokens)


def normalize_role(role: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", (role or "").lower()).strip()
    tokens = [t for t in text.split() if t and t not in SENIORITY_TOKENS]
    return " ".join(tokens)


def normalize_subject_for_thread(subject: str) -> str:
    text = (subject or "").strip().lower()
    text = re.sub(r"^(re|fw|fwd)\s*:\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()
