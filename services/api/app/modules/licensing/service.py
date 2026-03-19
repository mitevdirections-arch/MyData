from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import uuid

from sqlalchemy import and_, bindparam, case, or_, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import DeviceLease, License, LicenseIssueRequest, LicenseIssuancePolicy, Tenant

CORE_PLAN_SEATS: dict[str, int] = {
    "CORE3": 3,
    "CORE5": 5,
    "CORE8": 8,
    "CORE13": 13,
    "CORE21": 21,
    "CORE24": 24,
    "CORE34": 34,
    "CORE45": 45,
}
UNLIMITED_CORE_PLANS: set[str] = {"COREENTERPRISE", "CORE_ENT"}
ALNUM_RE = re.compile(r"[^A-Z0-9]")
ISSUANCE_MODES = {"AUTO", "SEMI", "MANUAL"}
ENTITLEMENT_QUERY_MODE_ENV = "MYDATA_PERF_ENTITLEMENT_QUERY_MODE"
ENTITLEMENT_QUERY_MODE_CORE = "core"
ENTITLEMENT_QUERY_MODE_LEGACY = "legacy"

_RESOLVE_MODULE_ENTITLEMENT_STMT = (
    select(
        License.license_type,
        License.id,
        License.valid_to,
    )
    .where(
        License.tenant_id == bindparam("tenant_id"),
        License.status == bindparam("active_status"),
        License.valid_from <= bindparam("now_ts"),
        License.valid_to >= bindparam("now_ts"),
        or_(
            License.license_type == bindparam("startup_type"),
            and_(
                License.module_code == bindparam("module_code"),
                License.license_type != bindparam("core_type"),
                License.license_type != bindparam("startup_type"),
            ),
        ),
    )
    .order_by(
        case((License.license_type == bindparam("startup_type"), 0), else_=1),
        License.valid_to.desc(),
    )
    .limit(1)
)


