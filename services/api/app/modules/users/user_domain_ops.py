from __future__ import annotations

import base64
from datetime import timedelta
import hashlib
import hmac
from typing import Any
import secrets
import uuid

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import WorkspaceUser, WorkspaceUserCredential, WorkspaceUserDocument, WorkspaceUserNextOfKin


# Extracted operational methods from UserDomainService to keep service surface thin.
def list_user_documents(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    return [svc._doc_to_dict(x) for x in svc._list_documents_rows(db, workspace_type=wtype, workspace_id=wid, user_id=uid, limit=limit)]


def upsert_user_document(svc,

    db: Session,

    *,

    workspace_type: str,

    workspace_id: str,

    user_id: str,

    actor: str,

    payload: dict[str, Any],

    document_id: str | None = None,

) -> dict[str, Any]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()



    row: WorkspaceUserDocument | None = None

    if document_id is not None:

        try:

            did = uuid.UUID(str(document_id).strip())

        except Exception as exc:  # noqa: BLE001

            raise ValueError("document_id_invalid") from exc

        row = (

            db.query(WorkspaceUserDocument)

            .filter(

                WorkspaceUserDocument.id == did,

                WorkspaceUserDocument.workspace_type == wtype,

                WorkspaceUserDocument.workspace_id == wid,

                WorkspaceUserDocument.user_id == uid,

            )

            .first()

        )

        if row is None:

            raise ValueError("user_document_not_found")



    now = svc._now()

    if row is None:

        doc_kind = (svc._clean_text(payload.get("doc_kind"), 64) or "").upper()

        title = svc._clean_text(payload.get("title"), 255)

        if not doc_kind:

            raise ValueError("doc_kind_required")

        if not title:

            raise ValueError("title_required")

        row = WorkspaceUserDocument(

            workspace_type=wtype,

            workspace_id=wid,

            user_id=uid,

            doc_kind=doc_kind,

            title=title,

            doc_number=svc._clean_text(payload.get("doc_number"), 128),

            issuer=svc._clean_text(payload.get("issuer"), 255),

            country_code=svc._clean_text(payload.get("country_code"), 8),

            issued_on=svc._parse_datetime(payload.get("issued_on")),

            valid_from=svc._parse_datetime(payload.get("valid_from")),

            valid_until=svc._parse_datetime(payload.get("valid_until")),

            status=(svc._clean_text(payload.get("status"), 32) or "ACTIVE").upper(),

            storage_provider=svc._clean_text(payload.get("storage_provider"), 32),

            bucket=svc._clean_text(payload.get("bucket"), 128),

            object_key=svc._clean_text(payload.get("object_key"), 512),

            file_name=svc._clean_text(payload.get("file_name"), 255),

            mime_type=svc._clean_text(payload.get("mime_type"), 128),

            size_bytes=(int(payload.get("size_bytes")) if payload.get("size_bytes") is not None else None),

            sha256=svc._clean_text(payload.get("sha256"), 128),

            metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),

            created_by=str(actor or "unknown"),

            updated_by=str(actor or "unknown"),

            created_at=now,

            updated_at=now,

        )

        db.add(row)

    else:

        for k, max_len in [

            ("doc_kind", 64),

            ("title", 255),

            ("doc_number", 128),

            ("issuer", 255),

            ("country_code", 8),

            ("status", 32),

            ("storage_provider", 32),

            ("bucket", 128),

            ("object_key", 512),

            ("file_name", 255),

            ("mime_type", 128),

            ("sha256", 128),

        ]:

            if k in payload:

                val = svc._clean_text(payload.get(k), max_len)

                if k in {"doc_kind", "status"} and val is not None:

                    val = val.upper()

                setattr(row, k, val)

        if "issued_on" in payload:

            row.issued_on = svc._parse_datetime(payload.get("issued_on"))

        if "valid_from" in payload:

            row.valid_from = svc._parse_datetime(payload.get("valid_from"))

        if "valid_until" in payload:

            row.valid_until = svc._parse_datetime(payload.get("valid_until"))

        if "size_bytes" in payload:

            row.size_bytes = int(payload.get("size_bytes")) if payload.get("size_bytes") is not None else None

        if "metadata" in payload and isinstance(payload.get("metadata"), dict):

            row.metadata_json = dict(payload.get("metadata") or {})

        row.updated_by = str(actor or "unknown")

        row.updated_at = now



    db.flush()

    return svc._doc_to_dict(row)


