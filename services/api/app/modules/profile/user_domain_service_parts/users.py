from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.db.models import (
    Tenant,
    WorkspaceUser,
    WorkspaceUserAddress,
    WorkspaceUserContactChannel,
    WorkspaceUserCredential,
    WorkspaceUserDocument,
    WorkspaceUserNextOfKin,
    WorkspaceUserProfile,
)
from app.modules.profile.service import PLATFORM_WORKSPACE_ID, WORKSPACE_PLATFORM, WORKSPACE_TENANT, service as workspace_service
from app.modules.profile import user_domain_ops

class UserDomainUsersMixin:
    def get_or_create_user_profile(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any]:

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        self._ensure_workspace_exists(db, workspace_type=wtype, workspace_id=wid)

        user = self._ensure_workspace_user(db, workspace_type=wtype, workspace_id=wid, user_id=user_id, actor=actor)



        row = (

            db.query(WorkspaceUserProfile)

            .filter(

                WorkspaceUserProfile.workspace_type == wtype,

                WorkspaceUserProfile.workspace_id == wid,

                WorkspaceUserProfile.user_id == user.user_id,

            )

            .first()

        )

        if row is None:

            now = self._now()

            row = WorkspaceUserProfile(

                workspace_type=wtype,

                workspace_id=wid,

                user_id=user.user_id,

                first_name=None,

                last_name=None,

                display_name=user.display_name,

                date_of_birth=None,

contact_email=user.email,

                contact_phone=None,

address_country_code=None,

                address_line1=None,

                address_line2=None,

                address_city=None,

                address_postal_code=None,

                bank_account_holder=None,

                bank_iban=None,

                bank_swift=None,

                bank_name=None,

                bank_currency=None,

                employee_code=None,

                job_title=user.job_title,

                department=user.department,

                employment_status=user.employment_status or "ACTIVE",

                preferred_locale="en",

                preferred_time_zone="UTC",

                date_style="YMD",

                time_style="H24",

                unit_system="metric",

                metadata_json={},

                created_by=str(actor or "unknown"),

                updated_by=str(actor or "unknown"),

                created_at=now,

                updated_at=now,

            )

            db.add(row)

            db.flush()



        contacts = [self._contact_to_dict(x) for x in self._list_contacts_rows(db, workspace_type=wtype, workspace_id=wid, user_id=user.user_id)]

        addresses = [self._address_to_dict(x) for x in self._list_addresses_rows(db, workspace_type=wtype, workspace_id=wid, user_id=user.user_id)]

        documents = [self._doc_to_dict(x) for x in self._list_documents_rows(db, workspace_type=wtype, workspace_id=wid, user_id=user.user_id)]

        next_of_kin = [self._next_of_kin_to_dict(x) for x in self._list_next_of_kin_rows(db, workspace_type=wtype, workspace_id=wid, user_id=user.user_id)]

        return self._profile_to_dict(row, contacts=contacts, addresses=addresses, documents=documents, next_of_kin=next_of_kin)

    def update_user_profile(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()



        row = (

            db.query(WorkspaceUserProfile)

            .filter(

                WorkspaceUserProfile.workspace_type == wtype,

                WorkspaceUserProfile.workspace_id == wid,

                WorkspaceUserProfile.user_id == uid,

            )

            .first()

        )

        if row is None:

            raise ValueError("user_profile_not_found")



        identity = self._as_dict(payload.get("identity"))

        contacts = self._as_dict(payload.get("contacts"))

        address = self._as_dict(payload.get("address"))

        payroll = self._as_dict(payload.get("payroll"))

        if not payroll and isinstance(payload.get("banking"), dict):

            payroll = self._as_dict(payload.get("banking"))

        employment = self._as_dict(payload.get("employment"))

        preferences = self._as_dict(payload.get("preferences"))



        row.first_name = self._clean_text(identity.get("first_name"), 128)

        row.last_name = self._clean_text(identity.get("last_name"), 128)

        row.display_name = self._clean_text(identity.get("display_name"), 255)

        row.date_of_birth = self._parse_datetime(identity.get("date_of_birth"))

        row.employee_code = self._clean_text(identity.get("employee_code"), 64)



        row.contact_email = self._clean_text(contacts.get("email"), 255)

        row.contact_phone = self._clean_text(contacts.get("phone"), 64)



        row.address_country_code = self._clean_text(address.get("country_code"), 8)

        row.address_line1 = self._clean_text(address.get("line1"), 255)

        row.address_line2 = self._clean_text(address.get("line2"), 255)

        row.address_city = self._clean_text(address.get("city"), 128)

        row.address_postal_code = self._clean_text(address.get("postal_code"), 32)



        row.bank_account_holder = self._clean_text(payroll.get("account_holder"), 255)

        row.bank_iban = self._clean_text(payroll.get("iban"), 64)

        row.bank_swift = self._clean_text(payroll.get("swift"), 32)

        row.bank_name = self._clean_text(payroll.get("bank_name"), 255)

        row.bank_currency = self._clean_text(payroll.get("currency"), 16)



        row.job_title = self._clean_text(employment.get("job_title"), 128)

        row.department = self._clean_text(employment.get("department"), 128)

        row.employment_status = (self._clean_text(employment.get("employment_status"), 32) or row.employment_status or "ACTIVE").upper()



        row.preferred_locale = self._clean_text(preferences.get("locale"), 32)

        row.preferred_time_zone = self._clean_text(preferences.get("time_zone"), 64)

        row.date_style = self._clean_text(preferences.get("date_style"), 8)

        row.time_style = self._clean_text(preferences.get("time_style"), 8)

        row.unit_system = self._clean_text(preferences.get("unit_system"), 16)



        if isinstance(payload.get("metadata"), dict):

            row.metadata_json = dict(payload.get("metadata") or {})



        row.updated_by = str(actor or "unknown")

        row.updated_at = self._now()



        user = (

            db.query(WorkspaceUser)

            .filter(

                WorkspaceUser.workspace_type == wtype,

                WorkspaceUser.workspace_id == wid,

                WorkspaceUser.user_id == uid,

            )

            .first()

        )

        if user is not None:

            if row.display_name:

                user.display_name = row.display_name

            user.email = row.contact_email

            user.job_title = row.job_title

            user.department = row.department

            user.employment_status = row.employment_status

            user.updated_by = str(actor or "unknown")

            user.updated_at = self._now()



        db.flush()

        return self.get_or_create_user_profile(db, workspace_type=wtype, workspace_id=wid, user_id=uid, actor=actor)

    def bootstrap_first_tenant_admin(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:

        tid = str(tenant_id or "").strip()

        if not tid:

            raise ValueError("tenant_id_required")

        self._ensure_workspace_exists(db, workspace_type=WORKSPACE_TENANT, workspace_id=tid)



        data = self._as_dict(payload)

        uid = self._clean_text(data.get("user_id"), 255)

        email = self._clean_text(data.get("email"), 255)

        if not uid:

            uid = email

        if not uid:

            raise ValueError("user_id_required")



        allow_if_exists = bool(data.get("allow_if_exists", False))

        users_count = int(

            db.query(WorkspaceUser)

            .filter(

                WorkspaceUser.workspace_type == WORKSPACE_TENANT,

                WorkspaceUser.workspace_id == tid,

            )

            .count()

        )

        if users_count > 0 and not allow_if_exists:

            raise ValueError("first_admin_already_exists")



        workspace_user = workspace_service.upsert_workspace_user(

            db,

            workspace_type=WORKSPACE_TENANT,

            workspace_id=tid,

            user_id=uid,

            payload={

                "email": email,

                "display_name": self._clean_text(data.get("display_name"), 255) or uid,

                "job_title": self._clean_text(data.get("job_title"), 128) or "Tenant Administrator",

                "department": self._clean_text(data.get("department"), 128),

                "employment_status": "ACTIVE",

                "direct_permissions": list(data.get("direct_permissions") or []),

                "meta": self._as_dict(data.get("meta")),

            },

            actor=actor,

        )



        with_roles = workspace_service.set_workspace_user_roles(

            db,

            workspace_type=WORKSPACE_TENANT,

            workspace_id=tid,

            user_id=uid,

            role_codes=["TENANT_ADMIN"],

            actor=actor,

        )



        admin_profile = workspace_service.get_or_create_admin_profile(

            db,

            workspace_type=WORKSPACE_TENANT,

            workspace_id=tid,

            user_id=uid,

            actor=actor,

        )

        admin_profile = workspace_service.update_admin_profile(

            db,

            workspace_type=WORKSPACE_TENANT,

            workspace_id=tid,

            user_id=uid,

            actor=actor,

            payload={

                "display_name": self._clean_text(data.get("display_name"), 255) or admin_profile.get("display_name"),

                "email": email,

                "phone": self._clean_text(data.get("phone"), 64),

                "job_title": self._clean_text(data.get("job_title"), 128) or "Tenant Administrator",

                "avatar_url": self._clean_text(data.get("avatar_url"), 1024),

                "preferences": self._as_dict(data.get("preferences")),

                "notification_prefs": self._as_dict(data.get("notification_prefs")),

            },

        )



        user_profile = self.get_or_create_user_profile(

            db,

            workspace_type=WORKSPACE_TENANT,

            workspace_id=tid,

            user_id=uid,

            actor=actor,

        )

        profile_payload = self._as_dict(data.get("user_profile"))

        if profile_payload:

            user_profile = self.update_user_profile(

                db,

                workspace_type=WORKSPACE_TENANT,

                workspace_id=tid,

                user_id=uid,

                actor=actor,

                payload=profile_payload,

            )



        cred_resp = None

        if bool(data.get("issue_credentials", True)):

            cred_payload = self._as_dict(data.get("credentials"))

            if email and not cred_payload.get("username"):

                cred_payload["username"] = str(email).split("@", 1)[0]

            try:

                cred_resp = self.issue_user_credentials(

                    db,

                    workspace_type=WORKSPACE_TENANT,

                    workspace_id=tid,

                    user_id=uid,

                    actor=actor,

                    payload=cred_payload,

                    reset_existing=bool(data.get("reset_credentials_if_exists", False)),

                )

            except ValueError as exc:

                if str(exc) != "credentials_already_issued":

                    raise

                cred_resp = {

                    "ok": True,

                    "credential": self.get_user_credential(

                        db,

                        workspace_type=WORKSPACE_TENANT,

                        workspace_id=tid,

                        user_id=uid,

                        actor=actor,

                    ),

                    "temporary_password": None,

                    "temporary_password_expires_at": None,

                    "mode": "EXISTING",

                }



        return {

            "ok": True,

            "tenant_id": tid,

            "first_admin_user_id": uid,

            "users_in_workspace_before": users_count,

            "workspace_user": workspace_user,

            "workspace_user_with_roles": with_roles,

            "admin_profile": admin_profile,

            "user_profile": user_profile,

            "credentials": cred_resp,

        }





