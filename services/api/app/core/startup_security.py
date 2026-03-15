from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.core.settings import Settings, get_settings


def is_prod_env(app_env: str | None) -> bool:
    return str(app_env or "").strip().lower() in {"prod", "production"}


def _is_default_like_secret(value: str | None) -> bool:
    v = str(value or "").strip().lower()
    return (not v) or v.startswith("change-me")


def _parse_iso_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_valid_https_url(value: str | None) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        split = urlsplit(raw)
    except Exception:  # noqa: BLE001
        return False
    if str(split.scheme or "").lower() != "https":
        return False
    if not str(split.netloc or "").strip():
        return False
    return True


def _check_rotation_field(*, field_name: str, raw_value: str | None, max_age_days: int, now: datetime, issues: list[str]) -> None:
    dt = _parse_iso_dt(raw_value)
    if dt is None:
        issues.append(f"{field_name}_missing_or_invalid_in_prod")
        return

    age_days = (now - dt).days
    if age_days > int(max_age_days):
        issues.append(f"{field_name}_too_old_in_prod")


def collect_startup_security_issues(settings: Settings) -> list[str]:
    if not is_prod_env(settings.app_env):
        return []

    issues: list[str] = []
    now = datetime.now(timezone.utc)

    if settings.auth_dev_token_enabled:
        issues.append("auth_dev_token_enabled_must_be_false_in_prod")

    if _is_default_like_secret(settings.jwt_secret):
        issues.append("jwt_secret_default_in_prod")

    if _is_default_like_secret(settings.storage_grant_secret):
        issues.append("storage_grant_secret_default_in_prod")

    if _is_default_like_secret(settings.guard_bot_signing_master_secret):
        issues.append("guard_bot_signing_master_secret_default_in_prod")
    if not bool(settings.superadmin_step_up_enabled):
        issues.append("superadmin_step_up_must_be_enabled_in_prod")

    if _is_default_like_secret(settings.superadmin_step_up_totp_secret):
        issues.append("superadmin_step_up_totp_secret_missing_in_prod")

    if not bool(settings.guard_bot_signature_required):
        issues.append("guard_bot_signature_required_must_be_true_in_prod")

    if int(settings.jwt_secret_version) < 1:
        issues.append("jwt_secret_version_invalid_in_prod")
    if int(settings.storage_grant_secret_version) < 1:
        issues.append("storage_grant_secret_version_invalid_in_prod")
    if int(settings.guard_bot_signing_master_secret_version) < 1:
        issues.append("guard_bot_signing_master_secret_version_invalid_in_prod")

    origins = settings.cors_origins_list()
    if not origins:
        issues.append("cors_allow_origins_empty_in_prod")
    elif "*" in origins:
        issues.append("cors_allow_origins_wildcard_forbidden_in_prod")

    _check_rotation_field(
        field_name="jwt_secret_rotated_at",
        raw_value=settings.jwt_secret_rotated_at,
        max_age_days=int(settings.secret_rotation_max_age_days),
        now=now,
        issues=issues,
    )
    _check_rotation_field(
        field_name="storage_grant_secret_rotated_at",
        raw_value=settings.storage_grant_secret_rotated_at,
        max_age_days=int(settings.secret_rotation_max_age_days),
        now=now,
        issues=issues,
    )
    _check_rotation_field(
        field_name="guard_bot_signing_master_secret_rotated_at",
        raw_value=settings.guard_bot_signing_master_secret_rotated_at,
        max_age_days=int(settings.secret_rotation_max_age_days),
        now=now,
        issues=issues,
    )

    mode = str(settings.security_alerts_delivery_mode or "").strip().upper() or "LOG_ONLY"
    if mode not in {"LOG_ONLY", "WEBHOOK"}:
        issues.append("security_alerts_delivery_mode_invalid_in_prod")
    if mode == "WEBHOOK":
        webhook = str(settings.security_alert_webhook_url or "").strip()
        if not webhook:
            issues.append("security_alert_webhook_url_required_for_webhook_mode_in_prod")
        elif not _is_valid_https_url(webhook):
            issues.append("security_alert_webhook_url_must_be_https_in_prod")

    return issues


def enforce_startup_security(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    issues = collect_startup_security_issues(s)
    if issues and bool(s.security_enforce_prod_checks):
        raise RuntimeError("production_security_guardrails_failed: " + ";".join(issues))