def delete_user_document(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, document_id: str) -> dict[str, Any]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    try:

        did = uuid.UUID(str(document_id).strip())

    except Exception as exc:  # noqa: BLE001

        raise ValueError("document_id_invalid") from exc



    row = (

        db.query(WorkspaceUserDocument)

        .filter(

            WorkspaceUserDocument.id == did,

            WorkspaceUserDocument.workspace_type == wtype,

            WorkspaceUserDocument.workspace_id == wid,

            WorkspaceUserDocument.user_id == uid,

        )

        .first()

    )

    if row is None:

        raise ValueError("user_document_not_found")

    out = svc._doc_to_dict(row)

    db.delete(row)

    db.flush()

    return out


def list_user_next_of_kin(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    return [svc._next_of_kin_to_dict(x) for x in svc._list_next_of_kin_rows(db, workspace_type=wtype, workspace_id=wid, user_id=uid, limit=limit)]


def upsert_user_next_of_kin(svc,

    db: Session,

    *,

    workspace_type: str,

    workspace_id: str,

    user_id: str,

    actor: str,

    payload: dict[str, Any],

    kin_id: str | None = None,

) -> dict[str, Any]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()



    existing_count = int(

        db.query(WorkspaceUserNextOfKin)

        .filter(

            WorkspaceUserNextOfKin.workspace_type == wtype,

            WorkspaceUserNextOfKin.workspace_id == wid,

            WorkspaceUserNextOfKin.user_id == uid,

        )

        .count()

    )



    row: WorkspaceUserNextOfKin | None = None

    if kin_id is not None:

        try:

            kid = uuid.UUID(str(kin_id).strip())

        except Exception as exc:  # noqa: BLE001

            raise ValueError("kin_id_invalid") from exc

        row = (

            db.query(WorkspaceUserNextOfKin)

            .filter(

                WorkspaceUserNextOfKin.id == kid,

                WorkspaceUserNextOfKin.workspace_type == wtype,

                WorkspaceUserNextOfKin.workspace_id == wid,

                WorkspaceUserNextOfKin.user_id == uid,

            )

            .first()

        )

        if row is None:

            raise ValueError("user_next_of_kin_not_found")



    now = svc._now()

    if row is None:

        full_name = svc._clean_text(payload.get("full_name"), 255)

        relation = svc._clean_text(payload.get("relation"), 64)

        if not full_name:

            raise ValueError("full_name_required")

        if not relation:

            raise ValueError("relation_required")

        row = WorkspaceUserNextOfKin(

            workspace_type=wtype,

            workspace_id=wid,

            user_id=uid,

            full_name=full_name,

            relation=relation,

            contact_email=svc._clean_text(payload.get("contact_email"), 255),

            contact_phone=svc._clean_text(payload.get("contact_phone"), 64),

            address_country_code=svc._clean_text(payload.get("country_code"), 8),

            address_line1=svc._clean_text(payload.get("line1"), 255),

            address_line2=svc._clean_text(payload.get("line2"), 255),

            address_city=svc._clean_text(payload.get("city"), 128),

            address_postal_code=svc._clean_text(payload.get("postal_code"), 32),

            is_primary=bool(payload.get("is_primary", existing_count == 0)),

            sort_order=svc._clean_sort_order(payload.get("sort_order"), default=0),

            metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),

            created_by=str(actor or "unknown"),

            updated_by=str(actor or "unknown"),

            created_at=now,

            updated_at=now,

        )

        db.add(row)

    else:

        for key, max_len in [

            ("full_name", 255),

            ("relation", 64),

            ("contact_email", 255),

            ("contact_phone", 64),

            ("country_code", 8),

            ("line1", 255),

            ("line2", 255),

            ("city", 128),

            ("postal_code", 32),

        ]:

            if key in payload:

                val = svc._clean_text(payload.get(key), max_len)

                if key == "country_code":

                    row.address_country_code = val

                elif key == "line1":

                    row.address_line1 = val

                elif key == "line2":

                    row.address_line2 = val

                elif key == "city":

                    row.address_city = val

                elif key == "postal_code":

                    row.address_postal_code = val

                else:

                    setattr(row, key, val)

        if "is_primary" in payload:

            row.is_primary = bool(payload.get("is_primary"))

        if "sort_order" in payload:

            row.sort_order = svc._clean_sort_order(payload.get("sort_order"), default=int(row.sort_order or 0))

        if "metadata" in payload and isinstance(payload.get("metadata"), dict):

            row.metadata_json = dict(payload.get("metadata") or {})

        row.updated_by = str(actor or "unknown")

        row.updated_at = now



    db.flush()

    if bool(row.is_primary):

        (

            db.query(WorkspaceUserNextOfKin)

            .filter(

                WorkspaceUserNextOfKin.workspace_type == wtype,

                WorkspaceUserNextOfKin.workspace_id == wid,

                WorkspaceUserNextOfKin.user_id == uid,

                WorkspaceUserNextOfKin.id != row.id,

            )

            .update({WorkspaceUserNextOfKin.is_primary: False}, synchronize_session=False)

        )

        db.flush()



    return svc._next_of_kin_to_dict(row)


