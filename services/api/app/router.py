import logging

from fastapi import APIRouter, Depends

from app.core.policy_matrix import enforce_request_policy
from app.modules.ai.router import router as ai_router
from app.modules.country_engine.api_public import router as country_engine_public_router
from app.modules.entity_verification.router import router as entity_verification_router
from app.modules.guard.router import router as guard_router
from app.modules.i18n.router import admin_router as i18n_admin_router, router as i18n_router, super_router as i18n_super_router
from app.modules.iam.router import router as iam_router
from app.modules.incidents.router import admin_router as incidents_admin_router, super_router as incidents_super_router
from app.modules.licensing.router import router as licensing_router
from app.modules.marketplace.router import router as marketplace_router
from app.modules.onboarding.router_admin import router as onboarding_admin_router
from app.modules.onboarding.router_public import router as onboarding_public_router
from app.modules.orders.router import router as orders_router
from app.modules.partners.router import router as partners_router
from app.modules.payments.router import admin_router as payments_admin_router, super_router as payments_super_router
from app.modules.provisioning.router import router as provisioning_router
from app.modules.profile.router import router as profile_router, super_router as profile_super_router
from app.modules.public_portal.router import admin_router as public_admin_router, router as public_portal_router
from app.modules.security_ops.router import router as security_ops_router
from app.modules.storage_policy.router import policy_router as storage_policy_router, router as storage_verification_router, super_router as storage_super_router
from app.modules.support.router import public_router as support_public_router, super_router as support_super_router, tenant_router as support_tenant_router
from app.modules.users.router import router as users_router
from app.modules.tenants.auth_router import router as auth_router
from app.modules.tenants.router import router as tenants_router

router_logger = logging.getLogger("mydata.core_api")

api_router = APIRouter(dependencies=[Depends(enforce_request_policy)])


def _include(router: APIRouter, label: str, *, explicit: bool = False) -> None:
    api_router.include_router(router)
    if explicit:
        router_logger.info("router loaded (explicit): %s", label)
        return
    router_logger.info("router loaded: %s", label)


_include(auth_router, "app.modules.tenants.auth_router")
_include(tenants_router, "app.modules.tenants.router", explicit=True)
_include(licensing_router, "app.modules.licensing.router", explicit=True)
_include(guard_router, "app.modules.guard.router", explicit=True)
_include(public_portal_router, "app.modules.public_portal.router", explicit=True)
_include(public_admin_router, "app.modules.public_portal.router", explicit=True)
_include(country_engine_public_router, "app.modules.country_engine.api_public", explicit=True)
_include(onboarding_public_router, "app.modules.onboarding.router_public", explicit=True)
_include(onboarding_admin_router, "app.modules.onboarding.router_admin", explicit=True)
_include(storage_policy_router, "app.modules.storage_policy.router", explicit=True)
_include(storage_verification_router, "app.modules.storage_policy.router", explicit=True)
_include(storage_super_router, "app.modules.storage_policy.router", explicit=True)
_include(ai_router, "app.modules.ai.router")
_include(incidents_admin_router, "app.modules.incidents.router")
_include(incidents_super_router, "app.modules.incidents.router")
_include(profile_router, "app.modules.profile.router", explicit=True)
_include(users_router, "app.modules.users.router", explicit=True)
_include(profile_super_router, "app.modules.profile.router", explicit=True)
_include(i18n_router, "app.modules.i18n.router")
_include(i18n_admin_router, "app.modules.i18n.router")
_include(i18n_super_router, "app.modules.i18n.router")
_include(marketplace_router, "app.modules.marketplace.router", explicit=True)
_include(payments_admin_router, "app.modules.payments.router", explicit=True)
_include(payments_super_router, "app.modules.payments.router", explicit=True)
_include(orders_router, "app.modules.orders.router", explicit=True)
_include(partners_router, "app.modules.partners.router", explicit=True)
_include(provisioning_router, "app.modules.provisioning.router", explicit=True)
_include(security_ops_router, "app.modules.security_ops.router", explicit=True)
_include(support_tenant_router, "app.modules.support.router", explicit=True)
_include(support_super_router, "app.modules.support.router", explicit=True)
_include(support_public_router, "app.modules.support.router", explicit=True)
_include(iam_router, "app.modules.iam.router", explicit=True)
_include(entity_verification_router, "app.modules.entity_verification.router", explicit=True)

