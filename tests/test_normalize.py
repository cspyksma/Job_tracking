from extraction.normalize import normalize_company, normalize_role


def test_normalize_company_suffixes():
    assert normalize_company("Meta Platforms, Inc.") == "meta platforms"


def test_normalize_role_seniority():
    assert normalize_role("Senior Software Engineer III") == "software engineer"
