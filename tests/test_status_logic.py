from datetime import datetime, timezone

from state_machine.status_logic import compute_follow_up_due, next_status


def test_no_downgrade_from_interview_to_applied():
    status = next_status("Interview", "ApplicationConfirmation", 0.9, 0.55)
    assert status == "Interview"


def test_offer_wins():
    status = next_status("Rejected", "Offer", 0.9, 0.55)
    assert status == "Offer"


def test_follow_up_due_computation():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    due = compute_follow_up_due("Applied", base, {"Applied": 10})
    assert due is not None
    assert due.day == 11
