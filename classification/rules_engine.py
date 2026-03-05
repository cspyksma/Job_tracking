from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_TYPES = {
    "Opportunity",
    "ApplicationConfirmation",
    "InterviewRequest",
    "Rejection",
    "Offer",
    "Other",
    "Ad",
}


@dataclass
class ClassificationResult:
    detected_type: str
    confidence: float
    matched_by: str
    score: int
    signals: list[str] = field(default_factory=list)


class RulesEngine:
    def __init__(self, rules_path: str, config: dict[str, Any]) -> None:
        self.rules_path = Path(rules_path)
        self.config = config
        self.rules = self._load_rules()
        self.enable_llm_fallback = bool(self.config.get("classification", {}).get("enable_llm_fallback", False))

    def _load_rules(self) -> dict[str, Any]:
        with self.rules_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if "types" not in self.rules:
            errors.append("rules.yml missing 'types'")
        else:
            for t, body in self.rules["types"].items():
                if t not in SUPPORTED_TYPES:
                    errors.append(f"unsupported type in rules: {t}")
                if "keywords" not in body:
                    errors.append(f"type {t} missing keywords")
                if "score" not in body:
                    errors.append(f"type {t} missing score")
        return len(errors) == 0, errors

    def classify(self, subject: str, body: str, from_domain: str) -> ClassificationResult:
        text = f"{subject}\n{body}".lower()
        min_score = int(self.config.get("classification", {}).get("min_confident_score", 5))
        signals: list[str] = []

        scores: dict[str, int] = {}
        for type_name, rule in self.rules.get("types", {}).items():
            score = 0
            if type_name == "Ad":
                for kw in rule.get("keywords", []):
                    if kw.lower() in text:
                        score += int(rule.get("score", 1))
                        signals.append(f"ad_kw:{kw}")
                for dom in self.rules.get("domain_hints", {}).get("ad", []):
                    if dom.lower() in from_domain.lower():
                        score += 3
                        signals.append(f"ad_dom:{dom}")
                        break
            else:
                for kw in rule.get("keywords", []):
                    if kw.lower() in text:
                        score += int(rule.get("score", 1))
                        signals.append(f"{type_name}:kw:{kw}")
            scores[type_name] = score

        # ATS senders strongly indicate application lifecycle.
        for dom in self.rules.get("domain_hints", {}).get("ats", []):
            if from_domain.endswith(dom.lower()):
                scores["ApplicationConfirmation"] = scores.get("ApplicationConfirmation", 0) + 5
                signals.append(f"ats_domain:{dom}")
                break

        best_type = "Other"
        best_score = 0
        for t, s in scores.items():
            if s > best_score:
                best_type = t
                best_score = s

        # Guardrail: "Offer" is overloaded in marketing email.
        # Only keep Offer if at least one strict offer regex or multiple offer-like signals exist.
        if best_type == "Offer":
            strict_offer_hits = 0
            for rx in self.rules.get("regex", {}).get("offer_strict", []):
                if re.search(rx, text):
                    strict_offer_hits += 1
            offer_signal_count = sum(1 for s in signals if s.startswith("Offer:kw:"))
            if strict_offer_hits == 0 and offer_signal_count < 2:
                # Fall back to Other unless another lifecycle type is strong.
                alt_types = {k: v for k, v in scores.items() if k != "Offer"}
                alt_best_type = max(alt_types, key=alt_types.get) if alt_types else "Other"
                alt_best_score = alt_types.get(alt_best_type, 0)
                if alt_best_score >= min_score:
                    best_type = alt_best_type
                    best_score = alt_best_score
                    signals.append("offer_guardrail:fallback_to_alt")
                else:
                    best_type = "Other"
                    best_score = 0
                    signals.append("offer_guardrail:fallback_to_other")

        if best_type == "Ad" and best_score >= 4:
            return ClassificationResult("Ad", 0.9, "rule:ad_filter", best_score, signals)

        if best_score < min_score:
            # Keep optional fallback hook disabled by default.
            if self.enable_llm_fallback:
                from classification.llm_fallback import classify_with_llm  # local import by design

                llm_out = classify_with_llm(subject=subject, body=body, sender_domain=from_domain)
                if llm_out:
                    return llm_out
            return ClassificationResult("Other", 0.35, "rule:low_score", best_score, signals)

        conf = min(0.99, 0.45 + (best_score / 20.0))
        return ClassificationResult(best_type, conf, f"rule:{best_type}", best_score, signals)

    def extract_req_id(self, text: str) -> str:
        for rx in self.rules.get("regex", {}).get("req_id", []):
            m = re.search(rx, text)
            if m:
                return m.group(3).strip()
        return ""

    def extract_urls(self, text: str) -> list[str]:
        urls: list[str] = []
        for rx in self.rules.get("regex", {}).get("url", []):
            urls.extend(re.findall(rx, text))
        # Preserve order, remove duplicates.
        out: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out