def delete_user_next_of_kin(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, kin_id: str) -> dict[str, Any]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    try:

        kid = uuid.UUID(str(kin_id).strip())

    except Exception as exc:  # noqa: BLE001

        raise ValueError("kin_id_invalid") from exc



    row = (

        db.query(WorkspaceUserNextOfKin)

        .filter(

            WorkspaceUserNextOfKin.id == kid,

            WorkspaceUserNextOfKin.workspace_type == wtype,

            WorkspaceUserNextOfKin.workspace_id == wid,

            WorkspaceUserNextOfKin.user_id == uid,

        )

        .first()

    )

    if row is None:

        raise ValueError("user_next_of_kin_not_found")

    out = svc._next_of_kin_to_dict(row)

    db.delete(row)

    db.flush()

    return out


def _credential_row_for_user(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str) -> WorkspaceUserCredential | None:

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    return (

        db.query(WorkspaceUserCredential)

        .filter(

            WorkspaceUserCredential.workspace_type == wtype,

            WorkspaceUserCredential.workspace_id == wid,

            WorkspaceUserCredential.user_id == uid,

        )

        .first()

    )


def _coerce_int(payload: dict[str, Any], *, key: str, default: int, min_value: int, max_value: int, error_code: str) -> int:

    raw = payload.get(key, default)

    try:
        value = int(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(error_code) from exc

    return max(min_value, min(value, max_value))


def _decode_urlsafe_b64(value: str) -> bytes:
    txt = str(value or "").strip()
    if not txt:
        raise ValueError("credential_hash_invalid")
    padding = "=" * (-len(txt) % 4)
    try:
        return base64.urlsafe_b64decode(f"{txt}{padding}".encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("credential_hash_invalid") from exc


def _verify_secret_hash(secret: str, *, salt_b64: str, hash_b64: str, iterations: int) -> bool:
    salt = _decode_urlsafe_b64(salt_b64)
    expected = _decode_urlsafe_b64(hash_b64)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(digest, expected)


def _password_policy_settings() -> tuple[int, int]:
    settings = get_settings()
    min_length = max(8, min(int(getattr(settings, "auth_password_min_length", 12) or 12), 128))
    max_age_days = max(30, min(int(getattr(settings, "auth_password_max_age_days", 180) or 180), 3650))
    return min_length, max_age_days


def _validate_new_password(raw: Any, *, min_length: int) -> str:
    password = str(raw or "")
    if len(password) < int(min_length):
        raise ValueError("new_password_too_short")
    if not any(ch.islower() for ch in password):
        raise ValueError("new_password_weak")
    if not any(ch.isupper() for ch in password):
        raise ValueError("new_password_weak")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("new_password_weak")
    return password


def _require_active_credential_for_self_service(row: WorkspaceUserCredential, *, now) -> None:
    status = str(row.status or "").strip().upper()
    if status in {"PENDING_INVITE", "INVITE_EXPIRED"}:
        raise ValueError("invite_not_accepted")
    if status == "DISABLED":
        raise ValueError("credential_disabled")
    if status != "ACTIVE":
        raise ValueError("credential_not_active")
    if row.locked_until is not None and row.locked_until > now:
        raise ValueError("credential_locked")


def get_user_credential(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any] | None:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)

    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)

    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    if row is None:

        return None

    return svc._credential_public_dict(row)


