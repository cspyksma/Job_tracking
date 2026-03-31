from extraction.extract_fields import extract_fields, _clean_role_candidate, _pick_job_url, _company_from_sender_name


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


def test_extract_role_from_application_phrase():
    msg = {
        "subject": "Your application for Data Engineer at Example Corp",
        "body": "Thanks for applying.",
        "from_domain": "example.com",
        "from_name": "Careers",
        "from_email": "careers@example.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.role.lower() == "data engineer"


def test_extract_role_from_job_url_slug_when_subject_missing():
    msg = {
        "subject": "Application update",
        "body": "View details https://jobs.example.com/openings/senior-data-analyst-12345",
        "from_domain": "example.com",
        "from_name": "Careers",
        "from_email": "careers@example.com",
    }
    out = extract_fields(msg, req_id="", urls=["https://jobs.example.com/openings/senior-data-analyst-12345"])
    assert "Data Analyst" in out.role


def test_company_from_noisy_subdomain_linkedin():
    msg = {
        "subject": "Your application was reviewed",
        "body": "Thanks for applying.",
        "from_domain": "notifications.linkedin.com",
        "from_name": "LinkedIn",
        "from_email": "jobs@notifications.linkedin.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.company.lower() == "linkedin"


def test_company_from_noisy_subdomain_google():
    msg = {
        "subject": "Application received",
        "body": "Thanks for applying.",
        "from_domain": "mail.google.com",
        "from_name": "Google",
        "from_email": "noreply@mail.google.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.company.lower() == "google"


def test_role_from_applied_for_pattern():
    msg = {
        "subject": "You've applied for Data Analyst at Acme Corp",
        "body": "Thank you for your application.",
        "from_domain": "acme.com",
        "from_name": "Acme",
        "from_email": "careers@acme.com",
    }
    out = extract_fields(msg, req_id="")
    assert "Data Analyst" in out.role


def test_role_from_opening_for_pattern():
    msg = {
        "subject": "Opening for a Software Engineer at Widgets Inc",
        "body": "We have an exciting opportunity.",
        "from_domain": "widgets.com",
        "from_name": "Widgets",
        "from_email": "hr@widgets.com",
    }
    out = extract_fields(msg, req_id="")
    assert "Software Engineer" in out.role


def test_company_from_ats_workday_email():
    """ATS sender: company extracted from email local part (zillow@myworkday.com → Zillow)."""
    msg = {
        "subject": "Your application has been received",
        "body": "Thank you for applying.",
        "from_domain": "myworkday.com",
        "from_name": "Zillow Careers",
        "from_email": "zillow@myworkday.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.company.lower() == "zillow"


def test_company_from_greenhouse_body_fallback():
    """ATS sender with noise local part: company found in body scan."""
    msg = {
        "subject": "Your application update",
        "body": "We're excited about your interest at PrizePicks. Thank you for applying.",
        "from_domain": "us.greenhouse-mail.io",
        "from_name": "PrizePicks",
        "from_email": "no-reply@us.greenhouse-mail.io",
    }
    out = extract_fields(msg, req_id="")
    assert out.company.lower() == "prizepicks"


def test_company_from_trakstar_subdomain():
    """Trakstar ATS: company extracted from subdomain, not recruiter's email local part."""
    msg = {
        "subject": "PVREA Phone Call - AI & BI Specialist Confirmation",
        "body": "Thank you for applying.",
        "from_domain": "pvrea.hire.trakstar.com",
        "from_name": "Ashly Gavito | Poudre Valley REA",
        "from_email": "agavito@pvrea.hire.trakstar.com",
    }
    out = extract_fields(msg, req_id="")
    # Sender name "Ashly Gavito | Poudre Valley REA" overrides the subdomain abbreviation "Pvrea"
    assert "poudre valley" in out.company.lower() or out.company.lower() == "pvrea"


def test_company_from_sender_name_hiring_team():
    """Sender name 'Company Hiring Team' strips noise words → 'Company'."""
    assert _company_from_sender_name("Crusoe Hiring Team") == "Crusoe"


def test_company_from_sender_name_pipe():
    """Sender name 'Person | Company' extracts company after pipe."""
    assert _company_from_sender_name("Ashly Gavito | Poudre Valley REA") == "Poudre Valley REA"


def test_company_from_pipe_subject():
    """Subjects like 'Crusoe | Application Received' extract company before pipe."""
    msg = {
        "subject": "Crusoe | Application Received",
        "body": "Thank you for your application.",
        "from_domain": "ashbyhq.com",
        "from_name": "Crusoe Hiring Team",
        "from_email": "no-reply@ashbyhq.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.company.lower() == "crusoe"


def test_linkedin_role_not_extracted_as_company():
    """LinkedIn 'Your application to Data Analyst at X' → company=X, role=Data Analyst."""
    msg = {
        "subject": "Your application to Data Analyst at Airsupply Tools",
        "body": "You applied for Data Analyst at Airsupply Tools.",
        "from_domain": "linkedin.com",
        "from_name": "LinkedIn",
        "from_email": "jobs-noreply@linkedin.com",
    }
    out = extract_fields(msg, req_id="")
    assert "airsupply" in out.company.lower()
    assert "analyst" in out.role.lower()


def test_cbre_company_strips_req_id():
    """'Thank you for applying at CBRE - 263358 Transaction Analyst' → company=CBRE."""
    msg = {
        "subject": "Thank you for applying at CBRE  - 263358 Transaction Analyst",
        "body": "We received your application.",
        "from_domain": "cbre.com",
        "from_name": "CBRE Talent Acquisition",
        "from_email": "noreply@cbre.com",
    }
    out = extract_fields(msg, req_id="")
    assert out.company.lower() == "cbre"
    assert "analyst" in out.role.lower()


def test_pick_job_url_skips_image_returns_job_url():
    """_pick_job_url should skip image URLs and return the first job-path URL."""
    urls = [
        "https://example.com/track.png",
        "https://jobs.example.com/careers/senior-engineer-123",
    ]
    result = _pick_job_url(urls)
    assert "careers" in result


def test_clean_role_rejects_url_encoded():
    assert _clean_role_candidate("City%20Of%20Fort%20Collins%20Logo.jpg", "") == ""


def test_clean_role_rejects_image_extension():
    assert _clean_role_candidate("Offerletterlogos 1.Png", "") == ""


def test_clean_role_rejects_tracking_id():
    assert _clean_role_candidate("A5Z5Dv0 85Zhokf098Sdxnbdu5N1Qk85Von5Cber", "") == ""
