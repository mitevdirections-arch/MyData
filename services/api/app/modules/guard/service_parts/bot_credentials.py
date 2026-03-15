from __future__ import annotations

from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.settings import get_settings
from app.db.models import GuardBotCredential, GuardBotNonce, Incident


class GuardBotCredentialMixin:
    def _b64url_encode(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _derive_bot_signing_key(self, *, tenant_id: str, bot_id: str, key_version: int) -> bytes:
        s = get_settings()
        master = str(s.guard_bot_signing_master_secret or "").strip()
        if not master or master.startswith("change-me-"):
            raise ValueError("guard_bot_signing_master_secret_not_set")
        material = f"{tenant_id}:{bot_id}:v{int(key_version)}".encode("utf-8")
        return hmac.new(master.encode("utf-8"), material, hashlib.sha256).digest()

    def _canonical_bot_message(self, *, method: str, path: str, timestamp: int, nonce: str, body_bytes: bytes) -> bytes:
        body_sha = hashlib.sha256(body_bytes).hexdigest()
        canonical = f"{method.upper()}\n{path}\n{int(timestamp)}\n{str(nonce)}\n{body_sha}"
        return canonical.encode("utf-8")

    def _sign_bot_message(self, *, key: bytes, message: bytes) -> str:
        mac = hmac.new(key, message, hashlib.sha256).digest()
        return self._b64url_encode(mac)

    def _sanitize_bot_id(self, bot_id: str) -> str:
        raw = str(bot_id or "").strip()
        if not raw:
            raise ValueError("bot_id_required")
        return raw[:128]

    def _get_active_bot_credential(self, db: Session, *, tenant_id: str, bot_id: str) -> GuardBotCredential | None:
        bid = self._sanitize_bot_id(bot_id)
        return (
            db.query(GuardBotCredential)
            .filter(
                GuardBotCredential.tenant_id == tenant_id,
                GuardBotCredential.bot_id == bid,
                GuardBotCredential.status == "ACTIVE",
            )
            .first()
        )

    def issue_bot_credential(self, db: Session, *, tenant_id: str, actor: str, label: str | None = None) -> dict:
        now = self._now()
        bot_id = f"gbot-{uuid.uuid4().hex[:20]}"
        row = GuardBotCredential(
            tenant_id=tenant_id,
            bot_id=bot_id,
            label=(str(label).strip()[:255] if label else None),
            key_version=1,
            status="ACTIVE",
            created_by=str(actor or "unknown"),
            created_at=now,
        )
        db.add(row)
        db.flush()

        signing_key = self._derive_bot_signing_key(tenant_id=tenant_id, bot_id=bot_id, key_version=1)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "label": row.label,
            "key_version": 1,
            "algorithm": "HMAC-SHA256",
            "signing_secret": self._b64url_encode(signing_key),
            "status": "ACTIVE",
            "created_at": row.created_at.isoformat(),
        }

    def rotate_bot_credential(self, db: Session, *, tenant_id: str, bot_id: str, actor: str) -> dict:
        now = self._now()
        row = self._get_active_bot_credential(db, tenant_id=tenant_id, bot_id=bot_id)
        if row is None:
            raise ValueError("bot_credential_not_found")

        row.key_version = int(row.key_version) + 1
        row.rotated_at = now
        db.flush()

        signing_key = self._derive_bot_signing_key(tenant_id=tenant_id, bot_id=row.bot_id, key_version=int(row.key_version))
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "bot_id": row.bot_id,
            "label": row.label,
            "key_version": int(row.key_version),
            "algorithm": "HMAC-SHA256",
            "signing_secret": self._b64url_encode(signing_key),
            "status": row.status,
            "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
            "rotated_by": str(actor or "unknown"),
        }

    def revoke_bot_credential(self, db: Session, *, tenant_id: str, bot_id: str, actor: str) -> dict:
        now = self._now()
        row = self._get_active_bot_credential(db, tenant_id=tenant_id, bot_id=bot_id)
        if row is None:
            raise ValueError("bot_credential_not_found")

        row.status = "REVOKED"
        row.revoked_by = str(actor or "unknown")
        row.revoked_at = now
        db.flush()
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "bot_id": row.bot_id,
            "status": row.status,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "revoked_by": row.revoked_by,
        }

    def list_bot_credentials(self, db: Session, *, tenant_id: str, limit: int = 200) -> list[dict]:
        rows = (
            db.query(GuardBotCredential)
            .filter(GuardBotCredential.tenant_id == tenant_id)
            .order_by(GuardBotCredential.created_at.desc())
            .limit(max(1, min(int(limit), 1000)))
            .all()
        )
        out: list[dict] = []
        for x in rows:
            out.append(
                {
                    "tenant_id": x.tenant_id,
                    "bot_id": x.bot_id,
                    "label": x.label,
                    "key_version": int(x.key_version),
                    "status": x.status,
                    "failed_attempts": int(x.failed_attempts or 0),
                    "locked_until": x.locked_until.isoformat() if x.locked_until else None,
                    "last_failed_at": x.last_failed_at.isoformat() if x.last_failed_at else None,
                    "last_fail_reason": x.last_fail_reason,
                    "last_warning_at": x.last_warning_at.isoformat() if x.last_warning_at else None,
                    "created_by": x.created_by,
                    "created_at": x.created_at.isoformat() if x.created_at else None,
                    "last_seen_at": x.last_seen_at.isoformat() if x.last_seen_at else None,
                    "rotated_at": x.rotated_at.isoformat() if x.rotated_at else None,
                    "revoked_by": x.revoked_by,
                    "revoked_at": x.revoked_at.isoformat() if x.revoked_at else None,
                }
            )
        return out

    def _get_bot_credential_any(self, db: Session, *, tenant_id: str, bot_id: str) -> GuardBotCredential | None:
        bid = self._sanitize_bot_id(bot_id)
        return (
            db.query(GuardBotCredential)
            .filter(
                GuardBotCredential.tenant_id == tenant_id,
                GuardBotCredential.bot_id == bid,
            )
            .first()
        )

    def _create_lockout_warning(self, db: Session, *, tenant_id: str, bot_id: str, reason: str, locked_until: datetime) -> str:
        now = self._now()
        title = f"Guard Bot Lockout: {bot_id}"
        description = (
            f"Bot credential {bot_id} is locked until {locked_until.isoformat()} due to repeated auth failures. "
            f"Last reason: {reason}. Review bot integrity and rotate credentials before unlock."
        )
        row = Incident(
            tenant_id=tenant_id,
            status="OPEN",
            severity="CRITICAL",
            category="SECURITY",
            source="GUARD",
            title=title[:180],
            description=description[:5000],
            evidence_object_ids=[],
            created_by="guard-system",
            acknowledged_by=None,
            acknowledged_at=None,
            resolved_by=None,
            resolved_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        write_audit(
            db,
            action="guard.bot_lockout_warning_created",
            actor="guard-system",
            tenant_id=tenant_id,
            target=f"guard/bot/{bot_id}",
            metadata={"incident_id": str(row.id), "reason": reason, "locked_until": locked_until.isoformat()},
        )
        return str(row.id)

    def _register_bot_auth_failure(self, db: Session, *, tenant_id: str, bot_id: str, reason: str, actor: str) -> dict:
        now = self._now()
        row = self._get_bot_credential_any(db, tenant_id=tenant_id, bot_id=bot_id)
        if row is None:
            self.record_security_flag(
                db,
                tenant_id=tenant_id,
                reason=f"bot_auth_failed:{reason}",
                module_code=None,
                actor=actor,
                request_path="/guard/heartbeat",
                request_method="POST",
            )
            write_audit(
                db,
                action="guard.bot_auth_failed_unknown_credential",
                actor=actor,
                tenant_id=tenant_id,
                target=f"guard/bot/{bot_id}",
                metadata={"reason": reason},
            )
            db.commit()
            return {"locked": False, "reason": reason, "detail": "bot_credential_not_found"}

        row.failed_attempts = int(row.failed_attempts or 0) + 1
        row.last_failed_at = now
        row.last_fail_reason = str(reason)[:512]

        self.record_security_flag(
            db,
            tenant_id=tenant_id,
            reason=f"bot_auth_failed:{reason}",
            module_code=None,
            actor=actor,
            request_path="/guard/heartbeat",
            request_method="POST",
        )

        settings = get_settings()
        limit = max(1, int(settings.guard_bot_failed_signature_limit))
        lock_seconds = max(60, int(settings.guard_bot_lockout_seconds))

        warning_incident_id = None
        locked_now = False
        if int(row.failed_attempts) >= limit:
            row.locked_until = now + timedelta(seconds=lock_seconds)
            row.failed_attempts = 0
            row.last_warning_at = now
            warning_incident_id = self._create_lockout_warning(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason=reason,
                locked_until=row.locked_until,
            )
            locked_now = True
            write_audit(
                db,
                action="guard.bot_credential_locked",
                actor=actor,
                tenant_id=tenant_id,
                target=f"guard/bot/{row.bot_id}",
                metadata={
                    "reason": reason,
                    "lockout_until": row.locked_until.isoformat() if row.locked_until else None,
                    "warning_incident_id": warning_incident_id,
                },
            )
        else:
            write_audit(
                db,
                action="guard.bot_auth_failed",
                actor=actor,
                tenant_id=tenant_id,
                target=f"guard/bot/{row.bot_id}",
                metadata={
                    "reason": reason,
                    "failed_attempts": int(row.failed_attempts),
                    "failed_limit": limit,
                },
            )

        db.commit()
        return {
            "locked": bool(locked_now),
            "reason": reason,
            "warning_incident_id": warning_incident_id,
            "lockout_until": row.locked_until.isoformat() if row.locked_until else None,
        }

    def verify_bot_signature(
        self,
        db: Session,
        *,
        tenant_id: str,
        bot_id: str,
        key_version: int,
        timestamp: int,
        nonce: str,
        signature: str,
        method: str,
        path: str,
        body_bytes: bytes,
        actor: str,
    ) -> dict:
        now = self._now()
        s = get_settings()

        row = self._get_bot_credential_any(db, tenant_id=tenant_id, bot_id=bot_id)
        if row is None:
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=bot_id,
                reason="credential_not_found",
                actor=actor,
            )
            raise ValueError(str(fail.get("detail") or "bot_credential_not_found"))

        if row.status != "ACTIVE":
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason="credential_not_active",
                actor=actor,
            )
            raise ValueError("bot_credential_not_active")

        if row.locked_until is not None and row.locked_until > now:
            raise ValueError("bot_credential_locked")

        if int(key_version) != int(row.key_version):
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason="key_version_mismatch",
                actor=actor,
            )
            if bool(fail.get("locked")):
                raise ValueError("bot_credential_locked")
            raise ValueError("bot_key_version_mismatch")

        skew = abs(int(now.timestamp()) - int(timestamp))
        if skew > max(1, int(s.guard_bot_signature_max_skew_seconds)):
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason="timestamp_skew",
                actor=actor,
            )
            if bool(fail.get("locked")):
                raise ValueError("bot_credential_locked")
            raise ValueError("bot_signature_timestamp_skew")

        key = self._derive_bot_signing_key(tenant_id=tenant_id, bot_id=row.bot_id, key_version=int(row.key_version))
        message = self._canonical_bot_message(
            method=method,
            path=path,
            timestamp=int(timestamp),
            nonce=str(nonce),
            body_bytes=body_bytes,
        )
        expected = self._sign_bot_message(key=key, message=message)
        if not hmac.compare_digest(str(signature or "").strip(), expected):
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason="signature_invalid",
                actor=actor,
            )
            if bool(fail.get("locked")):
                raise ValueError("bot_credential_locked")
            raise ValueError("bot_signature_invalid")

        ttl = max(30, int(s.guard_bot_nonce_ttl_seconds))

        db.query(GuardBotNonce).filter(GuardBotNonce.expires_at < now).delete(synchronize_session=False)

        existing_nonce = (
            db.query(GuardBotNonce)
            .filter(
                GuardBotNonce.bot_id == row.bot_id,
                GuardBotNonce.nonce == str(nonce)[:128],
                GuardBotNonce.expires_at >= now,
            )
            .first()
        )
        if existing_nonce is not None:
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason="nonce_replay",
                actor=actor,
            )
            if bool(fail.get("locked")):
                raise ValueError("bot_credential_locked")
            raise ValueError("bot_nonce_replay")

        nonce_row = GuardBotNonce(
            tenant_id=tenant_id,
            bot_id=row.bot_id,
            nonce=str(nonce)[:128],
            used_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        db.add(nonce_row)
        try:
            db.flush()
        except IntegrityError:
            fail = self._register_bot_auth_failure(
                db,
                tenant_id=tenant_id,
                bot_id=row.bot_id,
                reason="nonce_replay_race",
                actor=actor,
            )
            if bool(fail.get("locked")):
                raise ValueError("bot_credential_locked")
            raise ValueError("bot_nonce_replay")

        row.last_seen_at = now
        row.failed_attempts = 0
        row.last_failed_at = None
        row.last_fail_reason = None
        db.flush()

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "bot_id": row.bot_id,
            "key_version": int(row.key_version),
            "verified_at": now.isoformat(),
        }


    def list_locked_bot_credentials(self, db: Session, *, tenant_id: str, limit: int = 200) -> list[dict]:
        now = self._now()
        rows = (
            db.query(GuardBotCredential)
            .filter(
                GuardBotCredential.tenant_id == tenant_id,
                GuardBotCredential.status == "ACTIVE",
                GuardBotCredential.locked_until.is_not(None),
                GuardBotCredential.locked_until > now,
            )
            .order_by(GuardBotCredential.locked_until.desc())
            .limit(max(1, min(int(limit), 1000)))
            .all()
        )
        return [
            {
                "tenant_id": x.tenant_id,
                "bot_id": x.bot_id,
                "label": x.label,
                "key_version": int(x.key_version),
                "locked_until": x.locked_until.isoformat() if x.locked_until else None,
                "last_fail_reason": x.last_fail_reason,
                "last_failed_at": x.last_failed_at.isoformat() if x.last_failed_at else None,
                "last_warning_at": x.last_warning_at.isoformat() if x.last_warning_at else None,
            }
            for x in rows
        ]

    def unlock_bot_credential(self, db: Session, *, tenant_id: str, bot_id: str, actor: str, note: str | None = None) -> dict:
        row = self._get_bot_credential_any(db, tenant_id=tenant_id, bot_id=bot_id)
        if row is None:
            raise ValueError("bot_credential_not_found")
        if row.status != "ACTIVE":
            raise ValueError("bot_credential_not_active")

        row.locked_until = None
        row.failed_attempts = 0
        row.last_fail_reason = None
        row.last_failed_at = None
        db.flush()

        write_audit(
            db,
            action="guard.bot_credential_unlocked",
            actor=actor,
            tenant_id=tenant_id,
            target=f"guard/bot/{row.bot_id}",
            metadata={"note": str(note or "").strip() or None},
        )
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "bot_id": row.bot_id,
            "status": row.status,
            "locked_until": None,
            "unlocked_by": actor,
        }

