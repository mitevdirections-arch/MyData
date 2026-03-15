from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import re
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import StorageDeleteQueue, StorageGrant, StorageObjectMeta

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _allowed_content_types() -> set[str]:
    raw = get_settings().verification_doc_allowed_content_types
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _validate_content_type(content_type: str) -> str:
    ct = (content_type or "application/octet-stream").strip().lower()
    if ct not in _allowed_content_types():
        raise ValueError("content_type_not_allowed")
    return ct


def _validate_sha256(sha256: str) -> str:
    val = (sha256 or "").strip().lower()
    if not SHA256_RE.match(val):
        raise ValueError("sha256_invalid")
    return val


def _s3_client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.storage_endpoint,
        aws_access_key_id=s.storage_access_key,
        aws_secret_access_key=s.storage_secret_key,
        region_name=s.storage_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_dec(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _sign(msg: str) -> str:
    secret = get_settings().storage_grant_secret.encode("utf-8")
    mac = hmac.new(secret, msg.encode("utf-8"), hashlib.sha256).digest()
    return _b64u(mac)


def _encode_grant_token(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "SGT", "v": 1}
    h = _b64u(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign(f"{h}.{p}")
    return f"{h}.{p}.{sig}"


def _decode_grant_token(token: str) -> dict:
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ValueError("grant_token_invalid_format")
    h, p, s = parts
    if not hmac.compare_digest(_sign(f"{h}.{p}"), s):
        raise ValueError("grant_token_invalid_signature")
    try:
        payload = json.loads(_b64u_dec(p).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("grant_token_invalid_payload") from exc

    now_ts = int(_now().timestamp())
    if int(payload.get("exp", 0)) < now_ts:
        raise ValueError("grant_token_expired")
    return payload


def _compute_grant_ttl(ttl_seconds: int | None) -> int:
    s = get_settings()
    ttl = int(ttl_seconds) if ttl_seconds is not None else int(s.storage_grant_ttl_seconds_default)
    return max(30, min(ttl, int(s.storage_grant_ttl_seconds_max)))


def create_verification_doc_slot(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    file_name: str,
    content_type: str,
    retention_hours: int | None,
) -> dict:
    s = get_settings()
    hrs = retention_hours if retention_hours is not None else s.verification_doc_retention_hours_default
    hrs = max(1, min(int(hrs), int(s.verification_doc_retention_hours_max)))

    safe_name = file_name.replace("\\", "_").replace("/", "_").strip()
    if not safe_name:
        raise ValueError("file_name_required")

    doc_content_type = _validate_content_type(content_type)

    doc_id = str(uuid.uuid4())
    object_key = f"verification/{tenant_id}/{doc_id}/{safe_name}"
    retention_until = _now() + timedelta(hours=hrs)

    row = StorageObjectMeta(
        tenant_id=tenant_id,
        object_key=object_key,
        purpose="verification_doc",
        file_name=safe_name,
        content_type=doc_content_type,
        size_bytes=None,
        sha256=None,
        storage_provider=s.storage_provider,
        bucket=s.storage_bucket_verification,
        status="PENDING_UPLOAD",
        retention_until=retention_until,
        created_by=actor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    client = _s3_client()
    expires = max(60, min(int(s.storage_presign_ttl_seconds), 3600))
    url = client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": row.bucket,
            "Key": row.object_key,
            "ContentType": doc_content_type,
        },
        ExpiresIn=expires,
    )

    return {
        "id": str(row.id),
        "bucket": row.bucket,
        "object_key": row.object_key,
        "upload_url": url,
        "method": "PUT",
        "expires_in_seconds": expires,
        "retention_until": row.retention_until.isoformat(),
        "mode": "SIGNED_PRESIGN",
        "max_bytes": int(s.verification_doc_max_bytes),
        "allowed_content_types": sorted(_allowed_content_types()),
    }


def create_download_slot(db: Session, *, tenant_id: str, object_id: str) -> dict:
    row = (
        db.query(StorageObjectMeta)
        .filter(StorageObjectMeta.id == object_id, StorageObjectMeta.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise ValueError("storage_object_not_found")
    if row.status != "ACTIVE":
        raise ValueError("invalid_storage_state")
    if row.retention_until <= _now():
        raise ValueError("retention_expired")

    s = get_settings()
    expires = max(30, min(int(s.storage_download_presign_ttl_seconds), 300))
    url = _s3_client().generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": row.bucket,
            "Key": row.object_key,
        },
        ExpiresIn=expires,
    )

    return {
        "id": str(row.id),
        "download_url": url,
        "method": "GET",
        "expires_in_seconds": expires,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "retention_until": row.retention_until.isoformat(),
        "mode": "SIGNED_PRESIGN",
    }


def issue_upload_grant(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    file_name: str,
    content_type: str,
    retention_hours: int | None,
    ttl_seconds: int | None,
) -> dict:
    safe_name = (file_name or "").replace("\\", "_").replace("/", "_").strip()
    if not safe_name:
        raise ValueError("file_name_required")

    ct = _validate_content_type(content_type)
    ttl = _compute_grant_ttl(ttl_seconds)
    exp = _now() + timedelta(seconds=ttl)

    row = StorageGrant(
        tenant_id=tenant_id,
        scope="UPLOAD",
        status="ISSUED",
        object_id=None,
        payload_json={
            "file_name": safe_name,
            "content_type": ct,
            "retention_hours": retention_hours,
        },
        expires_at=exp,
        created_by=actor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    now_ts = int(_now().timestamp())
    payload = {
        "gid": str(row.id),
        "tenant_id": tenant_id,
        "scope": "UPLOAD",
        "sub": actor,
        "iat": now_ts,
        "exp": int(exp.timestamp()),
        "iss": "mydata-storage-grant",
    }
    token = _encode_grant_token(payload)

    return {
        "grant_token": token,
        "grant_id": str(row.id),
        "scope": row.scope,
        "expires_at": exp.isoformat(),
        "expires_in_seconds": ttl,
        "mode": "BROKERED_STS_V1",
    }


def issue_download_grant(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    object_id: str,
    ttl_seconds: int | None,
) -> dict:
    row_obj = (
        db.query(StorageObjectMeta)
        .filter(StorageObjectMeta.id == object_id, StorageObjectMeta.tenant_id == tenant_id)
        .first()
    )
    if row_obj is None:
        raise ValueError("storage_object_not_found")
    if row_obj.status != "ACTIVE":
        raise ValueError("invalid_storage_state")

    ttl = _compute_grant_ttl(ttl_seconds)
    exp = _now() + timedelta(seconds=ttl)

    row = StorageGrant(
        tenant_id=tenant_id,
        scope="DOWNLOAD",
        status="ISSUED",
        object_id=row_obj.id,
        payload_json={},
        expires_at=exp,
        created_by=actor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    now_ts = int(_now().timestamp())
    payload = {
        "gid": str(row.id),
        "tenant_id": tenant_id,
        "scope": "DOWNLOAD",
        "object_id": str(row_obj.id),
        "sub": actor,
        "iat": now_ts,
        "exp": int(exp.timestamp()),
        "iss": "mydata-storage-grant",
    }
    token = _encode_grant_token(payload)

    return {
        "grant_token": token,
        "grant_id": str(row.id),
        "scope": row.scope,
        "object_id": str(row_obj.id),
        "expires_at": exp.isoformat(),
        "expires_in_seconds": ttl,
        "mode": "BROKERED_STS_V1",
    }


def exchange_grant(db: Session, *, tenant_id: str, actor: str, grant_token: str) -> dict:
    payload = _decode_grant_token(grant_token)
    if str(payload.get("tenant_id") or "") != tenant_id:
        raise ValueError("grant_tenant_mismatch")

    gid = str(payload.get("gid") or "").strip()
    if not gid:
        raise ValueError("grant_id_missing")

    row = (
        db.query(StorageGrant)
        .filter(StorageGrant.id == gid, StorageGrant.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise ValueError("grant_not_found")
    if row.status != "ISSUED":
        raise ValueError("grant_not_issuable")
    if row.expires_at <= _now():
        row.status = "EXPIRED"
        db.commit()
        raise ValueError("grant_token_expired")

    scope = str(payload.get("scope") or row.scope or "").upper()
    if scope == "UPLOAD":
        p = row.payload_json or {}
        slot = create_verification_doc_slot(
            db,
            tenant_id=tenant_id,
            actor=actor,
            file_name=str(p.get("file_name") or ""),
            content_type=str(p.get("content_type") or "application/octet-stream"),
            retention_hours=p.get("retention_hours"),
        )
        row.object_id = uuid.UUID(slot["id"])
        action = "UPLOAD"
    elif scope == "DOWNLOAD":
        oid = str(payload.get("object_id") or row.object_id or "").strip()
        slot = create_download_slot(db, tenant_id=tenant_id, object_id=oid)
        action = "DOWNLOAD"
    else:
        raise ValueError("grant_scope_invalid")

    row.status = "USED"
    row.used_at = _now()
    db.commit()

    return {
        "action": action,
        "slot": slot,
        "grant_id": str(row.id),
        "mode": "BROKERED_STS_V1",
    }




def enqueue_delete_retry(
    db: Session,
    *,
    tenant_id: str,
    bucket: str,
    object_key: str,
    object_meta_id: str | None,
    reason: str,
    error: str,
) -> dict:
    # avoid duplicate pending jobs for same object
    existing = (
        db.query(StorageDeleteQueue)
        .filter(
            StorageDeleteQueue.tenant_id == tenant_id,
            StorageDeleteQueue.object_key == object_key,
            StorageDeleteQueue.status.in_(["PENDING", "RETRY_SCHEDULED"]),
        )
        .order_by(StorageDeleteQueue.created_at.desc())
        .first()
    )
    if existing is not None:
        existing.last_error = (error or "")[:2000]
        existing.updated_at = _now()
        db.commit()
        return {"id": str(existing.id), "status": existing.status, "deduplicated": True}

    max_attempts = int(get_settings().storage_delete_retry_max_attempts)
    row = StorageDeleteQueue(
        tenant_id=tenant_id,
        object_meta_id=(uuid.UUID(object_meta_id) if object_meta_id else None),
        bucket=bucket,
        object_key=object_key,
        reason=(reason or "retention")[:64],
        status="PENDING",
        attempts=0,
        max_attempts=max_attempts,
        next_attempt_at=_now(),
        last_error=(error or "")[:2000],
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status, "deduplicated": False}

def mark_uploaded(db: Session, *, tenant_id: str, object_id: str, size_bytes: int, sha256: str) -> dict:
    row = (
        db.query(StorageObjectMeta)
        .filter(StorageObjectMeta.id == object_id, StorageObjectMeta.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise ValueError("storage_object_not_found")

    if row.status != "PENDING_UPLOAD":
        raise ValueError("invalid_storage_state")

    max_bytes = int(get_settings().verification_doc_max_bytes)
    if int(size_bytes) <= 0 or int(size_bytes) > max_bytes:
        raise ValueError("size_bytes_out_of_policy")

    row.size_bytes = int(size_bytes)
    row.sha256 = _validate_sha256(sha256)
    row.status = "ACTIVE"
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "retention_until": row.retention_until.isoformat(),
    }


def list_verification_docs(db: Session, *, tenant_id: str, include_deleted: bool = False) -> list[dict]:
    q = db.query(StorageObjectMeta).filter(
        StorageObjectMeta.tenant_id == tenant_id,
        StorageObjectMeta.purpose == "verification_doc",
    )
    if not include_deleted:
        q = q.filter(StorageObjectMeta.status != "DELETED", StorageObjectMeta.status != "HARD_DELETED")

    rows = q.order_by(StorageObjectMeta.created_at.desc()).all()
    return [
        {
            "id": str(x.id),
            "file_name": x.file_name,
            "content_type": x.content_type,
            "size_bytes": x.size_bytes,
            "status": x.status,
            "bucket": x.bucket,
            "object_key": x.object_key,
            "retention_until": x.retention_until.isoformat(),
            "created_at": x.created_at.isoformat(),
        }
        for x in rows
    ]


def _delete_object_from_storage(bucket: str, object_key: str) -> None:
    try:
        _s3_client().delete_object(Bucket=bucket, Key=object_key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "")).strip()
        if code not in {"NoSuchKey", "NotFound"}:
            raise


def delete_doc(db: Session, *, tenant_id: str, object_id: str) -> dict:
    row = (
        db.query(StorageObjectMeta)
        .filter(StorageObjectMeta.id == object_id, StorageObjectMeta.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise ValueError("storage_object_not_found")

    try:
        _delete_object_from_storage(row.bucket, row.object_key)
        row.status = "HARD_DELETED"
        row.deleted_at = _now()
        db.commit()
        return {"id": str(row.id), "status": row.status, "queued": False}
    except Exception as exc:  # noqa: BLE001
        # logical delete now; physical delete goes to retry queue
        row.status = "DELETED"
        row.deleted_at = _now()
        db.commit()
        q = enqueue_delete_retry(
            db,
            tenant_id=tenant_id,
            bucket=row.bucket,
            object_key=row.object_key,
            object_meta_id=str(row.id),
            reason="manual_delete",
            error=str(exc),
        )
        return {"id": str(row.id), "status": row.status, "queued": True, "queue": q}

def list_delete_queue_jobs(
    db: Session,
    *,
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    allowed_statuses = {"PENDING", "RETRY_SCHEDULED", "DONE", "FAILED"}

    q = db.query(StorageDeleteQueue)
    if tenant_id:
        q = q.filter(StorageDeleteQueue.tenant_id == tenant_id)
    if status:
        s = status.strip().upper()
        if s not in allowed_statuses:
            raise ValueError("queue_status_invalid")
        q = q.filter(StorageDeleteQueue.status == s)

    rows = (
        q.order_by(StorageDeleteQueue.next_attempt_at.asc(), StorageDeleteQueue.created_at.desc())
        .limit(max(1, min(int(limit), 1000)))
        .all()
    )

    return [
        {
            "id": str(x.id),
            "tenant_id": x.tenant_id,
            "object_meta_id": str(x.object_meta_id) if x.object_meta_id else None,
            "bucket": x.bucket,
            "object_key": x.object_key,
            "reason": x.reason,
            "status": x.status,
            "attempts": int(x.attempts),
            "max_attempts": int(x.max_attempts),
            "next_attempt_at": x.next_attempt_at.isoformat(),
            "last_error": x.last_error,
            "created_at": x.created_at.isoformat(),
            "updated_at": x.updated_at.isoformat(),
            "processed_at": x.processed_at.isoformat() if x.processed_at else None,
        }
        for x in rows
    ]


def delete_queue_summary(db: Session, *, tenant_id: str | None = None) -> dict:
    q = db.query(StorageDeleteQueue)
    if tenant_id:
        q = q.filter(StorageDeleteQueue.tenant_id == tenant_id)

    rows = q.all()
    summary = {"PENDING": 0, "RETRY_SCHEDULED": 0, "DONE": 0, "FAILED": 0}
    for r in rows:
        if r.status in summary:
            summary[r.status] += 1

    return {
        "total": len(rows),
        "status": summary,
    }

def requeue_delete_job(db: Session, *, job_id: str) -> dict:
    row = db.query(StorageDeleteQueue).filter(StorageDeleteQueue.id == job_id).first()
    if row is None:
        raise ValueError("queue_job_not_found")

    if row.status == "DONE":
        raise ValueError("queue_job_done_cannot_requeue")

    row.status = "PENDING"
    row.next_attempt_at = _now()
    row.last_error = None
    row.updated_at = _now()
    db.commit()
    db.refresh(row)

    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "status": row.status,
        "attempts": int(row.attempts),
        "max_attempts": int(row.max_attempts),
        "next_attempt_at": row.next_attempt_at.isoformat(),
    }

def _next_retry_at(attempts: int) -> datetime:
    s = get_settings()
    base = int(s.storage_delete_retry_base_seconds)
    mx = int(s.storage_delete_retry_max_seconds)
    delay = min(base * (2 ** max(0, attempts - 1)), mx)
    return _now() + timedelta(seconds=delay)


def process_delete_queue_once(db: Session, *, limit: int | None = None) -> dict:
    s = get_settings()

    lim = int(limit) if limit is not None else int(s.storage_delete_queue_batch_size)
    lim = max(1, min(lim, 1000))

    jobs = (
        db.query(StorageDeleteQueue)
        .filter(
            StorageDeleteQueue.status.in_(["PENDING", "RETRY_SCHEDULED"]),
            StorageDeleteQueue.next_attempt_at <= _now(),
        )
        .order_by(StorageDeleteQueue.next_attempt_at.asc())
        .limit(lim)
        .all()
    )

    done_count = 0
    failed_count = 0

    for job in jobs:
        try:
            _s3_client().delete_object(Bucket=job.bucket, Key=job.object_key)
            job.status = "DONE"
            job.attempts = int(job.attempts) + 1
            job.processed_at = _now()
            job.updated_at = _now()
            job.last_error = None

            if job.object_meta_id:
                obj = db.query(StorageObjectMeta).filter(StorageObjectMeta.id == job.object_meta_id).first()
                if obj is not None:
                    obj.status = "HARD_DELETED"
                    obj.deleted_at = _now()
            done_count += 1
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "")).strip()
            if code in {"NoSuchKey", "NotFound"}:
                job.status = "DONE"
                job.attempts = int(job.attempts) + 1
                job.processed_at = _now()
                job.updated_at = _now()
                job.last_error = None
                done_count += 1
                continue

            job.attempts = int(job.attempts) + 1
            job.last_error = str(exc)[:2000]
            job.updated_at = _now()
            if int(job.attempts) >= int(job.max_attempts):
                job.status = "FAILED"
                job.processed_at = _now()
            else:
                job.status = "RETRY_SCHEDULED"
                job.next_attempt_at = _next_retry_at(int(job.attempts))
            failed_count += 1
        except Exception as exc:  # noqa: BLE001
            job.attempts = int(job.attempts) + 1
            job.last_error = str(exc)[:2000]
            job.updated_at = _now()
            if int(job.attempts) >= int(job.max_attempts):
                job.status = "FAILED"
                job.processed_at = _now()
            else:
                job.status = "RETRY_SCHEDULED"
                job.next_attempt_at = _next_retry_at(int(job.attempts))
            failed_count += 1

    db.commit()
    return {
        "processed": len(jobs),
        "done": done_count,
        "failed": failed_count,
    }

def fail_delete_job_now(db: Session, *, job_id: str, reason: str | None = None) -> dict:
    row = db.query(StorageDeleteQueue).filter(StorageDeleteQueue.id == job_id).first()
    if row is None:
        raise ValueError("queue_job_not_found")
    if row.status == "DONE":
        raise ValueError("queue_job_done_cannot_fail")

    msg = (reason or "manual_fail_now").strip()
    if len(msg) > 2000:
        msg = msg[:2000]

    row.status = "FAILED"
    row.last_error = msg
    row.processed_at = _now()
    row.updated_at = _now()
    db.commit()
    db.refresh(row)

    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "status": row.status,
        "attempts": int(row.attempts),
        "max_attempts": int(row.max_attempts),
        "last_error": row.last_error,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }