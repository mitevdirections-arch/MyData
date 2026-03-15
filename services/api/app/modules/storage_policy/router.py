from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_superadmin, require_tenant_admin
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.modules.licensing.deps import require_module_entitlement
from app.modules.storage_policy.service import (
    create_download_slot,
    create_verification_doc_slot,
    delete_doc,
    delete_queue_summary,
    exchange_grant,
    issue_download_grant,
    issue_upload_grant,
    list_delete_queue_jobs,
    list_verification_docs,
    mark_uploaded,
    requeue_delete_job,
    fail_delete_job_now,
    process_delete_queue_once,
)

router = APIRouter(
    prefix="/admin/storage/verification-docs",
    tags=["admin.storage.verification"],
    dependencies=[Depends(require_module_entitlement("STORAGE"))],
)
policy_router = APIRouter(
    prefix="/admin/storage",
    tags=["admin.storage"],
    dependencies=[Depends(require_module_entitlement("STORAGE"))],
)
super_router = APIRouter(prefix="/superadmin/storage", tags=["superadmin.storage"])


@policy_router.get("/policy")
def storage_policy(claims: dict[str, Any] = Depends(require_tenant_admin)) -> dict:
    s = get_settings()
    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "policy": {
            "zero_retention": True,
            "store_customer_files": False,
            "metadata_only": True,
            "verification_docs_exception": True,
            "verification_docs_storage": s.storage_provider,
            "verification_docs_bucket": s.storage_bucket_verification,
            "default_retention_hours": s.verification_doc_retention_hours_default,
            "max_retention_hours": s.verification_doc_retention_hours_max,
            "allowed_content_types": [x.strip() for x in s.verification_doc_allowed_content_types.split(",") if x.strip()],
            "max_bytes": int(s.verification_doc_max_bytes),
            "download_presign_ttl_seconds": int(s.storage_download_presign_ttl_seconds),
            "grant_mode": "BROKERED_STS_V1",
            "grant_ttl_default_seconds": int(s.storage_grant_ttl_seconds_default),
            "grant_ttl_max_seconds": int(s.storage_grant_ttl_seconds_max),
        },
    }


