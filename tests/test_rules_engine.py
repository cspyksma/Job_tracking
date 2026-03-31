from classification.rules_engine import RulesEngine


CFG = {
    "classification": {
        "min_confident_score": 3,
        "enable_llm_fallback": False,
    }
}


def test_classifies_confirmation():
    engine = RulesEngine("classification/rules.yml", CFG)
    result = engine.classify(
        "Thank you for applying to Example Corp",
        "We received your application",
        "myworkday.workday.com",
    )
    assert result.detected_type == "ApplicationConfirmation"
    assert result.confidence > 0.55


def test_extract_req_id():
    engine = RulesEngine("classification/rules.yml", CFG)
    req = engine.extract_req_id("Application received for Job #ABC-1234")
    assert req == "ABC-1234"


def test_extract_req_id_not_required_false_positive():
    engine = RulesEngine("classification/rules.yml", CFG)
    req = engine.extract_req_id("Skills required: Python and SQL")
    assert req == ""


def test_extract_urls():
    engine = RulesEngine("classification/rules.yml", CFG)
    urls = engine.extract_urls("Please apply here: https://example.com/jobs/123 and review https://example.com/about")
    assert urls[0] == "https://example.com/jobs/123"


def test_not_job_guardrail_credit_alert():
    """Capital One credit score email with 'unfortunately' must not become a Rejection."""
    engine = RulesEngine("classification/rules.yml", CFG)
    result = engine.classify(
        "Your credit score update",
        "Unfortunately your credit score has changed. Review your account balance now.",
        "notification.capitalone.com",
    )
    assert result.detected_type == "Other"
    assert any("not_job_guardrail" in s for s in result.signals)


def test_not_job_guardrail_product_marketing():
    """Apple product marketing with scheduling language must not become an InterviewRequest."""
    engine = RulesEngine("classification/rules.yml", CFG)
    result = engine.classify(
        "Schedule your availability to see the new iPhone",
        "New features and product update available. Download the iOS app now.",
        "insideapple.apple.com",
    )
    assert result.detected_type == "Other"


def test_not_job_guardrail_passes_real_rejection():
    """Real rejection email with 'unfortunately' and personal job signal must stay Rejection."""
    engine = RulesEngine("classification/rules.yml", CFG)
    result = engine.classify(
        "Update on your application",
        "Unfortunately we won't be moving forward with your application at this time.",
        "mail.greenhouse.io",
    )
    assert result.detected_type == "Rejection"


def test_not_job_guardrail_ats_domain_bypasses_check():
    """ATS sender domain bypasses the guardrail even without personal job signals."""
    engine = RulesEngine("classification/rules.yml", CFG)
    result = engine.classify(
        "Application update",
        "We regret to inform you that the position has been filled.",
        "mail.myworkdayjobs.com",
    )
    assert result.detected_type == "Rejection"


def test_cbre_application_confirmation_not_interview():
    """'We will reach out to schedule an interview' is conditional — must be ApplicationConfirmation not InterviewRequest."""
    engine = RulesEngine("classification/rules.yml", CFG)
    body = (
        "Thank you for applying to the Transaction Analyst role. We have successfully received "
        "your application and it is currently under review. If your qualifications prove to be "
        "a match, we will reach out to you to schedule an interview. We may invite you to some "
        "or all of the below recruitment stages. A screening interview. Face-to-face interview "
        "or Zoom Call."
    )
    result = engine.classify(
        "Thank you for applying at CBRE - 263358 Transaction Analyst",
        body,
        "cbre.com",
    )
    assert result.detected_type != "InterviewRequest", f"Got {result.detected_type} — conditional scheduling language should not classify as InterviewRequest"


def test_pvrea_confirmation_stays_interview():
    """'Confirming your availability' for an already-scheduled call must stay InterviewRequest."""
    engine = RulesEngine("classification/rules.yml", CFG)
    body = (
        "Hello Cole, Thank you for confirming your availability! "
        "This email serves as a confirmation of your phone call scheduled with Poudre Valley REA."
    )
    result = engine.classify(
        "PVREA Phone Call - AI & BI Specialist Confirmation",
        body,
        "pvrea.hire.trakstar.com",
    )
    assert result.detected_type == "InterviewRequest"
