from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth import create_access_token
from app.core.settings import get_settings
from app.db.models import SupportFaqEntry, SupportMessage, SupportRequest, SupportSession

ALLOWED_REQUEST_STATUS = {"NEW", "DOOR_OPEN", "SESSION_ACTIVE", "CLOSED", "EXPIRED", "REJECTED"}
ALLOWED_SESSION_STATUS = {"ACTIVE", "ENDED", "REVOKED", "EXPIRED"}
ALLOWED_CHANNELS = {"LIVE_ACCESS", "CHAT_HUMAN", "CHAT_BOT", "EMAIL", "FAQ"}
ALLOWED_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_MESSAGE_CHANNELS = {"CHAT_HUMAN", "CHAT_BOT", "EMAIL"}
ALLOWED_FAQ_STATUS = {"DRAFT", "PUBLISHED", "ARCHIVED"}


class SupportService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _uuid_or_err(self, raw: str, *, err: str) -> UUID:
        try:
            return UUID(str(raw))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(err) from exc

    def _clean_text(self, value: Any, max_len: int) -> str:
        return str(value or "").strip()[:max_len]

    def _normalize_status(self, value: str | None) -> str:
        out = str(value or "").strip().upper()
        if not out:
            return ""
        if out not in ALLOWED_REQUEST_STATUS:
            raise ValueError("support_request_status_invalid")
        return out

    def _normalize_session_status(self, value: str | None) -> str:
        out = str(value or "").strip().upper()
        if not out:
            return ""
        if out not in ALLOWED_SESSION_STATUS:
            raise ValueError("support_session_status_invalid")
        return out

    def _normalize_channel(self, value: str | None) -> str:
        out = str(value or "LIVE_ACCESS").strip().upper()
        if out not in ALLOWED_CHANNELS:
            raise ValueError("support_channel_invalid")
        return out

    def _normalize_priority(self, value: str | None) -> str:
        out = str(value or "MEDIUM").strip().upper()
        if out not in ALLOWED_PRIORITIES:
            raise ValueError("support_priority_invalid")
        return out

    def _normalize_message_channel(self, value: str | None, *, default: str = "CHAT_HUMAN") -> str:
        out = str(value or default).strip().upper()
        if out not in ALLOWED_MESSAGE_CHANNELS:
            raise ValueError("support_message_channel_invalid")
        return out

    def _normalize_faq_status(self, value: str | None, *, default: str = "PUBLISHED") -> str:
        out = str(value or default).strip().upper()
        if out not in ALLOWED_FAQ_STATUS:
            raise ValueError("support_faq_status_invalid")
        return out

    def _normalize_locale(self, value: str | None, *, default: str = "en") -> str:
        out = self._clean_text(value or default, 32).lower()
        return out or default

    def _normalize_limit(self, value: int | None, *, default: int = 200) -> int:
        max_limit = max(1, int(get_settings().support_messages_list_limit_max))
        raw = int(value if value is not None else default)
        return max(1, min(raw, max_limit))

    def _door_minutes(self, raw_minutes: Any | None) -> int:
        s = get_settings()
        default_minutes = max(5, int(s.support_door_open_default_minutes))
        max_minutes = max(default_minutes, int(s.support_door_open_max_minutes))
        if raw_minutes is None:
            return default_minutes
        val = int(raw_minutes)
        if val < 5:
            return 5
        if val > max_minutes:
            return max_minutes
        return val

    def _session_minutes(self, raw_minutes: Any | None) -> int:
        s = get_settings()
        default_minutes = max(5, int(s.support_session_ttl_minutes))
        max_minutes = max(default_minutes, int(s.support_session_ttl_max_minutes))
        if raw_minutes is None:
            return default_minutes
        val = int(raw_minutes)
        if val < 5:
            return 5
        if val > max_minutes:
            return max_minutes
        return val

    def _expire_due(self, db: Session, *, tenant_id: str | None = None) -> None:
        now = self._now()

        req_q = db.query(SupportRequest).filter(SupportRequest.status == "DOOR_OPEN", SupportRequest.door_expires_at.isnot(None), SupportRequest.door_expires_at < now)
        if tenant_id:
            req_q = req_q.filter(SupportRequest.tenant_id == tenant_id)
        req_q.update(
            {
                SupportRequest.status: "EXPIRED",
                SupportRequest.updated_at: now,
                SupportRequest.close_reason: "door_expired",
            },
            synchronize_session=False,
        )

        ses_q = db.query(SupportSession).filter(SupportSession.status == "ACTIVE", SupportSession.expires_at < now)
        if tenant_id:
            ses_q = ses_q.filter(SupportSession.tenant_id == tenant_id)
        ses_q.update(
            {
                SupportSession.status: "EXPIRED",
                SupportSession.ended_at: now,
                SupportSession.end_reason: "session_expired",
                SupportSession.updated_at: now,
            },
            synchronize_session=False,
        )

        stale_req_q = db.query(SupportRequest).filter(SupportRequest.status == "SESSION_ACTIVE")
        if tenant_id:
            stale_req_q = stale_req_q.filter(SupportRequest.tenant_id == tenant_id)
        stale_reqs = stale_req_q.all()
        for req in stale_reqs:
            active = (
                db.query(SupportSession)
                .filter(
                    SupportSession.request_id == req.id,
                    SupportSession.status == "ACTIVE",
                    SupportSession.expires_at >= now,
                )
                .first()
            )
            if active is None:
                req.status = "EXPIRED"
                req.updated_at = now
                if not req.close_reason:
                    req.close_reason = "session_expired"

        db.flush()

    def _request_to_dict(self, row: SupportRequest) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "status": row.status,
            "channel": row.channel,
            "priority": row.priority,
            "title": row.title,
            "description": row.description,
            "requested_by": row.requested_by,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "door_opened_by": row.door_opened_by,
            "door_opened_at": row.door_opened_at.isoformat() if row.door_opened_at else None,
            "door_expires_at": row.door_expires_at.isoformat() if row.door_expires_at else None,
            "session_started_by": row.session_started_by,
            "session_started_at": row.session_started_at.isoformat() if row.session_started_at else None,
            "closed_by": row.closed_by,
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
            "close_reason": row.close_reason,
            "metadata": row.metadata_json or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _session_to_dict(self, row: SupportSession) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "request_id": str(row.request_id),
            "tenant_id": row.tenant_id,
            "status": row.status,
            "started_by": row.started_by,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "ended_by": row.ended_by,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "end_reason": row.end_reason,
            "capabilities": row.capabilities_json or [],
            "metadata": row.metadata_json or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _message_to_dict(self, row: SupportMessage) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "request_id": str(row.request_id),
            "tenant_id": row.tenant_id,
            "session_id": (str(row.session_id) if row.session_id else None),
            "channel": row.channel,
            "sender_type": row.sender_type,
            "sender_id": row.sender_id,
            "body": row.body,
            "metadata": row.metadata_json or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _faq_to_dict(self, row: SupportFaqEntry) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "locale": row.locale,
            "category": row.category,
            "status": row.status,
            "sort_order": int(row.sort_order),
            "question": row.question,
            "answer": row.answer,
            "tags": row.tags_json or [],
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _ensure_request_message_open(self, row: SupportRequest) -> None:
        if row.status in {"CLOSED", "REJECTED", "EXPIRED"}:
            raise ValueError("support_request_closed")

    def create_request(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._expire_due(db, tenant_id=tenant_id)
        now = self._now()

        title = self._clean_text(payload.get("title"), 180)
        description = self._clean_text(payload.get("description"), 5000)
        if len(title) < 5:
            raise ValueError("support_title_too_short")
        if len(description) < 10:
            raise ValueError("support_description_too_short")

        channel = self._normalize_channel(payload.get("channel"))
        priority = self._normalize_priority(payload.get("priority"))
        door_open = bool(payload.get("door_open", True))

        req = SupportRequest(
            tenant_id=tenant_id,
            status="DOOR_OPEN" if door_open else "NEW",
            channel=channel,
            priority=priority,
            title=title,
            description=description,
            requested_by=str(actor or "unknown"),
            requested_at=now,
            door_opened_by=(str(actor or "unknown") if door_open else None),
            door_opened_at=(now if door_open else None),
            door_expires_at=(now + timedelta(minutes=self._door_minutes(payload.get("door_open_minutes"))) if door_open else None),
            session_started_by=None,
            session_started_at=None,
            closed_by=None,
            closed_at=None,
            close_reason=None,
            metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),
            updated_at=now,
        )
        db.add(req)
        db.flush()
        return self._request_to_dict(req)

    def list_tenant_requests(self, db: Session, *, tenant_id: str, status: str | None, limit: int = 200) -> list[dict[str, Any]]:
        self._expire_due(db, tenant_id=tenant_id)
        q = db.query(SupportRequest).filter(SupportRequest.tenant_id == tenant_id)
        status_norm = self._normalize_status(status)
        if status_norm:
            q = q.filter(SupportRequest.status == status_norm)
        rows = q.order_by(SupportRequest.requested_at.desc()).limit(max(1, min(int(limit), 1000))).all()
        return [self._request_to_dict(x) for x in rows]

    def list_super_requests(self, db: Session, *, status: str | None, tenant_id: str | None, limit: int = 300) -> list[dict[str, Any]]:
        self._expire_due(db)
        q = db.query(SupportRequest)
        if tenant_id:
            q = q.filter(SupportRequest.tenant_id == str(tenant_id).strip())
        status_norm = self._normalize_status(status)
        if status_norm:
            q = q.filter(SupportRequest.status == status_norm)
        rows = q.order_by(SupportRequest.requested_at.desc()).limit(max(1, min(int(limit), 2000))).all()
        return [self._request_to_dict(x) for x in rows]

    def _get_request(self, db: Session, *, request_id: str, tenant_id: str | None = None) -> SupportRequest:
        rid = self._uuid_or_err(request_id, err="support_request_id_invalid")
        q = db.query(SupportRequest).filter(SupportRequest.id == rid)
        if tenant_id:
            q = q.filter(SupportRequest.tenant_id == tenant_id)
        row = q.first()
        if row is None:
            raise ValueError("support_request_not_found")
        return row

    def open_door(self, db: Session, *, request_id: str, tenant_id: str, actor: str, door_open_minutes: int | None = None) -> dict[str, Any]:
        self._expire_due(db, tenant_id=tenant_id)
        row = self._get_request(db, request_id=request_id, tenant_id=tenant_id)
        if row.status in {"CLOSED", "REJECTED"}:
            raise ValueError("support_request_not_openable")

        now = self._now()
        row.status = "DOOR_OPEN"
        row.door_opened_by = str(actor or "unknown")
        row.door_opened_at = now
        row.door_expires_at = now + timedelta(minutes=self._door_minutes(door_open_minutes))
        row.close_reason = None
        row.updated_at = now
        db.flush()
        return self._request_to_dict(row)

    def close_request(self, db: Session, *, request_id: str, tenant_id: str, actor: str, reason: str | None = None) -> dict[str, Any]:
        self._expire_due(db, tenant_id=tenant_id)
        row = self._get_request(db, request_id=request_id, tenant_id=tenant_id)

        now = self._now()
        row.status = "CLOSED"
        row.closed_by = str(actor or "unknown")
        row.closed_at = now
        row.close_reason = self._clean_text(reason, 1024) or "closed_by_tenant"
        row.updated_at = now

        active_sessions = (
            db.query(SupportSession)
            .filter(
                SupportSession.request_id == row.id,
                SupportSession.status == "ACTIVE",
            )
            .all()
        )
        for s in active_sessions:
            s.status = "REVOKED"
            s.ended_by = str(actor or "unknown")
            s.ended_at = now
            s.end_reason = "door_closed_by_tenant"
            s.updated_at = now

        db.flush()
        return self._request_to_dict(row)

    def start_session(
        self,
        db: Session,
        *,
        request_id: str,
        actor: str,
        ttl_minutes: int | None,
        capabilities: list[str] | None,
    ) -> dict[str, Any]:
        self._expire_due(db)
        row = self._get_request(db, request_id=request_id)
        now = self._now()

        if row.status not in {"DOOR_OPEN", "SESSION_ACTIVE"}:
            raise ValueError("support_request_door_not_open")
        if row.door_expires_at is not None and row.door_expires_at < now:
            row.status = "EXPIRED"
            row.close_reason = "door_expired"
            row.updated_at = now
            db.flush()
            raise ValueError("support_request_door_expired")

        current = (
            db.query(SupportSession)
            .filter(
                SupportSession.request_id == row.id,
                SupportSession.status == "ACTIVE",
                SupportSession.expires_at >= now,
            )
            .order_by(SupportSession.started_at.desc())
            .first()
        )
        if current is not None:
            return {
                "request": self._request_to_dict(row),
                "session": self._session_to_dict(current),
            }

        minutes = self._session_minutes(ttl_minutes)
        requested_exp = now + timedelta(minutes=minutes)
        session_exp = min(requested_exp, row.door_expires_at) if row.door_expires_at is not None else requested_exp
        if session_exp <= now:
            raise ValueError("support_request_door_expired")

        clean_caps: list[str] = []
        seen: set[str] = set()
        for raw in list(capabilities or []):
            val = self._clean_text(str(raw).upper(), 64)
            if not val or val in seen:
                continue
            seen.add(val)
            clean_caps.append(val)

        session = SupportSession(
            request_id=row.id,
            tenant_id=row.tenant_id,
            status="ACTIVE",
            started_by=str(actor or "unknown"),
            started_at=now,
            expires_at=session_exp,
            ended_by=None,
            ended_at=None,
            end_reason=None,
            capabilities_json=clean_caps,
            metadata_json={},
            updated_at=now,
        )
        db.add(session)

        row.status = "SESSION_ACTIVE"
        row.session_started_by = str(actor or "unknown")
        row.session_started_at = now
        row.updated_at = now

        db.flush()
        return {
            "request": self._request_to_dict(row),
            "session": self._session_to_dict(session),
        }

    def list_sessions(self, db: Session, *, status: str | None, tenant_id: str | None, limit: int = 300) -> list[dict[str, Any]]:
        self._expire_due(db, tenant_id=tenant_id)
        q = db.query(SupportSession)
        if tenant_id:
            q = q.filter(SupportSession.tenant_id == str(tenant_id).strip())
        status_norm = self._normalize_session_status(status)
        if status_norm:
            q = q.filter(SupportSession.status == status_norm)
        rows = q.order_by(SupportSession.started_at.desc()).limit(max(1, min(int(limit), 2000))).all()
        return [self._session_to_dict(x) for x in rows]

    def _get_session(self, db: Session, *, session_id: str) -> SupportSession:
        sid = self._uuid_or_err(session_id, err="support_session_id_invalid")
        row = db.query(SupportSession).filter(SupportSession.id == sid).first()
        if row is None:
            raise ValueError("support_session_not_found")
        return row

    def end_session(self, db: Session, *, session_id: str, actor: str, reason: str | None = None) -> dict[str, Any]:
        self._expire_due(db)
        row = self._get_session(db, session_id=session_id)
        now = self._now()

        if row.status != "ACTIVE":
            return self._session_to_dict(row)

        row.status = "ENDED"
        row.ended_by = str(actor or "unknown")
        row.ended_at = now
        row.end_reason = self._clean_text(reason, 1024) or "closed_by_superadmin"
        row.updated_at = now

        req = db.query(SupportRequest).filter(SupportRequest.id == row.request_id).first()
        if req is not None and req.status == "SESSION_ACTIVE":
            req.status = "CLOSED"
            req.closed_by = str(actor or "unknown")
            req.closed_at = now
            req.close_reason = "session_closed_by_superadmin"
            req.updated_at = now

        db.flush()
        return self._session_to_dict(row)

    def issue_session_token(self, db: Session, *, session_id: str, actor: str) -> dict[str, Any]:
        self._expire_due(db)
        row = self._get_session(db, session_id=session_id)
        now = self._now()
        if row.status != "ACTIVE" or row.expires_at <= now:
            raise ValueError("support_session_invalid_or_expired")

        max_ttl = max(60, int(get_settings().support_token_ttl_seconds))
        remaining = int((row.expires_at - now).total_seconds())
        ttl = max(30, min(max_ttl, remaining))

        claims = {
            "sub": str(actor or "unknown"),
            "roles": ["SUPERADMIN"],
            "tenant_id": row.tenant_id,
            "support_tenant_id": row.tenant_id,
            "support_session_id": str(row.id),
            "support_request_id": str(row.request_id),
            "support_mode": "LIVE_ACCESS",
        }
        token = create_access_token(claims, ttl_seconds=ttl)

        row.updated_at = now
        db.flush()

        return {
            "ok": True,
            "tenant_id": row.tenant_id,
            "support_session_id": str(row.id),
            "support_request_id": str(row.request_id),
            "expires_in_seconds": ttl,
            "access_token": token,
            "token_type": "bearer",
        }

    def _resolve_optional_session_id(self, db: Session, *, request_id: UUID, tenant_id: str, session_id: str | None) -> UUID | None:
        sid_raw = str(session_id or "").strip()
        if not sid_raw:
            return None
        sid = self._uuid_or_err(sid_raw, err="support_session_id_invalid")
        row = (
            db.query(SupportSession)
            .filter(
                SupportSession.id == sid,
                SupportSession.request_id == request_id,
                SupportSession.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("support_session_not_found")
        return sid

    def add_tenant_message(self, db: Session, *, tenant_id: str, request_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._expire_due(db, tenant_id=tenant_id)
        req = self._get_request(db, request_id=request_id, tenant_id=tenant_id)
        self._ensure_request_message_open(req)

        max_chars = int(get_settings().support_chat_max_message_chars)
        body = self._clean_text(payload.get("body"), max_chars)
        if not body:
            raise ValueError("support_message_body_required")

        channel = self._normalize_message_channel(payload.get("channel"), default="CHAT_HUMAN")
        if channel == "CHAT_BOT":
            raise ValueError("support_bot_endpoint_required")

        sid = self._resolve_optional_session_id(db, request_id=req.id, tenant_id=tenant_id, session_id=payload.get("session_id"))
        row = SupportMessage(
            request_id=req.id,
            tenant_id=tenant_id,
            session_id=sid,
            channel=channel,
            sender_type="TENANT_ADMIN",
            sender_id=str(actor or "unknown"),
            body=body,
            metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),
            created_at=self._now(),
        )
        db.add(row)
        req.updated_at = self._now()
        db.flush()
        return self._message_to_dict(row)

    def add_superadmin_message(self, db: Session, *, request_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._expire_due(db)
        req = self._get_request(db, request_id=request_id)
        self._ensure_request_message_open(req)

        max_chars = int(get_settings().support_chat_max_message_chars)
        body = self._clean_text(payload.get("body"), max_chars)
        if not body:
            raise ValueError("support_message_body_required")

        channel = self._normalize_message_channel(payload.get("channel"), default="CHAT_HUMAN")
        sid = self._resolve_optional_session_id(db, request_id=req.id, tenant_id=req.tenant_id, session_id=payload.get("session_id"))

        row = SupportMessage(
            request_id=req.id,
            tenant_id=req.tenant_id,
            session_id=sid,
            channel=channel,
            sender_type="SUPERADMIN",
            sender_id=str(actor or "unknown"),
            body=body,
            metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),
            created_at=self._now(),
        )
        db.add(row)
        req.updated_at = self._now()
        db.flush()
        return self._message_to_dict(row)

    def list_messages(self, db: Session, *, request_id: str, tenant_id: str | None, limit: int = 200) -> list[dict[str, Any]]:
        self._expire_due(db, tenant_id=tenant_id)
        req = self._get_request(db, request_id=request_id, tenant_id=tenant_id)

        lim = self._normalize_limit(limit)
        rows_desc = (
            db.query(SupportMessage)
            .filter(SupportMessage.request_id == req.id)
            .order_by(SupportMessage.created_at.desc())
            .limit(lim)
            .all()
        )
        rows = list(reversed(rows_desc))
        return [self._message_to_dict(x) for x in rows]

    def _ensure_default_faq(self, db: Session) -> None:
        if int(db.query(SupportFaqEntry).count() or 0) > 0:
            return
        now = self._now()
        seed = [
            {"locale": "en", "category": "ACCESS", "question": "How do I grant support access?", "answer": "Create support request, open door, then superadmin starts session.", "sort_order": 10, "tags": ["support", "door", "session"]},
            {"locale": "en", "category": "LICENSES", "question": "Why core_license_required appears?", "answer": "Tenant must have active CORE entitlement for protected endpoints.", "sort_order": 20, "tags": ["core", "license"]},
            {"locale": "bg", "category": "ACCESS", "question": "Kak da dam dostap na suporta?", "answer": "Sazdai zaiavka, otvori door, posle superadmin startira sesiia.", "sort_order": 10, "tags": ["support", "door", "session"]},
            {"locale": "bg", "category": "LICENSES", "question": "Zashto vizhdam core_license_required?", "answer": "Triabva aktiven CORE licenz za zashtitenite endpoint-i.", "sort_order": 20, "tags": ["core", "license"]},
        ]
        for x in seed:
            db.add(
                SupportFaqEntry(
                    locale=str(x["locale"]),
                    category=str(x["category"]),
                    status="PUBLISHED",
                    sort_order=int(x["sort_order"]),
                    question=str(x["question"]),
                    answer=str(x["answer"]),
                    tags_json=list(x["tags"]),
                    created_by="system",
                    updated_by="system",
                    created_at=now,
                    updated_at=now,
                )
            )
        db.flush()

    def list_public_faq(self, db: Session, *, locale: str | None, q: str | None, category: str | None, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_default_faq(db)
        loc = self._normalize_locale(locale, default="en")
        lim = max(1, min(int(limit), 500))

        rows = (
            db.query(SupportFaqEntry)
            .filter(SupportFaqEntry.status == "PUBLISHED", SupportFaqEntry.locale == loc)
            .order_by(SupportFaqEntry.sort_order.asc(), SupportFaqEntry.updated_at.desc())
            .all()
        )
        if loc != "en":
            rows += (
                db.query(SupportFaqEntry)
                .filter(SupportFaqEntry.status == "PUBLISHED", SupportFaqEntry.locale == "en")
                .order_by(SupportFaqEntry.sort_order.asc(), SupportFaqEntry.updated_at.desc())
                .all()
            )

        if category:
            cat = self._clean_text(category, 64).upper()
            rows = [x for x in rows if str(x.category).upper() == cat]

        if q:
            qn = self._clean_text(q, 256).lower()
            rows = [x for x in rows if qn in str(x.question).lower() or qn in str(x.answer).lower()]

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            sid = str(row.id)
            if sid in seen:
                continue
            seen.add(sid)
            out.append(self._faq_to_dict(row))
            if len(out) >= lim:
                break
        return out

    def list_admin_faq(self, db: Session, *, status: str | None, locale: str | None, limit: int = 300) -> list[dict[str, Any]]:
        self._ensure_default_faq(db)
        q = db.query(SupportFaqEntry)
        if status:
            q = q.filter(SupportFaqEntry.status == self._normalize_faq_status(status))
        if locale:
            q = q.filter(SupportFaqEntry.locale == self._normalize_locale(locale))
        rows = q.order_by(SupportFaqEntry.locale.asc(), SupportFaqEntry.sort_order.asc(), SupportFaqEntry.updated_at.desc()).limit(max(1, min(int(limit), 2000))).all()
        return [self._faq_to_dict(x) for x in rows]

    def upsert_faq_entry(self, db: Session, *, actor: str, payload: dict[str, Any], entry_id: str | None = None) -> dict[str, Any]:
        self._ensure_default_faq(db)
        now = self._now()

        row: SupportFaqEntry | None = None
        if entry_id:
            eid = self._uuid_or_err(entry_id, err="support_faq_id_invalid")
            row = db.query(SupportFaqEntry).filter(SupportFaqEntry.id == eid).first()
            if row is None:
                raise ValueError("support_faq_not_found")

        locale = self._normalize_locale(payload.get("locale") if "locale" in payload else (row.locale if row else "en"))
        category = self._clean_text(payload.get("category") if "category" in payload else (row.category if row else "GENERAL"), 64).upper() or "GENERAL"
        status = self._normalize_faq_status(payload.get("status") if "status" in payload else (row.status if row else "PUBLISHED"))
        question = self._clean_text(payload.get("question") if "question" in payload else (row.question if row else ""), 512)
        answer = self._clean_text(payload.get("answer") if "answer" in payload else (row.answer if row else ""), 8000)

        if len(question) < 5:
            raise ValueError("support_faq_question_too_short")
        if len(answer) < 10:
            raise ValueError("support_faq_answer_too_short")

        sort_order = int(payload.get("sort_order") if "sort_order" in payload else (row.sort_order if row else 100))
        tags_in = list(payload.get("tags") if "tags" in payload else (row.tags_json if row else []))
        tags: list[str] = []
        seen: set[str] = set()
        for raw in tags_in:
            t = self._clean_text(raw, 64).lower()
            if not t or t in seen:
                continue
            seen.add(t)
            tags.append(t)
            if len(tags) >= 30:
                break

        if row is None:
            row = SupportFaqEntry(
                locale=locale,
                category=category,
                status=status,
                sort_order=sort_order,
                question=question,
                answer=answer,
                tags_json=tags,
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            row.locale = locale
            row.category = category
            row.status = status
            row.sort_order = sort_order
            row.question = question
            row.answer = answer
            row.tags_json = tags
            row.updated_by = str(actor or "unknown")
            row.updated_at = now

        db.flush()
        return self._faq_to_dict(row)

    def bot_reply(self, db: Session, *, tenant_id: str, request_id: str, actor: str, prompt: str | None, locale: str | None) -> dict[str, Any]:
        self._expire_due(db, tenant_id=tenant_id)
        req = self._get_request(db, request_id=request_id, tenant_id=tenant_id)
        self._ensure_request_message_open(req)

        text = self._clean_text(prompt, int(get_settings().support_chat_max_message_chars))
        if not text:
            text = req.description

        faq = self.list_public_faq(db, locale=locale, q=text, category=None, limit=1)
        if faq:
            body = f"FAQ match: {faq[0]['question']}\n{faq[0]['answer']}"
        else:
            body = "No exact FAQ match. Please provide error text, action and timestamp for human support."

        row = SupportMessage(
            request_id=req.id,
            tenant_id=tenant_id,
            session_id=None,
            channel="CHAT_BOT",
            sender_type="BOT",
            sender_id=str(actor or "support-bot"),
            body=body,
            metadata_json={"faq_match_ids": [x.get("id") for x in faq]},
            created_at=self._now(),
        )
        db.add(row)
        req.updated_at = self._now()
        db.flush()
        return {"message": self._message_to_dict(row), "faq_matches": faq}

    def validate_superadmin_tenant_scope(self, db: Session, *, claims: dict[str, Any], tenant_id: str) -> dict[str, Any] | None:
        roles = set(claims.get("roles") or [])
        if "SUPERADMIN" not in roles:
            return None

        support_tenant_id = str(claims.get("support_tenant_id") or "").strip()
        support_session_id = str(claims.get("support_session_id") or "").strip()
        if support_tenant_id != tenant_id or not support_session_id:
            raise ValueError("support_session_required_for_tenant_scope")

        sid = self._uuid_or_err(support_session_id, err="support_session_required_for_tenant_scope")
        now = self._now()
        row = (
            db.query(SupportSession)
            .filter(
                SupportSession.id == sid,
                SupportSession.tenant_id == tenant_id,
                SupportSession.status == "ACTIVE",
                SupportSession.expires_at >= now,
            )
            .first()
        )
        if row is None:
            raise ValueError("support_session_invalid_or_expired")
        return self._session_to_dict(row)


service = SupportService()