def issue_user_credentials(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
    reset_existing: bool = False,
) -> dict[str, Any]:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    user = svc._require_workspace_user(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    if row is not None and not reset_existing:

        raise ValueError("credentials_already_issued")

    requested_username = svc._clean_text(payload.get("username"), 128)

    if requested_username:

        username_seed = requested_username

    elif user.email:

        username_seed = str(user.email).split("@", 1)[0]

    else:

        username_seed = uid

    username = svc._unique_username(db, workspace_type=wtype, workspace_id=wid, candidate=username_seed, current_id=(row.id if row else None))

    iterations = _coerce_int(
        payload,
        key="hash_iterations",
        default=210000,
        min_value=120000,
        max_value=1000000,
        error_code="hash_iterations_invalid",
    )

    ttl_hours = _coerce_int(
        payload,
        key="temporary_password_ttl_hours",
        default=24,
        min_value=1,
        max_value=168,
        error_code="temporary_password_ttl_hours_invalid",
    )

    pw_len = _coerce_int(
        payload,
        key="temporary_password_length",
        default=18,
        min_value=12,
        max_value=64,
        error_code="temporary_password_length_invalid",
    )

    temp_password = svc._generate_temp_password(length=pw_len)

    salt, pw_hash = svc._hash_password(temp_password, iterations=iterations)

    now = svc._now()

    expires_at = now + timedelta(hours=ttl_hours)

    if row is None:

        row = WorkspaceUserCredential(
            workspace_type=wtype,
            workspace_id=wid,
            user_id=uid,
            username=username,
            password_hash=pw_hash,
            password_salt=salt,
            hash_alg="PBKDF2_SHA256",
            hash_iterations=iterations,
            must_change_password=True,
            status="ACTIVE",
            failed_attempts=0,
            locked_until=None,
            password_set_at=now,
            password_expires_at=expires_at,
            last_login_at=None,
            created_by=str(actor or "unknown"),
            updated_by=str(actor or "unknown"),
            created_at=now,
            updated_at=now,
        )

        db.add(row)

    else:

        row.username = username
        row.password_hash = pw_hash
        row.password_salt = salt
        row.hash_alg = "PBKDF2_SHA256"
        row.hash_iterations = iterations
        row.must_change_password = True
        row.status = "ACTIVE"
        row.failed_attempts = 0
        row.locked_until = None
        row.password_set_at = now
        row.password_expires_at = expires_at
        row.updated_by = str(actor or "unknown")
        row.updated_at = now

    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "temporary_password": temp_password,
        "temporary_password_expires_at": expires_at.isoformat(),
        "mode": ("RESET" if reset_existing else "ISSUE"),
    }


