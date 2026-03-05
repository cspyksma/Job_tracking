from extraction.extract_fields import extract_fields


def test_extract_role_from_structured_subject():
    msg = {
        "subject": "Interview scheduling for Senior Data Analyst role at Acme",
        "body": "Please share availability.",
        "from_domain": "acme.com",
        "from_name": "Recruiter",
        "from_email": "recruiter@acme.com",
    }
    out = extract_fields(msg, req_id="")
    assert "Data Analyst" in out.role


def test_noisy_subject_does_not_become_role():
    msg = {
        "subject": "Limited time offer - save 50% on your subscription",
        "body": "Unsubscribe anytime.",
        "from_domain": "promo-mail.com",
        "from_name": "Promo",
        "from_email": "news@promo-mail.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.role == ""
