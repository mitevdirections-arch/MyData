from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Tenant, WorkspaceOrganizationProfile
from app.modules.payments.service_constants import (
    ALLOWED_ENFORCEMENT_MODE,
    ALLOWED_NUMBERING_MODE,
    ALLOWED_TEMPLATE_CODES,
    ALLOWED_VAT_MODE,
    BG_EXTRA_REQUIRED,
    DEFAULT_TEMPLATE_POLICY,
    EU_REQUIRED_BASE,
    WORKSPACE_TENANT,
)


class PaymentsTemplatesMixin:
    def _template_code(self, value: Any, default: str = "EU_VAT_V1") -> str:
        out = self._clean(value or default, 32).upper()
        if out not in ALLOWED_TEMPLATE_CODES:
            raise ValueError("invoice_template_code_invalid")
        return out

    def _numbering_mode(self, value: Any, default: str = "AUTO_EU") -> str:
        out = self._clean(value or default, 32).upper()
        if out not in ALLOWED_NUMBERING_MODE:
            raise ValueError("invoice_numbering_mode_invalid")
        return out

    def _vat_mode(self, value: Any, default: str = "STANDARD") -> str:
        out = self._clean(value or default, 32).upper()
        if out not in ALLOWED_VAT_MODE:
            raise ValueError("invoice_vat_mode_invalid")
        return out

    def _enforcement_mode(self, value: Any, default: str = "WARN") -> str:
        out = self._clean(value or default, 16).upper()
        if out not in ALLOWED_ENFORCEMENT_MODE:
            raise ValueError("invoice_enforcement_mode_invalid")
        return out

    def _tenant_country_code(self, db: Session, *, tenant_id: str) -> str:
        org = (
            db.query(WorkspaceOrganizationProfile)
            .filter(
                WorkspaceOrganizationProfile.workspace_type == WORKSPACE_TENANT,
                WorkspaceOrganizationProfile.workspace_id == tenant_id,
            )
            .first()
        )
        cc = self._clean((org.address_country_code if org is not None else None), 8).upper()
        if cc:
            return cc

        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        vat = self._clean((tenant.vat_number if tenant is not None else None), 64).upper()
        if len(vat) >= 2 and vat[:2].isalpha():
            return vat[:2]
        return "EU"

    def _default_policy_for_country(self, country_code: str) -> dict[str, Any]:
        out = dict(DEFAULT_TEMPLATE_POLICY)
        out["country_code"] = self._clean(country_code, 8).upper() or "EU"
        return out

    def _normalize_template_policy(self, payload: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        out = dict(base or DEFAULT_TEMPLATE_POLICY)

        if "template_code" in payload:
            out["template_code"] = self._template_code(payload.get("template_code"), out.get("template_code") or "EU_VAT_V1")
        if "numbering_mode" in payload:
            out["numbering_mode"] = self._numbering_mode(payload.get("numbering_mode"), out.get("numbering_mode") or "AUTO_EU")
        if "vat_mode" in payload:
            out["vat_mode"] = self._vat_mode(payload.get("vat_mode"), out.get("vat_mode") or "STANDARD")
        if "vat_rate_percent" in payload:
            try:
                out["vat_rate_percent"] = max(0, min(int(payload.get("vat_rate_percent") or 0), 100))
            except Exception as exc:  # noqa: BLE001
                raise ValueError("invoice_vat_rate_invalid") from exc
        if "enforcement_mode" in payload:
            out["enforcement_mode"] = self._enforcement_mode(payload.get("enforcement_mode"), out.get("enforcement_mode") or "WARN")
        if "country_code" in payload:
            out["country_code"] = self._clean(payload.get("country_code"), 8).upper() or (out.get("country_code") or "EU")
        if "exemption_reason" in payload:
            out["exemption_reason"] = self._clean(payload.get("exemption_reason"), 512) or None
        if "reverse_charge_note" in payload:
            out["reverse_charge_note"] = self._clean(payload.get("reverse_charge_note"), 512) or None

        if out.get("template_code") == "BG_VAT_V1" and "numbering_mode" not in payload:
            out["numbering_mode"] = "BG_NUMERIC10"
        if out.get("template_code") == "EU_VAT_V1" and "numbering_mode" not in payload and out.get("numbering_mode") == "BG_NUMERIC10":
            out["numbering_mode"] = "AUTO_EU"

        if out.get("vat_mode") != "STANDARD":
            out["vat_rate_percent"] = 0

        out["version"] = "v1"
        return out

    def list_invoice_templates(self) -> list[dict[str, Any]]:
        return [
            {
                "template_code": "EU_VAT_V1",
                "name": "EU VAT Invoice (v1)",
                "default_numbering_mode": "AUTO_EU",
                "description": "EU default invoice structure aligned with VAT directive required fields.",
                "legal_basis": ["EU VAT Directive 2006/112/EC Art. 226"],
            },
            {
                "template_code": "BG_VAT_V1",
                "name": "Bulgaria VAT Invoice (v1)",
                "default_numbering_mode": "BG_NUMERIC10",
                "description": "Bulgarian VAT profile with numeric serial invoice numbering.",
                "legal_basis": ["EU VAT Directive 2006/112/EC Art. 226", "Bulgarian VAT Act (ZDDS) Art. 114"],
            },
        ]

    def get_invoice_template_policy(self, db: Session, *, tenant_id: str) -> dict[str, Any]:
        tid = self._tenant_id(tenant_id)
        country_code = self._tenant_country_code(db, tenant_id=tid)
        base = self._default_policy_for_country(country_code)

        row = self._account_row(db, tid)
        policy_raw: dict[str, Any] = {}
        if row is not None and isinstance(row.metadata_json, dict):
            v = row.metadata_json.get("invoice_template_policy")
            if isinstance(v, dict):
                policy_raw = dict(v)

        policy = self._normalize_template_policy(policy_raw, base=base)
        suggested = "BG_VAT_V1" if country_code == "BG" else "EU_VAT_V1"
        return {
            "tenant_id": tid,
            "detected_country_code": country_code,
            "suggested_template_code": suggested,
            "policy": policy,
            "available_templates": self.list_invoice_templates(),
        }

    def set_invoice_template_policy(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        tid = self._tenant_id(tenant_id)
        if not self._tenant_exists(db, tid):
            raise ValueError("tenant_not_found")

        current = self.get_invoice_template_policy(db, tenant_id=tid)
        policy = self._normalize_template_policy(dict(payload or {}), base=dict(current.get("policy") or {}))

        row = self._ensure_account_row(db, tenant_id=tid, actor=actor)
        md = dict(row.metadata_json or {}) if isinstance(row.metadata_json, dict) else {}
        md["invoice_template_policy"] = policy
        row.metadata_json = md
        row.updated_by = str(actor or "unknown")
        row.updated_at = self._now()
        db.flush()

        out = self.get_invoice_template_policy(db, tenant_id=tid)
        out["policy"] = policy
        return out

    def _path_value(self, obj: Any, path: str) -> Any:
        cur = obj
        for part in str(path or "").split("."):
            name = part
            idx: int | None = None
            if "[" in part and part.endswith("]"):
                name, rest = part.split("[", 1)
                try:
                    idx = int(rest[:-1])
                except Exception:  # noqa: BLE001
                    return None
            if name:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(name)
            if idx is not None:
                if not isinstance(cur, list) or idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
        return cur

    def _required_fields_for_policy(self, policy: dict[str, Any]) -> list[str]:
        req = list(EU_REQUIRED_BASE)
        vat_mode = self._vat_mode(policy.get("vat_mode"), "STANDARD")
        if vat_mode == "STANDARD":
            req.append("tax.vat_rate_percent")
        else:
            req.append("tax.exemption_reason")
        if vat_mode == "REVERSE_CHARGE":
            req.append("tax.reverse_charge_note")

        if self._template_code(policy.get("template_code"), "EU_VAT_V1") == "BG_VAT_V1":
            req.extend(BG_EXTRA_REQUIRED)

        return req

    def _validate_required_fields(self, document: dict[str, Any], required_fields: list[str]) -> list[str]:
        missing: list[str] = []
        for path in required_fields:
            val = self._path_value(document, path)
            if path.endswith("number_numeric") or path.endswith("number_digits_valid"):
                if val is not True:
                    missing.append(path)
                continue
            if val is None:
                missing.append(path)
                continue
            if isinstance(val, str) and not val.strip():
                missing.append(path)
                continue
            if isinstance(val, list) and len(val) == 0:
                missing.append(path)
                continue
        return missing