def issue_user_invite(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
    reset_existing: bool = False,
) -> dict[str, Any]:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    user = svc._require_workspace_user(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    if row is not None and not reset_existing:
        if str(row.status or "").strip().upper() == "PENDING_INVITE":
            raise ValueError("invite_already_pending")
        raise ValueError("credentials_already_issued")

    requested_username = svc._clean_text(payload.get("username"), 128)

    if requested_username:
        username_seed = requested_username
    elif user.email:
        username_seed = str(user.email).split("@", 1)[0]
    else:
        username_seed = uid

    username = svc._unique_username(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        candidate=username_seed,
        current_id=(row.id if row else None),
    )

    iterations = _coerce_int(
        payload,
        key="hash_iterations",
        default=210000,
        min_value=120000,
        max_value=1000000,
        error_code="hash_iterations_invalid",
    )
    ttl_hours = _coerce_int(
        payload,
        key="invite_ttl_hours",
        default=72,
        min_value=1,
        max_value=336,
        error_code="invite_ttl_hours_invalid",
    )
    invite_token = secrets.token_urlsafe(32)
    salt, invite_hash = svc._hash_password(invite_token, iterations=iterations)

    now = svc._now()
    expires_at = now + timedelta(hours=ttl_hours)

    if row is None:
        row = WorkspaceUserCredential(
            workspace_type=wtype,
            workspace_id=wid,
            user_id=uid,
            username=username,
            password_hash=invite_hash,
            password_salt=salt,
            hash_alg="PBKDF2_SHA256",
            hash_iterations=iterations,
            must_change_password=True,
            status="PENDING_INVITE",
            failed_attempts=0,
            locked_until=None,
            password_set_at=now,
            password_expires_at=expires_at,
            last_login_at=None,
            created_by=str(actor or "unknown"),
            updated_by=str(actor or "unknown"),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.username = username
        row.password_hash = invite_hash
        row.password_salt = salt
        row.hash_alg = "PBKDF2_SHA256"
        row.hash_iterations = iterations
        row.must_change_password = True
        row.status = "PENDING_INVITE"
        row.failed_attempts = 0
        row.locked_until = None
        row.password_set_at = now
        row.password_expires_at = expires_at
        row.updated_by = str(actor or "unknown")
        row.updated_at = now

    db.flush()

    invite_base_url = svc._clean_text(payload.get("invite_base_url"), 2048)
    invite_url = None
    if invite_base_url:
        sep = "&" if "?" in invite_base_url else "?"
        invite_url = f"{invite_base_url}{sep}token={invite_token}"

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "invite_token": invite_token,
        "invite_url": invite_url,
        "invite_expires_at": expires_at.isoformat(),
        "mode": ("INVITE_REISSUE" if reset_existing else "INVITE_ISSUE"),
    }


def lock_user_credential(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)
    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if row is None:
        raise ValueError("credential_not_found")

    lock_for_minutes = payload.get("lock_for_minutes")
    lock_minutes: int | None = None
    if lock_for_minutes is not None:
        lock_minutes = _coerce_int(
            payload,
            key="lock_for_minutes",
            default=30,
            min_value=1,
            max_value=10080,
            error_code="lock_for_minutes_invalid",
        )

    now = svc._now()
    row.status = "LOCKED"
    row.locked_until = (now + timedelta(minutes=lock_minutes)) if lock_minutes else None
    row.updated_by = str(actor or "unknown")
    row.updated_at = now
    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "mode": "LOCK",
    }


def unlock_user_credential(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)
    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if row is None:
        raise ValueError("credential_not_found")

    if str(row.status or "").strip().upper() == "DISABLED":
        raise ValueError("credential_disabled")

    if str(row.status or "").strip().upper() in {"PENDING_INVITE", "INVITE_EXPIRED"}:
        raise ValueError("invite_not_accepted")

    now = svc._now()
    row.status = "ACTIVE"
    row.locked_until = None
    row.failed_attempts = 0
    row.updated_by = str(actor or "unknown")
    row.updated_at = now
    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "mode": "UNLOCK",
    }


def revoke_user_invite(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
) -> dict[str, Any]:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)
    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if row is None:
        raise ValueError("credential_not_found")

    if str(row.status or "").strip().upper() not in {"PENDING_INVITE", "INVITE_EXPIRED"}:
        raise ValueError("invite_not_pending")

    now = svc._now()
    row.status = "DISABLED"
    row.locked_until = now
    row.password_expires_at = now
    row.updated_by = str(actor or "unknown")
    row.updated_at = now
    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "mode": "INVITE_REVOKE",
    }


