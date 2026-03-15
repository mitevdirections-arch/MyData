from __future__ import annotations

from fastapi import APIRouter

from app.modules.profile.router_parts.admin_user_domain import (
    create_user_address,
    create_user_contact,
    create_user_document,
    delete_user_address,
    delete_user_contact,
    delete_user_document,
    get_user_credentials,
    get_user_profile,
    issue_user_credentials,
    list_user_addresses,
    list_user_contacts,
    list_user_documents,
    reset_user_password,
    router as admin_user_domain_router,
    update_user_address,
    update_user_contact,
    update_user_document,
    update_user_profile,
)
from app.modules.profile.router_parts.admin_workspace import (
    get_user,
    list_roles,
    list_users,
    router as admin_workspace_router,
    set_user_roles,
    upsert_role,
    upsert_user,
)
from app.modules.profile.router_parts.superadmin import (
    super_router as profile_super_meta_router,
    tenants_overview,
)
from app.modules.profile.router_parts.workspace import (
    profile_me,
    profile_me_update,
    router as workspace_router,
    workspace_addresses_create,
    workspace_addresses_delete,
    workspace_addresses_list,
    workspace_addresses_update,
    workspace_contacts_create,
    workspace_contacts_delete,
    workspace_contacts_list,
    workspace_contacts_update,
    workspace_profile_get,
    workspace_profile_update,
)
from app.modules.profile.user_next_of_kin_router import (
    create_user_next_of_kin,
    delete_user_next_of_kin,
    list_user_next_of_kin,
    update_user_next_of_kin,
    router as user_next_of_kin_router,
)

router = APIRouter(prefix="/profile", tags=["profile"])
super_router = APIRouter(prefix="/superadmin/meta", tags=["superadmin.meta"])

router.include_router(workspace_router)
router.include_router(admin_workspace_router)
router.include_router(admin_user_domain_router)
router.include_router(user_next_of_kin_router)

super_router.include_router(profile_super_meta_router)

__all__ = [
    "router",
    "super_router",
    "profile_me",
    "profile_me_update",
    "workspace_profile_get",
    "workspace_profile_update",
    "workspace_contacts_list",
    "workspace_contacts_create",
    "workspace_contacts_update",
    "workspace_contacts_delete",
    "workspace_addresses_list",
    "workspace_addresses_create",
    "workspace_addresses_update",
    "workspace_addresses_delete",
    "list_roles",
    "upsert_role",
    "list_users",
    "upsert_user",
    "get_user",
    "set_user_roles",
    "get_user_profile",
    "update_user_profile",
    "list_user_contacts",
    "create_user_contact",
    "update_user_contact",
    "delete_user_contact",
    "list_user_addresses",
    "create_user_address",
    "update_user_address",
    "delete_user_address",
    "list_user_documents",
    "create_user_document",
    "update_user_document",
    "delete_user_document",
    "get_user_credentials",
    "issue_user_credentials",
    "reset_user_password",
    "create_user_next_of_kin",
    "update_user_next_of_kin",
    "delete_user_next_of_kin",
    "list_user_next_of_kin",
    "user_next_of_kin_router",
    "tenants_overview",
]
