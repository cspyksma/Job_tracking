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


def test_extract_urls():
    engine = RulesEngine("classification/rules.yml", CFG)
    urls = engine.extract_urls("Please apply here: https://example.com/jobs/123 and review https://example.com/about")
    assert urls[0] == "https://example.com/jobs/123"
