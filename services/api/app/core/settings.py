from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "mydata-api"
    jwt_issuer: str = "mydata-auth"
    access_token_ttl_seconds: int = 900

    # Auth hardening
    auth_dev_token_enabled: bool = False
    api_docs_enabled_in_prod: bool = False
    auth_password_min_length: int = 12
    auth_password_max_age_days: int = 180

    # CORS
    cors_allow_origins: str = ""
    cors_allow_credentials: bool = False

    # Prod startup guardrails
    security_enforce_prod_checks: bool = True

    # Secret rotation policy
    secret_rotation_max_age_days: int = 90
    jwt_secret_rotated_at: str | None = None
    storage_grant_secret_rotated_at: str | None = None
    guard_bot_signing_master_secret_rotated_at: str | None = None

    # Secret versioning
    jwt_secret_version: int = 1
    storage_grant_secret_version: int = 1
    guard_bot_signing_master_secret_version: int = 1

    # Superadmin step-up MFA (TOTP)
    superadmin_step_up_enabled: bool = False
    superadmin_step_up_header: str = "X-Step-Up-Code"
    superadmin_step_up_totp_secret: str = ""
    superadmin_step_up_period_seconds: int = 30
    superadmin_step_up_window_steps: int = 1

    # Security alert pipeline
    security_alerts_enabled: bool = True
    security_alerts_delivery_mode: str = "LOG_ONLY"  # LOG_ONLY / WEBHOOK
    security_alert_webhook_url: str = ""
    security_alert_min_severity: str = "HIGH"
    security_alert_dispatch_batch_size: int = 200
    security_alert_retry_max_attempts: int = 8
    security_alert_retry_base_seconds: int = 30
    security_alert_retry_max_seconds: int = 3600

    # Support gate/session controls
    support_door_open_default_minutes: int = 30
    support_door_open_max_minutes: int = 240
    support_session_ttl_minutes: int = 60
    support_session_ttl_max_minutes: int = 480
    support_token_ttl_seconds: int = 900
    support_chat_max_message_chars: int = 8000
    support_messages_list_limit_max: int = 500

    request_id_header: str = "X-Request-ID"
    sensitive_rate_limit_per_minute: int = 40
    sensitive_get_rate_limit_per_minute: int = 600
    redis_rate_limit_enabled: bool = True
    redis_url: str = ""
    redis_key_prefix: str = "mydata"

    # Core entitlement middleware cache
    core_entitlement_cache_ttl_seconds: int = 15
    core_entitlement_cache_max_entries: int = 20000
    api_list_limit_max: int = 500

    # API runtime load protection
    api_max_in_flight_requests: int = 250
    api_queue_wait_timeout_ms: int = 90000
    api_request_timeout_seconds: int = 120
    api_max_queue_waiters: int = 2000
    api_overload_retry_after_seconds: int = 2
    api_runtime_metrics_window_size: int = 2048
    api_runtime_slow_request_ms: int = 1500
    api_runtime_timing_headers_enabled: bool = False
    api_startup_routes_print_enabled: bool = False
    api_startup_routes_print_max: int = 2000

    # Temporary performance profiling seam (explicitly gated)
    perf_profiling_enabled: bool = False
    perf_profiling_methods: str = "GET"
    perf_profiling_path_prefixes: str = "/orders"
    perf_profiling_window_size: int = 4096
    # Entity verification provider runtime controls
    entity_verification_vies_enabled: bool = False
    entity_verification_vies_wsdl_url: str = "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"
    entity_verification_vies_service_url: str = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
    entity_verification_vies_connect_timeout_seconds: int = 2
    entity_verification_vies_read_timeout_seconds: int = 4
    entity_verification_vies_total_budget_seconds: int = 7
    entity_verification_vies_retry_count: int = 1
    entity_verification_vies_retry_backoff_ms: int = 300
    entity_verification_vies_cooldown_seconds: int = 60
    # Authz fast path (tenant DB effective permissions)
    authz_tenant_db_fast_path_enabled: bool = False
    authz_tenant_db_fast_path_shadow_compare_enabled: bool = False
    authz_tenant_db_fast_path_source_version: int = 1

    # DB pool controls (high concurrency)
    db_pool_size: int = 50
    db_max_overflow: int = 100
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_statement_timeout_ms: int = 12000

    # Guard/Bot policy knobs
    guard_heartbeat_base_seconds: int = 1800
    guard_heartbeat_stale_seconds: int = 2100
    guard_heartbeat_good_week_days: int = 7
    guard_heartbeat_max_multiplier: int = 4

    guard_license_expiry_window_hours: int = 72
    guard_license_expiry_tighten_seconds: int = 900
    guard_license_expiry_critical_hours: int = 24
    guard_license_expiry_critical_seconds: int = 600
    guard_license_expiry_emergency_hours: int = 6
    guard_license_expiry_emergency_seconds: int = 300

    guard_bot_sweep_interval_seconds: int = 300
    guard_bot_sweep_limit: int = 200
    guard_bot_default_mode: str = "SCHEDULED"
    guard_device_policy_enabled: bool = True
    guard_device_header_name: str = "X-Device-ID"
    guard_device_paused_desktop_auto_logout_minutes: int = 30

    # Guard bot cryptographic controls
    guard_bot_signature_required: bool = False
    guard_bot_signature_max_skew_seconds: int = 120
    guard_bot_nonce_ttl_seconds: int = 300
    guard_bot_signing_master_secret: str = ""
    guard_bot_failed_signature_limit: int = 5
    guard_bot_lockout_seconds: int = 900
    guard_bot_credential_auto_rotate_days: int = 30
    guard_bot_credential_rotation_batch_size: int = 200
    security_key_rotation_worker_enabled: bool = False
    # Licensing issuance flow (AUTO / SEMI / MANUAL)
    license_issuance_default_mode: str = "SEMI"

    # Deferred payments
    payment_deferred_default_terms_days: int = 30
    payment_deferred_default_grace_days: int = 3
    payment_overdue_sync_batch_size: int = 500
    payment_auto_hold_on_overdue_default: bool = True

    # Guard tenant bot license snapshot
    guard_license_snapshot_max_codes: int = 256

    # Zero-retention storage policy
    storage_provider: str = "minio"
    storage_bucket_verification: str = "mydata-verification"
    storage_endpoint: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_region: str = "us-east-1"
    storage_secure: bool = True
    storage_presign_ttl_seconds: int = 900
    storage_download_presign_ttl_seconds: int = 120
    storage_hard_delete_enabled: bool = True
    storage_delete_batch_size: int = 200
    storage_delete_queue_batch_size: int = 200
    storage_delete_retry_max_attempts: int = 8
    storage_delete_retry_base_seconds: int = 30
    storage_delete_retry_max_seconds: int = 3600

    # STS-style brokered grants (one-time exchange)
    storage_grant_secret: str = ""
    storage_grant_ttl_seconds_default: int = 120
    storage_grant_ttl_seconds_max: int = 600

    # Public portal draft/publish + branding assets
    storage_bucket_public_assets: str = "mydata-public-assets"
    public_logo_allowed_content_types: str = "image/png,image/jpeg,image/webp,image/svg+xml"
    public_logo_max_bytes: int = 2 * 1024 * 1024
    public_page_default_locale: str = "en"
    public_page_default_code: str = "HOME"

    verification_doc_retention_hours_default: int = 72
    verification_doc_retention_hours_max: int = 168
    verification_doc_allowed_content_types: str = "application/pdf,image/png,image/jpeg,text/plain,application/json,text/csv,text/markdown,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    verification_doc_max_bytes: int = 15 * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def cors_origins_list(self) -> list[str]:
        raw = str(self.cors_allow_origins or "").strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]

        out: list[str] = []
        for part in raw.split(","):
            item = part.strip()
            if item and item not in out:
                out.append(item)
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
