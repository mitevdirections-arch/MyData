from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.settings import get_settings
from app.db.models import StorageDeleteQueue, StorageObjectMeta
from app.db.session import get_session_factory
from app.modules.storage_policy.service import enqueue_delete_retry


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _safe_delete(client, *, bucket: str, key: str) -> None:
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "")).strip()
        if code not in {"NoSuchKey", "NotFound"}:
            raise


def _next_retry_at(attempts: int) -> datetime:
    s = get_settings()
    base = int(s.storage_delete_retry_base_seconds)
    mx = int(s.storage_delete_retry_max_seconds)
    delay = min(base * (2 ** max(0, attempts - 1)), mx)
    return _now() + timedelta(seconds=delay)


def main() -> int:
    s = get_settings()
    if not s.storage_hard_delete_enabled:
        print("retention_worker=disabled")
        return 0

    now = _now()
    factory = get_session_factory()
    db = factory()
    deleted_count = 0
    queued_count = 0
    retried_done = 0
    retried_failed = 0

    try:
        client = _s3_client()

        # 1) expiry-driven deletes (first attempt)
        rows = (
            db.query(StorageObjectMeta)
            .filter(
                StorageObjectMeta.status.in_(["ACTIVE", "EXPIRED", "DELETED"]),
                StorageObjectMeta.retention_until < now,
            )
            .order_by(StorageObjectMeta.retention_until.asc())
            .limit(int(s.storage_delete_batch_size))
            .all()
        )

        for row in rows:
            try:
                _safe_delete(client, bucket=row.bucket, key=row.object_key)
                row.status = "HARD_DELETED"
                row.deleted_at = now
                deleted_count += 1
            except Exception as exc:  # noqa: BLE001
                row.status = "DELETED"
                row.deleted_at = now
                db.commit()
                enqueue_delete_retry(
                    db,
                    tenant_id=row.tenant_id,
                    bucket=row.bucket,
                    object_key=row.object_key,
                    object_meta_id=str(row.id),
                    reason="retention",
                    error=str(exc),
                )
                queued_count += 1

        db.commit()

        # 2) retry queue
        jobs = (
            db.query(StorageDeleteQueue)
            .filter(
                StorageDeleteQueue.status.in_(["PENDING", "RETRY_SCHEDULED"]),
                StorageDeleteQueue.next_attempt_at <= _now(),
            )
            .order_by(StorageDeleteQueue.next_attempt_at.asc())
            .limit(int(s.storage_delete_queue_batch_size))
            .all()
        )

        for job in jobs:
            try:
                _safe_delete(client, bucket=job.bucket, key=job.object_key)
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
                retried_done += 1
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
                retried_failed += 1

        db.commit()

        print(
            f"retention_hard_deleted={deleted_count} queued={queued_count} retry_done={retried_done} retry_failed={retried_failed}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())