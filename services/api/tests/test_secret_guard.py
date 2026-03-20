from __future__ import annotations

from scripts.secret_guard import _is_forbidden_env_file, _scan_text


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_scan_text_flags_hardcoded_dsn_credentials() -> None:
    findings = _scan_text(
        "app/example.py",
        'DATABASE_URL = "postgresql://user:pass@127.0.0.1:5432/appdb"',
    )
    assert "hardcoded_dsn_credentials" in _codes(findings)


def test_scan_text_flags_non_official_vies_url_assignment() -> None:
    findings = _scan_text(
        "app/core/settings.py",
        'entity_verification_vies_wsdl_url = "https://evil.example/wsdl"',
    )
    assert "non_official_public_service_url_assignment" in _codes(findings)


def test_scan_text_accepts_official_vies_url_assignment() -> None:
    findings = _scan_text(
        "app/core/settings.py",
        'entity_verification_vies_wsdl_url = "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"',
    )
    assert "non_official_public_service_url_assignment" not in _codes(findings)


def test_scan_text_flags_dotenv_secret_value() -> None:
    findings = _scan_text(
        ".env",
        "JWT_SECRET=2f4b0d1bc9558f60a7f1472d30c9f6a4\n",
    )
    assert "dotenv_secret_value" in _codes(findings)


def test_scan_text_allows_placeholder_marker() -> None:
    findings = _scan_text(
        ".env.example",
        "JWT_SECRET=change-me\n",
    )
    assert "dotenv_secret_value" not in _codes(findings)


def test_scan_text_does_not_treat_ttl_as_secret() -> None:
    findings = _scan_text(
        ".env.example",
        "ACCESS_TOKEN_TTL_SECONDS=900\n",
    )
    assert "dotenv_secret_value" not in _codes(findings)


def test_forbidden_env_file_policy() -> None:
    assert _is_forbidden_env_file(".env") is True
    assert _is_forbidden_env_file("services/api/.env.local") is True
    assert _is_forbidden_env_file(".env.example") is False
