from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional

from storage.db import JobTrackerDB


@dataclass
class MatchResult:
    record_id: str
    confidence: float
    matched_by: str
    created_new: bool
    ambiguous: bool = False
    ambiguity_reason: str = ""


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def build_record_id(company_norm: str, role_norm: str, req_id: str, first_seen: datetime) -> str:
    if req_id:
        raw = f"{company_norm}|{req_id}"
    else:
        raw = f"{company_norm}|{role_norm}|{first_seen.date().isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class Matcher:
    def __init__(self, db: JobTrackerDB, cfg: dict):
        self.db = db
        m = cfg.get("matching", {})
        self.high = float(m.get("fuzzy_high_threshold", 0.84))
        self.low = float(m.get("fuzzy_low_threshold", 0.65))

    def match_or_create(
        self,
        company_norm: str,
        company_domain: str,
        role_norm: str,
        req_id: str,
        thread_hint: str,
        first_seen: datetime,
    ) -> MatchResult:
        if req_id and company_norm:
            row = self.db.get_application_by_req(company_norm, req_id)
            if row:
                return MatchResult(row["record_id"], 0.97, "strong:req_id", False)

        if thread_hint:
            row = self.db.get_application_by_thread_hint(thread_hint)
            if row:
                return MatchResult(row["record_id"], 0.9, "thread_hint", False)

        best_id: Optional[str] = None
        best_score = 0.0
        second_best = 0.0
        for row in self.db.find_candidates(company_norm, role_norm, company_domain):
            c = _ratio(company_norm, row["company_norm"] or "")
            r = _ratio(role_norm, row["role_norm"] or "")
            d = 1.0 if company_domain and (row["company_domain"] or "") == company_domain else 0.0
            score = (0.45 * c) + (0.45 * r) + (0.10 * d)
            if score > best_score:
                second_best = best_score
                best_score = score
                best_id = row["record_id"]
            elif score > second_best:
                second_best = score

        if best_id and best_score >= self.high:
            return MatchResult(best_id, round(best_score, 2), "fuzzy_high", False)

        record_id = build_record_id(company_norm, role_norm, req_id, first_seen)
        if best_score >= self.low and (best_score - second_best) < 0.05:
            return MatchResult(
                record_id,
                round(best_score, 2),
                "ambiguous_fuzzy_new",
                True,
                ambiguous=True,
                ambiguity_reason=f"multiple candidates score delta {best_score-second_best:.2f}",
            )
        if best_score >= self.low:
            return MatchResult(record_id, round(best_score, 2), "fuzzy_ambiguous_new", True)
        return MatchResult(record_id, max(0.5, round(best_score, 2)), "new_record", True)
