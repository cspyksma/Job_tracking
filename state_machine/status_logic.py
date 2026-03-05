from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


PRECEDENCE = {
    "Offer": 6,
    "Rejected": 5,
    "Interview": 4,
    "Applied": 3,
    "Opportunity": 2,
    "NeedsReview": 1,
    "Closed": 0,
}

TYPE_TO_STATUS = {
    "ApplicationConfirmation": "Applied",
    "InterviewRequest": "Interview",
    "Rejection": "Rejected",
    "Offer": "Offer",
    "Opportunity": "Opportunity",
}


def next_status(current: Optional[str], detected_type: str, confidence: float, threshold: float) -> str:
    target = TYPE_TO_STATUS.get(detected_type, "NeedsReview" if confidence < threshold else "Opportunity")
    if not current:
        return target
    if PRECEDENCE.get(target, 0) > PRECEDENCE.get(current, 0):
        return target
    return current


def compute_follow_up_due(status: str, status_date: datetime, follow_up_days: dict[str, int]) -> Optional[datetime]:
    if status not in follow_up_days:
        return None
    return status_date + timedelta(days=int(follow_up_days[status]))
