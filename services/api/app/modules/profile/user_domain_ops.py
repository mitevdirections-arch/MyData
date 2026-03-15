from __future__ import annotations

from datetime import timedelta
from typing import Any
import uuid

from sqlalchemy.orm import Session

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


def get_user_credential(svc, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any] | None:

    svc._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)

    svc._ensure_workspace_user(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()

    row = (

        db.query(WorkspaceUserCredential)

        .filter(

            WorkspaceUserCredential.workspace_type == wtype,

            WorkspaceUserCredential.workspace_id == wid,

            WorkspaceUserCredential.user_id == uid,

        )

        .first()

    )

    if row is None:

        return None

    return svc._credential_public_dict(row)


def issue_user_credentials(svc,

    db: Session,

    *,

    workspace_type: str,

    workspace_id: str,

    user_id: str,

    actor: str,

    payload: dict[str, Any],

    reset_existing: bool = False,

) -> dict[str, Any]:

    svc.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

    wtype, wid = svc._normalize_workspace(workspace_type, workspace_id)

    uid = str(user_id or "").strip()



    user = (

        db.query(WorkspaceUser)

        .filter(

            WorkspaceUser.workspace_type == wtype,

            WorkspaceUser.workspace_id == wid,

            WorkspaceUser.user_id == uid,

        )

        .first()

    )

    if user is None:

        raise ValueError("workspace_user_not_found")



    row = (

        db.query(WorkspaceUserCredential)

        .filter(

            WorkspaceUserCredential.workspace_type == wtype,

            WorkspaceUserCredential.workspace_id == wid,

            WorkspaceUserCredential.user_id == uid,

        )

        .first()

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



    iterations = max(120000, min(int(payload.get("hash_iterations") or 210000), 1000000))

    ttl_hours = max(1, min(int(payload.get("temporary_password_ttl_hours") or 24), 168))

    pw_len = max(12, min(int(payload.get("temporary_password_length") or 18), 64))

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
