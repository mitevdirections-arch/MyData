from __future__ import annotations

from importlib import import_module

MODEL_SPLIT_PREP_VERSION = "v1"

SPLIT_DOMAIN_MODULES: tuple[str, ...] = (
    "shared_patterns",
    "tenants",
    "licensing",
    "ai",
    "marketplace",
    "partners",
    "payments",
    "orders",
    "guard_security",
    "profile",
    "iam_users_roles",
    "support_onboarding_public",
)


def register_split_prep_domains(*, import_placeholders: bool = False) -> tuple[str, ...]:
    """Return the planned domain modules for future split phases.

    When `import_placeholders=True`, imports placeholder modules to fail fast on missing scaffold files.
    """
    if import_placeholders:
        for name in SPLIT_DOMAIN_MODULES:
            import_module(f"app.db.model_parts.{name}")
    return SPLIT_DOMAIN_MODULES
