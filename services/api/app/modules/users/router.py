from __future__ import annotations

from fastapi import APIRouter

from app.modules.users.router_parts.admin_user_domain import (
    create_user_address,
    create_user_contact,
    create_user_document,
    delete_user_address,
    delete_user_contact,
    delete_user_document,
    get_user_credentials,
    get_user_profile,
    issue_user_credentials,
    issue_user_invite,
    lock_user_credential,
    list_user_addresses,
    list_user_contacts,
    list_user_documents,
    revoke_user_invite,
    reset_user_password,
    unlock_user_credential,
    update_user_address,
    update_user_contact,
    update_user_document,
    update_user_profile,
)
from app.modules.users.router_parts.admin_workspace import (
    delete_role,
    get_user,
    list_roles,
    list_users,
    provision_user,
    set_user_roles,
    upsert_role,
    upsert_user,
)
from app.modules.users.router_parts.next_of_kin import (
    create_user_next_of_kin,
    delete_user_next_of_kin,
    list_user_next_of_kin,
    update_user_next_of_kin,
)
from app.modules.users.router_parts.self_credentials import change_my_password, change_my_username
from app.modules.users.router_parts.self_profile import profile_me, profile_me_update

router = APIRouter(prefix="/users", tags=["users"])

# Self profile (compat surface).
router.add_api_route("/me", profile_me, methods=["GET"], name="users_me_get")
router.add_api_route("/me", profile_me_update, methods=["PUT"], name="users_me_put")
router.add_api_route("/me/credentials/change-password", change_my_password, methods=["POST"], name="users_me_credentials_change_password")
router.add_api_route("/me/credentials/change-username", change_my_username, methods=["POST"], name="users_me_credentials_change_username")

# Roles / IAM.
router.add_api_route("/admin/roles", list_roles, methods=["GET"], name="users_admin_roles_get")
router.add_api_route("/admin/roles/{role_code}", upsert_role, methods=["PUT"], name="users_admin_roles_put")
router.add_api_route("/admin/roles/{role_code}", delete_role, methods=["DELETE"], name="users_admin_roles_delete")

# Users core.
router.add_api_route("/admin/users", list_users, methods=["GET"], name="users_admin_users_get")
router.add_api_route("/admin/users/{user_id}", upsert_user, methods=["PUT"], name="users_admin_user_put")
router.add_api_route("/admin/users/{user_id}", get_user, methods=["GET"], name="users_admin_user_get")
router.add_api_route("/admin/users/{user_id}/roles", set_user_roles, methods=["PUT"], name="users_admin_user_roles_put")
router.add_api_route("/admin/users/{user_id}/provision", provision_user, methods=["POST"], name="users_admin_user_provision_post")

# User profile.
router.add_api_route("/admin/users/{user_id}/profile", get_user_profile, methods=["GET"], name="users_admin_user_profile_get")
router.add_api_route("/admin/users/{user_id}/profile", update_user_profile, methods=["PUT"], name="users_admin_user_profile_put")

# Contacts.
router.add_api_route("/admin/users/{user_id}/contacts", list_user_contacts, methods=["GET"], name="users_admin_user_contacts_get")
router.add_api_route("/admin/users/{user_id}/contacts", create_user_contact, methods=["POST"], name="users_admin_user_contacts_post")
router.add_api_route("/admin/users/{user_id}/contacts/{contact_id}", update_user_contact, methods=["PUT"], name="users_admin_user_contact_put")
router.add_api_route("/admin/users/{user_id}/contacts/{contact_id}", delete_user_contact, methods=["DELETE"], name="users_admin_user_contact_delete")

# Addresses.
router.add_api_route("/admin/users/{user_id}/addresses", list_user_addresses, methods=["GET"], name="users_admin_user_addresses_get")
router.add_api_route("/admin/users/{user_id}/addresses", create_user_address, methods=["POST"], name="users_admin_user_addresses_post")
router.add_api_route("/admin/users/{user_id}/addresses/{address_id}", update_user_address, methods=["PUT"], name="users_admin_user_address_put")
router.add_api_route("/admin/users/{user_id}/addresses/{address_id}", delete_user_address, methods=["DELETE"], name="users_admin_user_address_delete")

# Next-of-kin.
router.add_api_route("/admin/users/{user_id}/next-of-kin", list_user_next_of_kin, methods=["GET"], name="users_admin_user_next_of_kin_get")
router.add_api_route("/admin/users/{user_id}/next-of-kin", create_user_next_of_kin, methods=["POST"], name="users_admin_user_next_of_kin_post")
router.add_api_route("/admin/users/{user_id}/next-of-kin/{kin_id}", update_user_next_of_kin, methods=["PUT"], name="users_admin_user_next_of_kin_put")
router.add_api_route("/admin/users/{user_id}/next-of-kin/{kin_id}", delete_user_next_of_kin, methods=["DELETE"], name="users_admin_user_next_of_kin_delete")

# Documents metadata.
router.add_api_route("/admin/users/{user_id}/documents", list_user_documents, methods=["GET"], name="users_admin_user_documents_get")
router.add_api_route("/admin/users/{user_id}/documents", create_user_document, methods=["POST"], name="users_admin_user_documents_post")
router.add_api_route("/admin/users/{user_id}/documents/{document_id}", update_user_document, methods=["PUT"], name="users_admin_user_document_put")
router.add_api_route("/admin/users/{user_id}/documents/{document_id}", delete_user_document, methods=["DELETE"], name="users_admin_user_document_delete")

# Credentials.
router.add_api_route("/admin/users/{user_id}/credentials", get_user_credentials, methods=["GET"], name="users_admin_user_credentials_get")
router.add_api_route("/admin/users/{user_id}/credentials/issue", issue_user_credentials, methods=["POST"], name="users_admin_user_credentials_issue")
router.add_api_route("/admin/users/{user_id}/credentials/invite", issue_user_invite, methods=["POST"], name="users_admin_user_credentials_invite")
router.add_api_route("/admin/users/{user_id}/credentials/reset-password", reset_user_password, methods=["POST"], name="users_admin_user_credentials_reset")
router.add_api_route("/admin/users/{user_id}/credentials/lock", lock_user_credential, methods=["POST"], name="users_admin_user_credentials_lock")
router.add_api_route("/admin/users/{user_id}/credentials/unlock", unlock_user_credential, methods=["POST"], name="users_admin_user_credentials_unlock")
router.add_api_route("/admin/users/{user_id}/credentials/revoke-invite", revoke_user_invite, methods=["POST"], name="users_admin_user_credentials_revoke_invite")