@super_router.get("/delete-queue")
def super_delete_queue(
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        items = list_delete_queue_jobs(db, status=status, tenant_id=tenant_id, limit=limit)
        summary = delete_queue_summary(db, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "filters": {"status": status, "tenant_id": tenant_id, "limit": limit},
        "summary": summary,
        "items": items,
    }


@super_router.post("/delete-queue/{job_id}/requeue")
def super_requeue_delete_job(
    job_id: str,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    actor = str(claims.get("sub") or "unknown")
    try:
        item = requeue_delete_job(db, job_id=job_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "queue_job_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="storage.delete_queue_requeue",
        actor=actor,
        tenant_id=item.get("tenant_id"),
        target=f"delete_queue/{job_id}",
        metadata={"status": item.get("status"), "attempts": item.get("attempts")},
    )
    db.commit()
    return {"ok": True, "item": item}






@super_router.post("/delete-queue/{job_id}/fail-now")
def super_fail_delete_job_now(
    job_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    actor = str(claims.get("sub") or "unknown")
    reason = str(payload.get("reason") or "manual_fail_now").strip()
    try:
        item = fail_delete_job_now(db, job_id=job_id, reason=reason)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "queue_job_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="storage.delete_queue_fail_now",
        actor=actor,
        tenant_id=item.get("tenant_id"),
        target=f"delete_queue/{job_id}",
        metadata={"status": item.get("status"), "reason": reason},
    )
    db.commit()
    return {"ok": True, "item": item}

@super_router.post("/delete-queue/run-once")
def super_delete_queue_run_once(
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    actor = str(claims.get("sub") or "unknown")
    out = process_delete_queue_once(db, limit=limit)

    write_audit(
        db,
        action="storage.delete_queue_run_once",
        actor=actor,
        tenant_id=None,
        target="delete_queue/run_once",
        metadata={"processed": out["processed"], "done": out["done"], "failed": out["failed"], "limit": limit},
    )
    db.commit()
    return {"ok": True, "requested_by": actor, "result": out}

@policy_router.post("/grants/issue-upload")
def grant_issue_upload(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    try:
        out = issue_upload_grant(
            db,
            tenant_id=tenant_id,
            actor=actor,
            file_name=str(payload.get("file_name") or "").strip(),
            content_type=str(payload.get("content_type") or "application/octet-stream").strip(),
            retention_hours=payload.get("retention_hours"),
            ttl_seconds=payload.get("ttl_seconds"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(db, action="storage.grant_issue_upload", actor=actor, tenant_id=tenant_id, target=f"grant/{out['grant_id']}", metadata={"expires_at": out["expires_at"]})
    db.commit()
    return {"ok": True, "grant": out}


@policy_router.post("/grants/issue-download")
def grant_issue_download(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    try:
        out = issue_download_grant(
            db,
            tenant_id=tenant_id,
            actor=actor,
            object_id=str(payload.get("object_id") or "").strip(),
            ttl_seconds=payload.get("ttl_seconds"),
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "storage_object_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(db, action="storage.grant_issue_download", actor=actor, tenant_id=tenant_id, target=f"grant/{out['grant_id']}", metadata={"object_id": out.get("object_id")})
    db.commit()
    return {"ok": True, "grant": out}


@policy_router.post("/grants/exchange")
def grant_exchange(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    token = str(payload.get("grant_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="grant_token_required")

    try:
        out = exchange_grant(db, tenant_id=tenant_id, actor=actor, grant_token=token)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail in {"grant_not_found", "storage_object_not_found"} else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(db, action="storage.grant_exchange", actor=actor, tenant_id=tenant_id, target=f"grant/{out['grant_id']}", metadata={"action": out["action"]})
    db.commit()
    return {"ok": True, **out}


@router.post("/presign-upload")
def presign_upload(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    file_name = str(payload.get("file_name") or "").strip()
    content_type = str(payload.get("content_type") or "application/octet-stream").strip()
    retention_hours = payload.get("retention_hours")

    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    if not file_name:
        raise HTTPException(status_code=400, detail="file_name_required")

    try:
        out = create_verification_doc_slot(
            db,
            tenant_id=tenant_id,
            actor=actor,
            file_name=file_name,
            content_type=content_type,
            retention_hours=retention_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(db, action="storage.verification_doc_presign", actor=actor, tenant_id=tenant_id, target=f"storage/{out['id']}", metadata={"file_name": file_name, "retention_until": out["retention_until"]})
    db.commit()
    return {"ok": True, "slot": out}


@router.post("/{object_id}/presign-download")
def presign_download(object_id: str, claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    try:
        out = create_download_slot(db, tenant_id=tenant_id, object_id=object_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "storage_object_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(db, action="storage.verification_doc_presign_download", actor=actor, tenant_id=tenant_id, target=f"storage/{object_id}", metadata={"expires_in_seconds": out["expires_in_seconds"]})
    db.commit()
    return {"ok": True, "slot": out}


@router.post("/{object_id}/mark-uploaded")
def confirm_uploaded(object_id: str, payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    size_bytes = int(payload.get("size_bytes") or 0)
    sha256 = str(payload.get("sha256") or "").strip()

    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="size_bytes_required")
    if not sha256:
        raise HTTPException(status_code=400, detail="sha256_required")

    try:
        out = mark_uploaded(db, tenant_id=tenant_id, object_id=object_id, size_bytes=size_bytes, sha256=sha256)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "storage_object_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(db, action="storage.verification_doc_uploaded", actor=actor, tenant_id=tenant_id, target=f"storage/{object_id}", metadata={"size_bytes": size_bytes})
    db.commit()
    return {"ok": True, "item": out}


@router.get("")
def list_docs(include_deleted: bool = False, claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    return {"ok": True, "items": list_verification_docs(db, tenant_id=tenant_id, include_deleted=include_deleted)}


@router.delete("/{object_id}")
def delete_doc_endpoint(object_id: str, claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    try:
        out = delete_doc(db, tenant_id=tenant_id, object_id=object_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    write_audit(db, action="storage.verification_doc_deleted", actor=actor, tenant_id=tenant_id, target=f"storage/{object_id}", metadata={"at": datetime.now(timezone.utc).isoformat()})
    db.commit()
    return {"ok": True, "item": out}