from classification.rules_engine import RulesEngine


CFG = {"classification": {"min_confident_score": 3, "enable_llm_fallback": False}}


def test_interview_request_subject():
    engine = RulesEngine("classification/rules.yml", CFG)
    out = engine.classify("Interview scheduling for Software Engineer role", "Please share availability", "recruiter@company.com")
    assert out.detected_type == "InterviewRequest"


def test_rejection_subject():
    engine = RulesEngine("classification/rules.yml", CFG)
    out = engine.classify("Update on your application", "Unfortunately, we are moving forward with other candidates.", "careers@company.com")
    assert out.detected_type == "Rejection"


def test_marketing_offer_not_job_offer():
    engine = RulesEngine("classification/rules.yml", CFG)
    out = engine.classify(
        "Limited time offer - save 50%",
        "Use promo code and unsubscribe anytime.",
        "news@promo-mail.com",
    )
    assert out.detected_type in {"Ad", "Other"}


def test_real_job_offer_detected():
    engine = RulesEngine("classification/rules.yml", CFG)
    out = engine.classify(
        "We are pleased to offer you the Software Engineer role",
        "Attached is your offer letter with compensation package and start date.",
        "careers@company.com",
    )
    assert out.detected_type == "Offer"


def test_future_maybe_interview_is_not_interview_request():
    engine = RulesEngine("classification/rules.yml", CFG)
    out = engine.classify(
        "Application update",
        "If selected, you may be invited to interview in a future round.",
        "careers@company.com",
    )
    assert out.detected_type != "InterviewRequest"


def test_interview_with_scheduling_language_stays_interview_request():
    engine = RulesEngine("classification/rules.yml", CFG)
    out = engine.classify(
        "Let's schedule an interview",
        "Please share your availability this week.",
        "recruiter@company.com",
    )
    assert out.detected_type == "InterviewRequest"