class LicensingService:
    def _resolve_entitlement_query_mode(self) -> str:
        raw = str(os.getenv(ENTITLEMENT_QUERY_MODE_ENV, ENTITLEMENT_QUERY_MODE_LEGACY)).strip().lower()
        if raw == ENTITLEMENT_QUERY_MODE_CORE:
            return ENTITLEMENT_QUERY_MODE_CORE
        return ENTITLEMENT_QUERY_MODE_LEGACY

    def _resolve_module_entitlement_row_legacy(
        self,
        db: Session,
        *,
        tenant_id: str,
        module_code: str,
        now: datetime,
    ):
        return (
            db.query(
                License.license_type,
                License.id,
                License.valid_to,
            )
            .filter(
                License.tenant_id == tenant_id,
                License.status == "ACTIVE",
                License.valid_from <= now,
                License.valid_to >= now,
                or_(
                    License.license_type == "STARTUP",
                    and_(
                        License.module_code == module_code,
                        License.license_type != "CORE",
                        License.license_type != "STARTUP",
                    ),
                ),
            )
            .order_by(
                case((License.license_type == "STARTUP", 0), else_=1),
                License.valid_to.desc(),
            )
            .first()
        )

    def _resolve_module_entitlement_row_core(
        self,
        db: Session,
        *,
        tenant_id: str,
        module_code: str,
        now: datetime,
    ):
        row = db.execute(
            _RESOLVE_MODULE_ENTITLEMENT_STMT,
            {
                "tenant_id": tenant_id,
                "active_status": "ACTIVE",
                "now_ts": now,
                "startup_type": "STARTUP",
                "module_code": module_code,
                "core_type": "CORE",
            },
        )
        return row.first()

    def _active(self, now: datetime, record: License) -> bool:
        return record.status == "ACTIVE" and record.valid_from <= now <= record.valid_to

    def _normalize_core_plan(self, module_code: str | None) -> str:
        code = str(module_code or "CORE8").strip().upper()
        if code == "CORE_ENTERPRISE":
            return "COREENTERPRISE"
        return code

    def _seat_limit_for_plan(self, module_code: str | None) -> int | None:
        code = self._normalize_core_plan(module_code)
        if code in UNLIMITED_CORE_PLANS:
            return None
        return CORE_PLAN_SEATS.get(code)

    def get_active_core(self, db: Session, tenant_id: str) -> License | None:
        now = datetime.now(timezone.utc)
        return (
            db.query(License)
            .filter(
                License.tenant_id == tenant_id,
                License.license_type == "CORE",
                License.status == "ACTIVE",
                License.valid_from <= now,
                License.valid_to >= now,
            )
            .order_by(License.valid_to.desc())
            .first()
        )

    def get_active_startup(self, db: Session, tenant_id: str) -> License | None:
        now = datetime.now(timezone.utc)
        return (
            db.query(License)
            .filter(
                License.tenant_id == tenant_id,
                License.license_type == "STARTUP",
                License.status == "ACTIVE",
                License.valid_from <= now,
                License.valid_to >= now,
            )
            .order_by(License.valid_to.desc())
            .first()
        )

    def get_active_module_license(self, db: Session, tenant_id: str, module_code: str) -> License | None:
        now = datetime.now(timezone.utc)
        code = str(module_code or "").strip().upper()
        if not code:
            return None
        return (
            db.query(License)
            .filter(
                License.tenant_id == tenant_id,
                License.module_code == code,
                License.status == "ACTIVE",
                License.valid_from <= now,
                License.valid_to >= now,
                License.license_type != "CORE",
                License.license_type != "STARTUP",
            )
            .order_by(License.valid_to.desc())
            .first()
        )

    def get_nearest_active_license_expiry(self, db: Session, tenant_id: str) -> datetime | None:
        now = datetime.now(timezone.utc)
        row = (
            db.query(License)
            .filter(
                License.tenant_id == tenant_id,
                License.status == "ACTIVE",
                License.valid_to >= now,
            )
            .order_by(License.valid_to.asc())
            .first()
        )
        return row.valid_to if row is not None else None

    def resolve_core_entitlement(self, db: Session, tenant_id: str) -> dict:
        core = self.get_active_core(db, tenant_id)
        if core is None:
            return {
                "has_core": False,
                "plan_code": None,
                "seat_limit": None,
                "core_valid_to": None,
            }

        plan_code = self._normalize_core_plan(core.module_code)
        return {
            "has_core": True,
            "plan_code": plan_code,
            "seat_limit": self._seat_limit_for_plan(plan_code),
            "core_valid_to": core.valid_to.isoformat(),
        }

    def _resolve_core_entitlement_from_active_catalog(self, active_licenses: list[dict[str, Any]]) -> dict[str, Any]:
        core_row = next(
            (
                row
                for row in list(active_licenses or [])
                if str((row or {}).get("license_type") or "").strip().upper() == "CORE"
            ),
            None,
        )
        if core_row is None:
            return {
                "has_core": False,
                "plan_code": None,
                "seat_limit": None,
                "core_valid_to": None,
            }

        plan_code = self._normalize_core_plan((core_row or {}).get("module_code"))
        core_valid_to = str((core_row or {}).get("valid_to") or "").strip() or None
        return {
            "has_core": True,
            "plan_code": plan_code,
            "seat_limit": self._seat_limit_for_plan(plan_code),
            "core_valid_to": core_valid_to,
        }

    def resolve_module_entitlement(self, db: Session, tenant_id: str, module_code: str) -> dict:
        code = str(module_code or "").strip().upper()
        if not code:
            return {
                "allowed": False,
                "module_code": None,
                "reason": "module_code_required",
                "source": None,
                "valid_to": None,
            }

        now = datetime.now(timezone.utc)
        query_mode = self._resolve_entitlement_query_mode()
        try:
            if query_mode == ENTITLEMENT_QUERY_MODE_LEGACY:
                row = self._resolve_module_entitlement_row_legacy(
                    db,
                    tenant_id=tenant_id,
                    module_code=code,
                    now=now,
                )
            else:
                row = self._resolve_module_entitlement_row_core(
                    db,
                    tenant_id=tenant_id,
                    module_code=code,
                    now=now,
                )
        except Exception:  # noqa: BLE001
            # Fail-closed for entitlement data-plane errors.
            return {
                "allowed": False,
                "module_code": code,
                "reason": "module_license_required",
                "source": None,
                "valid_to": None,
            }

        if row is None:
            return {
                "allowed": False,
                "module_code": code,
                "reason": "module_license_required",
                "source": None,
                "valid_to": None,
            }

        license_type = str(row[0] or "").strip().upper()
        license_id = str(row[1])
        valid_to = row[2].isoformat() if row[2] else None

        if license_type == "STARTUP":
            return {
                "allowed": True,
                "module_code": code,
                "reason": "startup_full_access",
                "source": {
                    "license_type": license_type,
                    "license_id": license_id,
                },
                "valid_to": valid_to,
            }

        return {
            "allowed": True,
            "module_code": code,
            "reason": "module_license_active",
            "source": {
                "license_type": license_type,
                "license_id": license_id,
            },
            "valid_to": valid_to,
        }

    def _normalize_issuance_mode(self, mode: str | None) -> str:
        val = str(mode or "").strip().upper()
        return val if val in ISSUANCE_MODES else "SEMI"

    def get_issuance_policy(self, db: Session, *, tenant_id: str) -> dict:
        default_mode = self._normalize_issuance_mode(get_settings().license_issuance_default_mode)
        row = db.query(LicenseIssuancePolicy).filter(LicenseIssuancePolicy.tenant_id == tenant_id).first()
        if row is None:
            return {
                "tenant_id": tenant_id,
                "mode": default_mode,
                "source": "default",
                "updated_by": None,
                "updated_at": None,
            }

        mode = self._normalize_issuance_mode(row.mode)
        return {
            "tenant_id": tenant_id,
            "mode": mode,
            "source": "tenant_override",
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def set_issuance_policy(self, db: Session, *, tenant_id: str, mode: str, actor: str) -> dict:
        normalized = self._normalize_issuance_mode(mode)
        row = db.query(LicenseIssuancePolicy).filter(LicenseIssuancePolicy.tenant_id == tenant_id).first()
        if row is None:
            row = LicenseIssuancePolicy(
                tenant_id=tenant_id,
                mode=normalized,
                updated_by=str(actor or "unknown"),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(row)
        else:
            row.mode = normalized
            row.updated_by = str(actor or "unknown")
            row.updated_at = datetime.now(timezone.utc)
        db.flush()
        return {
            "tenant_id": tenant_id,
            "mode": normalized,
            "source": "tenant_override",
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _request_to_dict(self, row: LicenseIssueRequest) -> dict:
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "request_type": row.request_type,
            "status": row.status,
            "payload": row.payload_json or {},
            "result": row.result_json or {},
            "requested_by": row.requested_by,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "decision_note": row.decision_note,
            "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        }

    def _find_pending_request(self, db: Session, *, tenant_id: str, request_type: str) -> LicenseIssueRequest | None:
        return (
            db.query(LicenseIssueRequest)
            .filter(
                LicenseIssueRequest.tenant_id == tenant_id,
                LicenseIssueRequest.request_type == request_type,
                LicenseIssueRequest.status == "PENDING",
            )
            .order_by(LicenseIssueRequest.requested_at.desc())
            .first()
        )

    def create_issue_request(
        self,
        db: Session,
        *,
        tenant_id: str,
        request_type: str,
        requested_by: str,
        payload: dict | None = None,
    ) -> dict:
        pending = self._find_pending_request(db, tenant_id=tenant_id, request_type=request_type)
        if pending is not None:
            return self._request_to_dict(pending)

        row = LicenseIssueRequest(
            tenant_id=tenant_id,
            request_type=str(request_type),
            status="PENDING",
            payload_json=dict(payload or {}),
            result_json={},
            requested_by=str(requested_by or "unknown"),
            requested_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()
        return self._request_to_dict(row)

    def list_issue_requests(self, db: Session, *, tenant_id: str | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
        q = db.query(LicenseIssueRequest)
        if tenant_id:
            q = q.filter(LicenseIssueRequest.tenant_id == tenant_id)
        if status:
            q = q.filter(LicenseIssueRequest.status == str(status).strip().upper())

        rows = q.order_by(LicenseIssueRequest.requested_at.desc()).limit(max(1, min(int(limit), 1000))).all()
        return [self._request_to_dict(x) for x in rows]

    def request_startup_with_policy(
        self,
        db: Session,
        *,
        tenant_id: str,
        requested_by: str,
        admin_confirmed: bool = False,
        note: str | None = None,
    ) -> dict:
        existing_startup = db.query(License).filter(License.tenant_id == tenant_id, License.license_type == "STARTUP").first()
        if existing_startup is not None:
            raise ValueError("startup_non_renewable")

        policy = self.get_issuance_policy(db, tenant_id=tenant_id)
        mode = str(policy.get("mode") or "SEMI").upper()

        if mode == "AUTO" or (mode == "SEMI" and bool(admin_confirmed)):
            issued = self.issue_startup_with_core(db=db, tenant_id=tenant_id)
            return {
                "ok": True,
                "flow": "ISSUED",
                "mode": mode,
                "tenant_id": tenant_id,
                "issued": issued.get("issued") or [],
                "license_visual_codes": issued.get("license_visual_codes") or {},
            }

        request_payload = {
            "action": "ISSUE_STARTUP_CORE",
            "admin_confirmed": bool(admin_confirmed),
            "note": str(note or "").strip() or None,
        }
        req = self.create_issue_request(
            db,
            tenant_id=tenant_id,
            request_type="STARTUP_CORE",
            requested_by=str(requested_by or "unknown"),
            payload=request_payload,
        )
        return {
            "ok": True,
            "flow": "PENDING_APPROVAL",
            "mode": mode,
            "tenant_id": tenant_id,
            "request": req,
        }

    def approve_issue_request(self, db: Session, *, request_id: str, approved_by: str, note: str | None = None) -> dict:
        try:
            rid = uuid.UUID(str(request_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("request_id_invalid") from exc

        row = db.query(LicenseIssueRequest).filter(LicenseIssueRequest.id == rid).first()
        if row is None:
            raise ValueError("request_not_found")
        if row.status != "PENDING":
            raise ValueError("request_not_pending")

        if row.request_type != "STARTUP_CORE":
            raise ValueError("request_type_unsupported")

        issued = self.issue_startup_with_core(db=db, tenant_id=row.tenant_id)

        now = datetime.now(timezone.utc)
        row.status = "ISSUED"
        row.approved_by = str(approved_by or "unknown")
        row.approved_at = now
        row.decision_note = str(note or "").strip() or None
        row.processed_at = now
        row.result_json = {
            "issued": issued.get("issued") or [],
            "license_visual_codes": issued.get("license_visual_codes") or {},
        }
        db.commit()
        return {
            "ok": True,
            "request": self._request_to_dict(row),
            "issued": issued,
        }

    def reject_issue_request(self, db: Session, *, request_id: str, approved_by: str, note: str | None = None) -> dict:
        try:
            rid = uuid.UUID(str(request_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("request_id_invalid") from exc

        row = db.query(LicenseIssueRequest).filter(LicenseIssueRequest.id == rid).first()
        if row is None:
            raise ValueError("request_not_found")
        if row.status != "PENDING":
            raise ValueError("request_not_pending")

        now = datetime.now(timezone.utc)
        row.status = "REJECTED"
        row.approved_by = str(approved_by or "unknown")
        row.approved_at = now
        row.decision_note = str(note or "").strip() or None
        row.processed_at = now
        row.result_json = {"decision": "rejected"}
        db.flush()
        return {
            "ok": True,
            "request": self._request_to_dict(row),
        }

    def active_license_catalog(self, db: Session, *, tenant_id: str) -> list[dict]:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(License)
            .filter(
                License.tenant_id == tenant_id,
                License.status == "ACTIVE",
                License.valid_from <= now,
                License.valid_to >= now,
            )
            .order_by(License.valid_to.desc())
            .all()
        )
        vat = self._tenant_vat(db, tenant_id)
        out: list[dict] = []
        for r in rows:
            code = r.license_visual_code or self.build_license_visual_code(
                license_type=r.license_type,
                module_code=r.module_code,
                issued_at=r.created_at,
                vat_number=vat,
                internal_seed=str(r.id),
            )
            out.append(
                {
                    "id": str(r.id),
                    "license_type": r.license_type,
                    "module_code": r.module_code,
                    "license_visual_code": str(code).strip().upper(),
                    "valid_to": r.valid_to.isoformat(),
                }
            )
        return out

    def verify_client_license_snapshot(self, db: Session, *, tenant_id: str, active_license_codes: list[str]) -> dict:
        max_codes = max(1, int(get_settings().guard_license_snapshot_max_codes))
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in list(active_license_codes or []):
            val = str(raw or "").strip().upper()
            if not val:
                continue
            if val in seen:
                continue
            seen.add(val)
            normalized.append(val)
            if len(normalized) > max_codes:
                raise ValueError("license_snapshot_too_large")

        issued_items = self.active_license_catalog(db, tenant_id=tenant_id)
        issued_map = {str(x.get("license_visual_code") or "").upper(): x for x in issued_items}

        issued_codes = set(issued_map.keys())
        client_codes = set(normalized)

        unknown_codes = sorted(client_codes - issued_codes)
        missing_issued_codes = sorted(issued_codes - client_codes)

        expected_core_codes = {
            code
            for code, item in issued_map.items()
            if str(item.get("license_type") or "").upper() == "CORE"
        }
        core_present_in_client_snapshot = (len(expected_core_codes) == 0) or any(code in client_codes for code in expected_core_codes)

        ok = len(unknown_codes) == 0 and core_present_in_client_snapshot

        return {
            "ok": ok,
            "tenant_id": tenant_id,
            "client_codes_count": len(client_codes),
            "issued_active_count": len(issued_codes),
            "unknown_codes": unknown_codes,
            "missing_issued_codes": missing_issued_codes,
            "core_present_in_client_snapshot": bool(core_present_in_client_snapshot),
            "expected_core_codes": sorted(expected_core_codes),
        }

    def count_active_leased_users(self, db: Session, tenant_id: str, *, exclude_user_id: str | None = None) -> int:
        q = db.query(DeviceLease).filter(DeviceLease.tenant_id == tenant_id, DeviceLease.is_active == True)  # noqa: E712
        if exclude_user_id:
            q = q.filter(DeviceLease.user_id != exclude_user_id)
        return int(q.count())

    def assert_seat_available(self, db: Session, *, tenant_id: str, user_id: str, exclude_user_id: str | None = None) -> dict:
        entitlement = self.resolve_core_entitlement(db, tenant_id)
        if not entitlement["has_core"]:
            raise ValueError("core_required")

        seat_limit = entitlement["seat_limit"]
        used = self.count_active_leased_users(db, tenant_id, exclude_user_id=exclude_user_id)

        if seat_limit is not None and used >= int(seat_limit):
            raise ValueError("core_seat_limit_exceeded")

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "plan_code": entitlement["plan_code"],
            "seat_limit": seat_limit,
            "active_users_used": used,
            "active_users_after_lease": used + 1,
            "core_valid_to": entitlement["core_valid_to"],
        }

    def _tenant_vat(self, db: Session, tenant_id: str) -> str | None:
        row = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        return row.vat_number if row is not None else None

    def _vat_prefix4(self, vat_number: str | None) -> str:
        cleaned = ALNUM_RE.sub("", str(vat_number or "").upper())
        if not cleaned:
            return "0000"
        return (cleaned + "0000")[:4]

    def _module_label(self, license_type: str, module_code: str | None) -> str:
        label = str(module_code or license_type or "LIC").upper().strip()
        label = ALNUM_RE.sub("", label)
        return label or "LIC"

    def _ours_tag4(self, seed: str) -> str:
        cleaned = ALNUM_RE.sub("", seed.upper())
        if len(cleaned) >= 4:
            return cleaned[-4:]
        return (cleaned + "X000")[:4]

    def build_license_visual_code(
        self,
        *,
        license_type: str,
        module_code: str | None,
        issued_at: datetime,
        vat_number: str | None,
        internal_seed: str,
    ) -> str:
        label = self._module_label(license_type, module_code)
        vat4 = self._vat_prefix4(vat_number)
        date_part = issued_at.astimezone(timezone.utc).strftime("%Y%m%d")
        ours4 = self._ours_tag4(internal_seed)
        return f"LIC-{label}-{date_part}-{vat4}-{ours4}"

    def render_license_visual(
        self,
        *,
        license_type: str,
        module_code: str | None,
        issued_at: datetime,
        vat_number: str | None,
        internal_seed: str,
        valid_to: datetime | None,
    ) -> dict:
        code = self.build_license_visual_code(
            license_type=license_type,
            module_code=module_code,
            issued_at=issued_at,
            vat_number=vat_number,
            internal_seed=internal_seed,
        )
        return {
            "code": code,
            "parts": {
                "license_or_module": self._module_label(license_type, module_code),
                "issue_date": issued_at.astimezone(timezone.utc).strftime("%Y-%m-%d"),
                "vat4": self._vat_prefix4(vat_number),
                "ours4": self._ours_tag4(internal_seed),
            },
            "card": {
                "title": f"{self._module_label(license_type, module_code)} License",
                "issued_at": issued_at.isoformat(),
                "valid_to": valid_to.isoformat() if valid_to else None,
                "vat_preview": self._vat_prefix4(vat_number),
                "code": code,
            },
        }

    def preview_visual_code(
        self,
        db: Session,
        *,
        tenant_id: str,
        license_type: str,
        module_code: str | None,
        vat_number: str | None,
        issued_at: datetime | None,
        internal_mark: str | None,
    ) -> dict:
        vat = vat_number if vat_number is not None else self._tenant_vat(db, tenant_id)
        ts = issued_at or datetime.now(timezone.utc)
        seed = internal_mark or str(uuid.uuid4())
        return self.render_license_visual(
            license_type=license_type,
            module_code=module_code,
            issued_at=ts,
            vat_number=vat,
            internal_seed=seed,
            valid_to=None,
        )

    def list_active(self, db: Session, tenant_id: str) -> list[dict]:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(License)
            .filter(License.tenant_id == tenant_id, License.status == "ACTIVE")
            .order_by(License.valid_to.desc())
            .all()
        )
        vat = self._tenant_vat(db, tenant_id)

        out: list[dict] = []
        for r in rows:
            if not self._active(now, r):
                continue
            visual_code = r.license_visual_code or self.build_license_visual_code(
                license_type=r.license_type,
                module_code=r.module_code,
                issued_at=r.created_at,
                vat_number=vat,
                internal_seed=str(r.id),
            )
            out.append(
                {
                    "id": str(r.id),
                    "tenant_id": r.tenant_id,
                    "license_type": r.license_type,
                    "module_code": r.module_code,
                    "valid_to": r.valid_to.isoformat(),
                    "license_visual_code": visual_code,
                    "visual": self.render_license_visual(
                        license_type=r.license_type,
                        module_code=r.module_code,
                        issued_at=r.created_at,
                        vat_number=vat,
                        internal_seed=str(r.id),
                        valid_to=r.valid_to,
                    ),
                }
            )
        return out

    def issue_startup_with_core(self, db: Session, tenant_id: str, days: int = 30) -> dict:
        now = datetime.now(timezone.utc)
        existing_startup = db.query(License).filter(License.tenant_id == tenant_id, License.license_type == "STARTUP").first()
        if existing_startup is not None:
            raise ValueError("startup_non_renewable")

        valid_to = now + timedelta(days=days)
        vat = self._tenant_vat(db, tenant_id)

        startup_id = uuid.uuid4()
        core_id = uuid.uuid4()

        startup = License(
            id=startup_id,
            tenant_id=tenant_id,
            license_type="STARTUP",
            status="ACTIVE",
            module_code=None,
            license_visual_code=self.build_license_visual_code(
                license_type="STARTUP",
                module_code=None,
                issued_at=now,
                vat_number=vat,
                internal_seed=str(startup_id),
            ),
            valid_from=now,
            valid_to=valid_to,
        )
        core = License(
            id=core_id,
            tenant_id=tenant_id,
            license_type="CORE",
            status="ACTIVE",
            module_code="CORE8",
            license_visual_code=self.build_license_visual_code(
                license_type="CORE",
                module_code="CORE8",
                issued_at=now,
                vat_number=vat,
                internal_seed=str(core_id),
            ),
            valid_from=now,
            valid_to=valid_to,
        )

        db.add(startup)
        db.add(core)
        db.commit()
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "issued": ["STARTUP", "CORE"],
            "license_visual_codes": {
                "STARTUP": startup.license_visual_code,
                "CORE": core.license_visual_code,
            },
        }


    def issue_core_only(self, db: Session, *, tenant_id: str, plan_code: str = "CORE8", days: int = 30) -> dict:
        tid = str(tenant_id or "").strip()
        if not tid:
            raise ValueError("tenant_id_required")
        if db.query(Tenant.id).filter(Tenant.id == tid).first() is None:
            raise ValueError("tenant_not_found")

        plan = self._normalize_core_plan(plan_code)
        if plan not in CORE_PLAN_SEATS and plan not in UNLIMITED_CORE_PLANS:
            raise ValueError("core_plan_invalid")

        now = datetime.now(timezone.utc)
        valid_days = max(1, min(int(days), 3650))

        existing_active = (
            db.query(License)
            .filter(
                License.tenant_id == tid,
                License.license_type == "CORE",
                License.status == "ACTIVE",
                License.valid_to >= now,
            )
            .order_by(License.valid_to.desc())
            .first()
        )
        if existing_active is not None:
            raise ValueError("core_already_active")

        lid = uuid.uuid4()
        vat = self._tenant_vat(db, tid)
        row = License(
            id=lid,
            tenant_id=tid,
            license_type="CORE",
            status="ACTIVE",
            module_code=plan,
            license_visual_code=self.build_license_visual_code(
                license_type="CORE",
                module_code=plan,
                issued_at=now,
                vat_number=vat,
                internal_seed=str(lid),
            ),
            valid_from=now,
            valid_to=now + timedelta(days=valid_days),
        )
        db.add(row)
        db.commit()
        return {
            "ok": True,
            "tenant_id": tid,
            "issued": ["CORE"],
            "license": {
                "license_id": str(row.id),
                "license_type": row.license_type,
                "module_code": row.module_code,
                "license_visual_code": row.license_visual_code,
                "valid_from": row.valid_from.isoformat(),
                "valid_to": row.valid_to.isoformat(),
            },
        }

    def issue_module_trial(self, db: Session, tenant_id: str, module_code: str, days: int = 14) -> dict:
        now = datetime.now(timezone.utc)
        core = self.get_active_core(db, tenant_id)
        if core is None or not self._active(now, core):
            raise ValueError("core_required")

        vat = self._tenant_vat(db, tenant_id)
        mid = uuid.uuid4()
        row = License(
            id=mid,
            tenant_id=tenant_id,
            license_type="MODULE_TRIAL",
            status="ACTIVE",
            module_code=module_code,
            license_visual_code=self.build_license_visual_code(
                license_type="MODULE_TRIAL",
                module_code=module_code,
                issued_at=now,
                vat_number=vat,
                internal_seed=str(mid),
            ),
            valid_from=now,
            valid_to=now + timedelta(days=days),
        )
        db.add(row)
        db.commit()
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "module_code": module_code,
            "license_visual_code": row.license_visual_code,
        }

    def entitlement_snapshot_v2(self, db: Session, *, tenant_id: str) -> dict:
        active = self.active_license_catalog(db=db, tenant_id=tenant_id)
        core = self._resolve_core_entitlement_from_active_catalog(active)

        startup_active = any(str(x.get("license_type") or "").upper() == "STARTUP" for x in active)
        active_module_codes = sorted(
            {
                str(x.get("module_code") or "").strip().upper()
                for x in active
                if str(x.get("module_code") or "").strip()
            }
        )

        payload = {
            "version": "v2",
            "tenant_id": tenant_id,
            "core": core,
            "startup_active": startup_active,
            "active_module_codes": active_module_codes,
            "active_licenses": active,
        }
        canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["hash_sha256"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        return payload

service = LicensingService()
