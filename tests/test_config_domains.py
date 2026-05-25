from exchange_mcp.config import Settings


def test_accepted_email_domains_from_env_string():
    settings = Settings(
        exchange_host="mail.example.com",
        exchange_user="user",
        exchange_password="secret",
        mcp_api_key="key",
        exchange_email="org@fin-frame.ru",
        org_accepted_domains="fin-frame.ru,inplatlabs.ru,instant-pay.ru",
    )
    assert settings.accepted_email_domains == [
        "fin-frame.ru",
        "inplatlabs.ru",
        "instant-pay.ru",
    ]


def test_accepted_email_domains_fallback_to_organizer():
    settings = Settings(
        exchange_host="mail.example.com",
        exchange_user="user",
        exchange_password="secret",
        mcp_api_key="key",
        exchange_email="org@fin-frame.ru",
        org_accepted_domains="",
    )
    assert settings.accepted_email_domains == ["fin-frame.ru"]
