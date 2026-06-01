from app.schemas.auth import BootstrapCompanyRequest


def test_bootstrap_schema_accepts_company_only():
    payload = BootstrapCompanyRequest(
        company_name="Attendio Demo",
        owner_first_name="Owner",
        owner_last_name="Admin",
        owner_email="owner@example.com",
        owner_password="Admin@12345"
    )
    assert payload.company_name == "Attendio Demo"
