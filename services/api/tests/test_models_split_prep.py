from __future__ import annotations


def test_app_db_models_entrypoint_stays_stable() -> None:
    from app.db import models

    assert hasattr(models, "Tenant")
    assert hasattr(models, "License")
    assert hasattr(models, "WorkspaceUser")
    assert hasattr(models, "OnboardingApplication")
    assert hasattr(models, "PublicProfileSettings")
    assert hasattr(models, "I18nWorkspacePolicy")
    assert hasattr(models, "MarketplaceModule")
    assert hasattr(models, "MarketplaceOffer")
    assert hasattr(models, "TenantCreditAccount")
    assert hasattr(models, "PaymentInvoiceSequence")
    assert hasattr(models, "PaymentInvoice")
    assert hasattr(models, "EidonPatternPublishArtifact")
    assert hasattr(models, "EidonPatternDistributionRecord")
    assert hasattr(models, "EidonPatternRolloutGovernanceRecord")
    assert hasattr(models, "EidonAIQualityEvent")


def test_models_import_side_effect_keeps_metadata_loaded() -> None:
    from app.db import Base, models  # noqa: F401

    table_names = set(Base.metadata.tables.keys())
    expected = {
        "tenants",
        "licenses",
        "orders",
        "payment_invoices",
        "payment_invoice_sequences",
        "tenant_credit_accounts",
        "workspace_users",
        "guard_heartbeats",
        "onboarding_applications",
        "public_profile_settings",
        "i18n_workspace_policies",
        "public_workspace_settings",
        "public_brand_assets",
        "public_page_drafts",
        "public_page_published",
        "marketplace_modules",
        "marketplace_offers",
        "eidon_pattern_publish_artifacts",
        "eidon_pattern_distribution_records",
        "eidon_pattern_rollout_governance_records",
        "eidon_ai_quality_events",
    }
    missing = sorted(expected - table_names)
    assert missing == []


def test_representative_model_imports_remain_valid() -> None:
    from app.db.models import (
        GuardBotCredential,
        I18nWorkspacePolicy,
        License,
        EidonAIQualityEvent,
        EidonPatternDistributionRecord,
        EidonPatternRolloutGovernanceRecord,
        MarketplaceModule,
        MarketplaceOffer,
        OnboardingApplication,
        Order,
        EidonPatternPublishArtifact,
        PaymentInvoice,
        PaymentInvoiceSequence,
        PublicBrandAsset,
        PublicPageDraft,
        PublicPagePublished,
        PublicProfileSettings,
        PublicWorkspaceSettings,
        SupportRequest,
        Tenant,
        TenantCreditAccount,
        WorkspaceUser,
    )

    assert Tenant.__tablename__ == "tenants"
    assert License.__tablename__ == "licenses"
    assert PaymentInvoice.__tablename__ == "payment_invoices"
    assert PaymentInvoiceSequence.__tablename__ == "payment_invoice_sequences"
    assert TenantCreditAccount.__tablename__ == "tenant_credit_accounts"
    assert Order.__tablename__ == "orders"
    assert GuardBotCredential.__tablename__ == "guard_bot_credentials"
    assert WorkspaceUser.__tablename__ == "workspace_users"
    assert SupportRequest.__tablename__ == "support_requests"

    assert OnboardingApplication.__tablename__ == "onboarding_applications"
    assert PublicProfileSettings.__tablename__ == "public_profile_settings"
    assert I18nWorkspacePolicy.__tablename__ == "i18n_workspace_policies"
    assert PublicWorkspaceSettings.__tablename__ == "public_workspace_settings"
    assert PublicBrandAsset.__tablename__ == "public_brand_assets"
    assert PublicPageDraft.__tablename__ == "public_page_drafts"
    assert PublicPagePublished.__tablename__ == "public_page_published"

    assert MarketplaceModule.__tablename__ == "marketplace_modules"
    assert MarketplaceOffer.__tablename__ == "marketplace_offers"
    assert EidonPatternPublishArtifact.__tablename__ == "eidon_pattern_publish_artifacts"
    assert EidonPatternDistributionRecord.__tablename__ == "eidon_pattern_distribution_records"
    assert EidonPatternRolloutGovernanceRecord.__tablename__ == "eidon_pattern_rollout_governance_records"
    assert EidonAIQualityEvent.__tablename__ == "eidon_ai_quality_events"


def test_model_parts_split_prep_scaffold_contract() -> None:
    from app.db.model_parts import MODEL_SPLIT_PREP_VERSION, SPLIT_DOMAIN_MODULES, register_split_prep_domains

    assert MODEL_SPLIT_PREP_VERSION == "v1"
    assert len(SPLIT_DOMAIN_MODULES) >= 8
    assert register_split_prep_domains(import_placeholders=True) == SPLIT_DOMAIN_MODULES
