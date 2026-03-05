from __future__ import annotations

from typing import Optional

from classification.rules_engine import ClassificationResult


def classify_with_llm(subject: str, body: str, sender_domain: str) -> Optional[ClassificationResult]:
    """
    Optional extension point for future LLM fallback.
    This hook is intentionally disabled by default and returns None.
    """
    _ = (subject, body, sender_domain)
    return None
