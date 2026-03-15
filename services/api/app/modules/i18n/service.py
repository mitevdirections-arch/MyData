from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AdminProfile, I18nWorkspacePolicy
from app.modules.i18n.catalog import CATALOG_VERSION, CATALOGS, LOCALE_REGISTRY
from app.modules.profile.service import WORKSPACE_PLATFORM, service as profile_service


class I18nService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _normalize_locale(self, raw: str | None) -> str:
        val = str(raw or "").strip()
        if not val:
            return "en"
        val = val.replace("_", "-")
        base = val.split("-", 1)[0].lower()
        return base

    def _supported_codes(self) -> set[str]:
        return {str(x.get("code") or "").strip().lower() for x in LOCALE_REGISTRY}

    def resolve_supported_locale(self, raw: str | None, fallback: str = "en") -> str:
        norm = self._normalize_locale(raw)
        return norm if norm in self._supported_codes() else self._normalize_locale(fallback)

    def list_locales(self) -> list[dict[str, Any]]:
        return [dict(x) for x in LOCALE_REGISTRY]

    def get_catalog(self, locale: str) -> dict[str, Any]:
        code = self.resolve_supported_locale(locale, fallback="en")
        data = CATALOGS.get(code)
        if data is None:
            data = CATALOGS.get("en", {})
            code = "en"
        return {
            "ok": True,
            "locale": code,
            "catalog_version": CATALOG_VERSION,
            "messages": data,
        }

    def _policy_payload(self, row: I18nWorkspacePolicy | None, *, workspace_type: str, workspace_id: str) -> dict[str, Any]:
        if row is None:
            return {
                "workspace_type": workspace_type,
                "workspace_id": workspace_id,
                "default_locale": "en",
                "fallback_locale": "en",
                "enabled_locales": ["en", "bg"],
                "updated_by": None,
                "updated_at": None,
            }
        return self._policy_payload(row, workspace_type=workspace_type, workspace_id=workspace_id)

    def get_workspace_policy(self, db: Session, *, workspace_type: str, workspace_id: str) -> dict[str, Any]:
        row = (
            db.query(I18nWorkspacePolicy)
            .filter(I18nWorkspacePolicy.workspace_type == workspace_type, I18nWorkspacePolicy.workspace_id == workspace_id)
            .first()
        )
        return self._policy_payload(row, workspace_type=workspace_type, workspace_id=workspace_id)

    def get_or_create_workspace_policy(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str) -> dict[str, Any]:
        profile_service._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
        row = db.query(I18nWorkspacePolicy).filter(I18nWorkspacePolicy.workspace_type == workspace_type, I18nWorkspacePolicy.workspace_id == workspace_id).first()
        if row is None:
            now = self._now()
            row = I18nWorkspacePolicy(
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                default_locale="en",
                fallback_locale="en",
                enabled_locales_json=["en", "bg"],
                updated_by=str(actor or "unknown"),
                updated_at=now,
            )
            db.add(row)
            try:
                db.flush()
            except IntegrityError:
                # Concurrent create on same workspace key: recover by re-reading the row.
                db.rollback()
                profile_service._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
                row = (
                    db.query(I18nWorkspacePolicy)
                    .filter(I18nWorkspacePolicy.workspace_type == workspace_type, I18nWorkspacePolicy.workspace_id == workspace_id)
                    .first()
                )
                if row is None:
                    raise
        return {
            "workspace_type": row.workspace_type,
            "workspace_id": row.workspace_id,
            "default_locale": row.default_locale,
            "fallback_locale": row.fallback_locale,
            "enabled_locales": row.enabled_locales_json or ["en"],
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def set_workspace_policy(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        actor: str,
        default_locale: str,
        fallback_locale: str,
        enabled_locales: list[str] | None,
    ) -> dict[str, Any]:
        row_dict = self.get_or_create_workspace_policy(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        row = db.query(I18nWorkspacePolicy).filter(I18nWorkspacePolicy.workspace_type == workspace_type, I18nWorkspacePolicy.workspace_id == workspace_id).first()
        if row is None:
            raise ValueError("i18n_policy_not_found")

        def_loc = self.resolve_supported_locale(default_locale, fallback="en")
        fb_loc = self.resolve_supported_locale(fallback_locale, fallback=def_loc)

        enabled: list[str] = []
        seen: set[str] = set()
        for raw in list(enabled_locales or []):
            code = self.resolve_supported_locale(raw, fallback="en")
            if code in seen:
                continue
            seen.add(code)
            enabled.append(code)
        if def_loc not in seen:
            enabled.append(def_loc)
            seen.add(def_loc)
        if fb_loc not in seen:
            enabled.append(fb_loc)

        row.default_locale = def_loc
        row.fallback_locale = fb_loc
        row.enabled_locales_json = enabled
        row.updated_by = str(actor or "unknown")
        row.updated_at = self._now()
        db.flush()

        row_dict.update(
            {
                "default_locale": row.default_locale,
                "fallback_locale": row.fallback_locale,
                "enabled_locales": row.enabled_locales_json or ["en"],
                "updated_by": row.updated_by,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
        return row_dict

    def resolve_effective_locale(
        self,
        db: Session,
        *,
        claims: dict[str, Any],
        workspace: str | None,
        requested_locale: str | None,
    ) -> dict[str, Any]:
        wtype, wid = profile_service.resolve_workspace(claims, workspace=workspace)
        actor = str(claims.get("sub") or "unknown")

        policy = self.get_or_create_workspace_policy(db, workspace_type=wtype, workspace_id=wid, actor=actor)
        profile = profile_service.get_or_create_admin_profile(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=actor,
            actor=actor,
        )

        preferred = None
        prefs = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
        if isinstance(prefs, dict):
            preferred = str(prefs.get("locale") or "").strip() or None

        effective = self.resolve_supported_locale(requested_locale or preferred or policy.get("default_locale"), fallback=policy.get("fallback_locale") or "en")

        return {
            "ok": True,
            "workspace_type": wtype,
            "workspace_id": wid,
            "effective_locale": effective,
            "profile_preferred_locale": preferred,
            "workspace_policy": policy,
            "catalog": self.get_catalog(effective),
            "meta": {
                "catalog_version": CATALOG_VERSION,
                "is_platform_scope": wtype == WORKSPACE_PLATFORM,
            },
        }


service = I18nService()