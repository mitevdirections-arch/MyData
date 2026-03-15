from __future__ import annotations

from fastapi import APIRouter

from app.modules.profile.router import (
    create_user_address,
    create_user_contact,
    create_user_document,
    create_user_next_of_kin,
    delete_user_address,
    delete_user_contact,
    delete_user_document,
    delete_user_next_of_kin,
    get_user,
    get_user_credentials,
    get_user_profile,
    issue_user_credentials,
    list_roles,
    list_user_addresses,
    list_user_contacts,
    list_user_documents,
    list_user_next_of_kin,
    list_users,
    profile_me,
    profile_me_update,
    reset_user_password,
    set_user_roles,
    update_user_address,
    update_user_contact,
    update_user_document,
    update_user_next_of_kin,
    update_user_profile,
    upsert_role,
    upsert_user,
)

router = APIRouter(prefix="/users", tags=["users"])

# Self profile
router.add_api_route("/me", profile_me, methods=["GET"], name="users_me_get")
router.add_api_route("/me", profile_me_update, methods=["PUT"], name="users_me_put")

# Roles / IAM
router.add_api_route("/admin/roles", list_roles, methods=["GET"], name="users_admin_roles_get")
router.add_api_route("/admin/roles/{role_code}", upsert_role, methods=["PUT"], name="users_admin_roles_put")

# Users core
router.add_api_route("/admin/users", list_users, methods=["GET"], name="users_admin_users_get")
router.add_api_route("/admin/users/{user_id}", upsert_user, methods=["PUT"], name="users_admin_user_put")
router.add_api_route("/admin/users/{user_id}", get_user, methods=["GET"], name="users_admin_user_get")
router.add_api_route("/admin/users/{user_id}/roles", set_user_roles, methods=["PUT"], name="users_admin_user_roles_put")

# User profile
router.add_api_route("/admin/users/{user_id}/profile", get_user_profile, methods=["GET"], name="users_admin_user_profile_get")
router.add_api_route("/admin/users/{user_id}/profile", update_user_profile, methods=["PUT"], name="users_admin_user_profile_put")

# Contacts
router.add_api_route("/admin/users/{user_id}/contacts", list_user_contacts, methods=["GET"], name="users_admin_user_contacts_get")
router.add_api_route("/admin/users/{user_id}/contacts", create_user_contact, methods=["POST"], name="users_admin_user_contacts_post")
router.add_api_route("/admin/users/{user_id}/contacts/{contact_id}", update_user_contact, methods=["PUT"], name="users_admin_user_contact_put")
router.add_api_route("/admin/users/{user_id}/contacts/{contact_id}", delete_user_contact, methods=["DELETE"], name="users_admin_user_contact_delete")

# Addresses
router.add_api_route("/admin/users/{user_id}/addresses", list_user_addresses, methods=["GET"], name="users_admin_user_addresses_get")
router.add_api_route("/admin/users/{user_id}/addresses", create_user_address, methods=["POST"], name="users_admin_user_addresses_post")
router.add_api_route("/admin/users/{user_id}/addresses/{address_id}", update_user_address, methods=["PUT"], name="users_admin_user_address_put")
router.add_api_route("/admin/users/{user_id}/addresses/{address_id}", delete_user_address, methods=["DELETE"], name="users_admin_user_address_delete")

# Next-of-kin
router.add_api_route("/admin/users/{user_id}/next-of-kin", list_user_next_of_kin, methods=["GET"], name="users_admin_user_next_of_kin_get")
router.add_api_route("/admin/users/{user_id}/next-of-kin", create_user_next_of_kin, methods=["POST"], name="users_admin_user_next_of_kin_post")
router.add_api_route("/admin/users/{user_id}/next-of-kin/{kin_id}", update_user_next_of_kin, methods=["PUT"], name="users_admin_user_next_of_kin_put")
router.add_api_route("/admin/users/{user_id}/next-of-kin/{kin_id}", delete_user_next_of_kin, methods=["DELETE"], name="users_admin_user_next_of_kin_delete")

# Documents metadata
router.add_api_route("/admin/users/{user_id}/documents", list_user_documents, methods=["GET"], name="users_admin_user_documents_get")
router.add_api_route("/admin/users/{user_id}/documents", create_user_document, methods=["POST"], name="users_admin_user_documents_post")
router.add_api_route("/admin/users/{user_id}/documents/{document_id}", update_user_document, methods=["PUT"], name="users_admin_user_document_put")
router.add_api_route("/admin/users/{user_id}/documents/{document_id}", delete_user_document, methods=["DELETE"], name="users_admin_user_document_delete")

# Credentials
router.add_api_route("/admin/users/{user_id}/credentials", get_user_credentials, methods=["GET"], name="users_admin_user_credentials_get")
router.add_api_route("/admin/users/{user_id}/credentials/issue", issue_user_credentials, methods=["POST"], name="users_admin_user_credentials_issue")
router.add_api_route("/admin/users/{user_id}/credentials/reset-password", reset_user_password, methods=["POST"], name="users_admin_user_credentials_reset")
