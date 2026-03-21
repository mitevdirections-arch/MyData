from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.settings import get_settings
from app.db.models import Tenant
from app.modules.guard.service import service as guard_service
from app.modules.i18n.service import service as i18n_service
from app.modules.licensing.core_catalog import DEFAULT_CORE_PLAN_CODE, canonical_plan_code
from app.modules.licensing.service import service as licensing_service
from app.modules.profile.service import WORKSPACE_TENANT, service as profile_service
from app.modules.users.service import service as user_domain_service
from app.modules.public_portal import service as public_portal_service


class ProvisioningService:
    def _clean_text(self, value: Any, max_len: int) -> str | None:
        if value is None:
            return None
        txt = str(value).strip()
        if not txt:
            return None
        return txt[:max_len]

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _tenant_upsert(self, db: Session, *, tenant_id: str, tenant_name: str, vat_number: str | None) -> dict[str, Any]:
        existing = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if existing is None:
            db.add(Tenant(id=tenant_id, name=tenant_name, vat_number=vat_number, is_active=True))
            db.flush()
            return {"created": True, "updated": True, "tenant_id": tenant_id, "name": tenant_name, "vat_number": vat_number}

        changed = False
        if tenant_name and existing.name != tenant_name:
            existing.name = tenant_name
            changed = True
        if vat_number is not None and existing.vat_number != vat_number:
            existing.vat_number = vat_number
            changed = True
        if not bool(existing.is_active):
            existing.is_active = True
            changed = True
        if changed:
            db.flush()

        return {
            "created": False,
            "updated": changed,
            "tenant_id": tenant_id,
            "name": existing.name,
            "vat_number": existing.vat_number,
        }

    def _provision_issuance(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        issuance = self._as_dict(payload.get("issuance"))
        requested_mode = self._clean_text(issuance.get("mode"), 16)
        requested_core_plan = canonical_plan_code(
            self._clean_text(issuance.get("core_plan_code"), 64),
            default=DEFAULT_CORE_PLAN_CODE,
        )
        if requested_mode:
            policy = licensing_service.set_issuance_policy(db, tenant_id=tenant_id, mode=requested_mode, actor=actor)
        else:
            policy = licensing_service.get_issuance_policy(db, tenant_id=tenant_id)

        issue_startup = bool(issuance.get("issue_startup", True))
        admin_confirmed = bool(issuance.get("admin_confirmed", True))
        note = self._clean_text(issuance.get("note"), 512)

        startup: dict[str, Any]
        if not issue_startup:
            startup = {
                "ok": True,
                "flow": "SKIPPED",
                "reason": "issue_startup_disabled",
                "mode": policy.get("mode"),
                "tenant_id": tenant_id,
            }
        else:
            try:
                startup = licensing_service.request_startup_with_policy(
                    db,
                    tenant_id=tenant_id,
                    requested_by=actor,
                    admin_confirmed=admin_confirmed,
                    note=note,
                    core_plan_code=requested_core_plan,
                )
            except ValueError as exc:
                if str(exc) != "startup_non_renewable":
                    raise
                startup = {
                    "ok": True,
                    "flow": "ALREADY_ISSUED",
                    "mode": policy.get("mode"),
                    "tenant_id": tenant_id,
                    "active": licensing_service.active_license_catalog(db, tenant_id=tenant_id),
                }

        return {
            "policy": policy,
            "startup": startup,
            "core_plan_code": requested_core_plan,
            "entitlement_v2": licensing_service.entitlement_snapshot_v2(db, tenant_id=tenant_id),
        }

    def _provision_profile(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        admin = self._as_dict(payload.get("admin"))
        org = self._as_dict(payload.get("organization"))

        admin_user_id = self._clean_text(admin.get("user_id"), 255) or actor
        if not admin_user_id:
            raise ValueError("admin_user_id_required")

        bootstrap_payload: dict[str, Any] = {
            "user_id": admin_user_id,
            "email": self._clean_text(admin.get("email"), 255),
            "display_name": self._clean_text(admin.get("display_name"), 255),
            "phone": self._clean_text(admin.get("phone"), 64),
            "job_title": self._clean_text(admin.get("job_title"), 128),
            "department": self._clean_text(admin.get("department"), 128),
            "avatar_url": self._clean_text(admin.get("avatar_url"), 1024),
            "preferences": self._as_dict(admin.get("preferences")),
            "notification_prefs": self._as_dict(admin.get("notification_prefs")),
            "direct_permissions": list(admin.get("direct_permissions") or []),
            "meta": self._as_dict(admin.get("meta")),
            "allow_if_exists": True,
            "issue_credentials": bool(admin.get("issue_credentials", True)),
            "reset_credentials_if_exists": bool(admin.get("reset_credentials_if_exists", False)),
            "credentials": self._as_dict(admin.get("credentials")),
            "user_profile": self._as_dict(admin.get("user_profile")),
        }

        first_admin = user_domain_service.bootstrap_first_tenant_admin(
            db,
            tenant_id=tenant_id,
            actor=actor,
            payload=bootstrap_payload,
        )

        workspace_profile = profile_service.get_or_create_organization_profile(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id=tenant_id,
            actor=actor,
        )
        if org:
            workspace_profile = profile_service.update_organization_profile(
                db,
                workspace_type=WORKSPACE_TENANT,
                workspace_id=tenant_id,
                actor=actor,
                payload=org,
            )

        default_roles = profile_service.list_roles(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id=tenant_id,
            actor=actor,
            limit=200,
        )
        return {
            "admin_user_id": admin_user_id,
            "first_admin": first_admin,
            "admin_profile": first_admin.get("admin_profile"),
            "user_profile": first_admin.get("user_profile"),
            "credentials": first_admin.get("credentials"),
            "workspace_profile": workspace_profile,
            "default_roles_count": len(default_roles),
        }

    def _provision_i18n(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        i18n = self._as_dict(payload.get("i18n"))
        if not i18n:
            return i18n_service.get_or_create_workspace_policy(
                db,
                workspace_type=WORKSPACE_TENANT,
                workspace_id=tenant_id,
                actor=actor,
            )

        return i18n_service.set_workspace_policy(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id=tenant_id,
            actor=actor,
            default_locale=str(i18n.get("default_locale") or "en"),
            fallback_locale=str(i18n.get("fallback_locale") or "en"),
            enabled_locales=list(i18n.get("enabled_locales") or []),
        )

    def _provision_public_profile(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        public = self._as_dict(payload.get("public_profile"))
        public_settings = self._as_dict(public.get("settings"))

        if public_settings:
            settings_row = public_portal_service.update_workspace_settings(
                db,
                workspace_type=WORKSPACE_TENANT,
                workspace_id=tenant_id,
                payload=public_settings,
                actor=actor,
            )
        else:
            settings_row = public_portal_service.get_workspace_settings(
                db,
                workspace_type=WORKSPACE_TENANT,
                workspace_id=tenant_id,
            )

        locale = str(public.get("locale") or get_settings().public_page_default_locale)
        page_code = str(public.get("page_code") or get_settings().public_page_default_code).strip().upper()
        if not page_code:
            raise ValueError("page_code_required")

        editor = public_portal_service.build_editor_state(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id=tenant_id,
            locale=locale,
            page_code=page_code,
            actor=actor,
        )

        published = None
        if bool(public.get("publish_initial", False)):
            note = self._clean_text(public.get("publish_note"), 1024)
            pub_row = public_portal_service.publish_draft(
                db,
                workspace_type=WORKSPACE_TENANT,
                workspace_id=tenant_id,
                locale=locale,
                page_code=page_code,
                actor=actor,
                note=note,
            )
            published = {
                "id": str(pub_row.id),
                "version": int(pub_row.version),
                "published_by": pub_row.published_by,
                "published_at": pub_row.published_at.isoformat() if pub_row.published_at else None,
            }

        return {
            "workspace_type": WORKSPACE_TENANT,
            "workspace_id": tenant_id,
            "locale": locale,
            "page_code": page_code,
            "settings": {
                "show_company_info": bool(settings_row.show_company_info),
                "show_fleet": bool(settings_row.show_fleet),
                "show_contacts": bool(settings_row.show_contacts),
                "show_price_list": bool(settings_row.show_price_list),
                "show_working_hours": bool(settings_row.show_working_hours),
            },
            "draft_id": ((editor.get("draft") or {}).get("id")),
            "published": published,
        }

    def _provision_guard(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        guard = self._as_dict(payload.get("guard"))
        issue_credential = bool(guard.get("issue_bot_credential", True))
        if not issue_credential:
            return {"flow": "SKIPPED", "reason": "issue_bot_credential_disabled"}

        existing = guard_service.list_bot_credentials(db, tenant_id=tenant_id, limit=200)
        active = [x for x in existing if str(x.get("status") or "").upper() == "ACTIVE"]
        if active:
            return {
                "flow": "ALREADY_ACTIVE",
                "active_count": len(active),
                "active_bot_ids": [str(x.get("bot_id") or "") for x in active if x.get("bot_id")],
            }

        out = guard_service.issue_bot_credential(
            db,
            tenant_id=tenant_id,
            actor=actor,
            label=self._clean_text(guard.get("label"), 255),
        )
        return {"flow": "ISSUED", "credential": out}

    def run_tenant_provisioning(self, db: Session, *, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        body = self._as_dict(payload)
        tenant_block = self._as_dict(body.get("tenant"))

        tenant_id = self._clean_text(body.get("tenant_id"), 64) or self._clean_text(tenant_block.get("tenant_id"), 64)
        if not tenant_id:
            raise ValueError("tenant_id_required")

        tenant_name = (
            self._clean_text(body.get("name"), 255)
            or self._clean_text(tenant_block.get("name"), 255)
            or tenant_id
        )
        vat_number = self._clean_text(body.get("vat_number"), 64) or self._clean_text(tenant_block.get("vat_number"), 64)

        tenant_result = self._tenant_upsert(db, tenant_id=tenant_id, tenant_name=tenant_name, vat_number=vat_number)
        issuance_result = self._provision_issuance(db, tenant_id=tenant_id, actor=actor, payload=body)
        profile_result = self._provision_profile(db, tenant_id=tenant_id, actor=actor, payload=body)
        i18n_result = self._provision_i18n(db, tenant_id=tenant_id, actor=actor, payload=body)
        public_result = self._provision_public_profile(db, tenant_id=tenant_id, actor=actor, payload=body)
        guard_result = self._provision_guard(db, tenant_id=tenant_id, actor=actor, payload=body)

        summary = {
            "tenant_id": tenant_id,
            "tenant_created": bool(tenant_result.get("created")),
            "issuance_mode": (issuance_result.get("policy") or {}).get("mode"),
            "startup_flow": (issuance_result.get("startup") or {}).get("flow"),
            "guard_flow": guard_result.get("flow"),
            "default_roles_count": profile_result.get("default_roles_count"),
        }

        write_audit(
            db,
            action="provisioning.tenant.run",
            actor=actor,
            tenant_id=tenant_id,
            target=f"provisioning/tenant/{tenant_id}",
            metadata={
                "summary": summary,
                "tenant_created": bool(tenant_result.get("created")),
                "startup_flow": (issuance_result.get("startup") or {}).get("flow"),
                "guard_flow": guard_result.get("flow"),
            },
        )
        db.commit()

        return {
            "ok": True,
            "requested_by": actor,
            "summary": summary,
            "tenant": tenant_result,
            "issuance": issuance_result,
            "profile": profile_result,
            "i18n": i18n_result,
            "public_profile": public_result,
            "guard": guard_result,
        }


service = ProvisioningService()