def reset_user_password(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:

    return svc.issue_user_credentials(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
        actor=actor,
        payload=payload,
        reset_existing=True,
    )


def change_my_password(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)

    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if row is None:
        raise ValueError("credential_not_found")

    now = svc._now()
    _require_active_credential_for_self_service(row, now=now)

    current_password = str(payload.get("current_password") or "")
    if not current_password:
        raise ValueError("current_password_required")
    if not _verify_secret_hash(
        current_password,
        salt_b64=str(row.password_salt or ""),
        hash_b64=str(row.password_hash or ""),
        iterations=int(row.hash_iterations or 0),
    ):
        raise ValueError("current_password_invalid")

    min_length, max_age_days = _password_policy_settings()
    new_password = _validate_new_password(payload.get("new_password"), min_length=min_length)
    if current_password == new_password:
        raise ValueError("new_password_reuse_not_allowed")

    salt, pw_hash = svc._hash_password(new_password, iterations=int(row.hash_iterations or 210000))
    row.password_hash = pw_hash
    row.password_salt = salt
    row.must_change_password = False
    row.status = "ACTIVE"
    row.failed_attempts = 0
    row.locked_until = None
    row.password_set_at = now
    row.password_expires_at = now + timedelta(days=max_age_days)
    row.updated_by = str(actor or "unknown")
    row.updated_at = now
    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "mode": "SELF_PASSWORD_CHANGE",
    }


def change_my_username(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)

    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if row is None:
        raise ValueError("credential_not_found")

    now = svc._now()
    _require_active_credential_for_self_service(row, now=now)

    current_password = str(payload.get("current_password") or "")
    if not current_password:
        raise ValueError("current_password_required")
    if not _verify_secret_hash(
        current_password,
        salt_b64=str(row.password_salt or ""),
        hash_b64=str(row.password_hash or ""),
        iterations=int(row.hash_iterations or 0),
    ):
        raise ValueError("current_password_invalid")

    requested_username = svc._clean_text(payload.get("new_username"), 128)
    if not requested_username:
        raise ValueError("new_username_required")

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)
    username = svc._unique_username(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        candidate=requested_username,
        current_id=row.id,
    )

    row.username = username
    row.updated_by = str(actor or "unknown")
    row.updated_at = now
    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "mode": "SELF_USERNAME_CHANGE",
    }


def accept_user_invite(
    svc,
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
    svc._require_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id)

    row = _credential_row_for_user(
        svc,
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if row is None:
        raise ValueError("credential_not_found")

    status = str(row.status or "").strip().upper()
    if status not in {"PENDING_INVITE", "INVITE_EXPIRED"}:
        raise ValueError("invite_not_pending")

    now = svc._now()
    if row.password_expires_at is not None and row.password_expires_at <= now:
        row.status = "INVITE_EXPIRED"
        row.updated_by = str(actor or "unknown")
        row.updated_at = now
        db.flush()
        raise ValueError("invite_expired")

    invite_token = str(payload.get("invite_token") or "").strip()
    if not invite_token:
        raise ValueError("invite_token_required")
    if not _verify_secret_hash(
        invite_token,
        salt_b64=str(row.password_salt or ""),
        hash_b64=str(row.password_hash or ""),
        iterations=int(row.hash_iterations or 0),
    ):
        raise ValueError("invite_token_invalid")

    min_length, max_age_days = _password_policy_settings()
    new_password = _validate_new_password(payload.get("new_password"), min_length=min_length)

    requested_username = svc._clean_text(payload.get("new_username"), 128) or row.username
    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)
    username = svc._unique_username(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        candidate=requested_username,
        current_id=row.id,
    )

    salt, pw_hash = svc._hash_password(new_password, iterations=int(row.hash_iterations or 210000))
    row.username = username
    row.password_hash = pw_hash
    row.password_salt = salt
    row.hash_alg = "PBKDF2_SHA256"
    row.must_change_password = False
    row.status = "ACTIVE"
    row.failed_attempts = 0
    row.locked_until = None
    row.password_set_at = now
    row.password_expires_at = now + timedelta(days=max_age_days)
    row.updated_by = str(actor or "invite_accept")
    row.updated_at = now
    db.flush()

    return {
        "ok": True,
        "credential": svc._credential_public_dict(row),
        "mode": "INVITE_ACCEPT",
    }
