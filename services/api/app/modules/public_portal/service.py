from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import uuid

import boto3
from botocore.client import Config
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import get_settings as core_get_settings
from app.db.models import (
    PublicBrandAsset,
    PublicPageDraft,
    PublicPagePublished,
    PublicProfileSettings,
    PublicWorkspaceSettings,
    WorkspaceAddress,
    WorkspaceContactPoint,
    WorkspaceOrganizationProfile,
)
from app.modules.i18n.service import service as i18n_service
from app.modules.profile.service import PLATFORM_WORKSPACE_ID, WORKSPACE_PLATFORM, WORKSPACE_TENANT

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_workspace_type(workspace_type: str) -> str:
    val = str(workspace_type or "").strip().upper()
    if val not in {WORKSPACE_TENANT, WORKSPACE_PLATFORM}:
        raise ValueError("workspace_type_invalid")
    return val


def _normalize_workspace_id(workspace_id: str) -> str:
    val = str(workspace_id or "").strip()
    if not val:
        raise ValueError("workspace_id_required")
    return val[:64]


def _allowed_logo_content_types() -> set[str]:
    raw = core_get_settings().public_logo_allowed_content_types
    return {x.strip().lower() for x in str(raw or "").split(",") if x.strip()}


def _validate_logo_content_type(content_type: str) -> str:
    ct = str(content_type or "").strip().lower()
    if ct not in _allowed_logo_content_types():
        raise ValueError("logo_content_type_not_allowed")
    return ct


def _validate_sha256(val: str) -> str:
    out = str(val or "").strip().lower()
    if not SHA256_RE.match(out):
        raise ValueError("sha256_invalid")
    return out


def _s3_client():
    s = core_get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.storage_endpoint,
        aws_access_key_id=s.storage_access_key,
        aws_secret_access_key=s.storage_secret_key,
        region_name=s.storage_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _safe_file_name(file_name: str) -> str:
    safe = str(file_name or "").replace("\\", "_").replace("/", "_").strip()
    if not safe:
        raise ValueError("file_name_required")
    return safe[:255]


def _empty_sections() -> dict:
    return {
        "company_info": {"visible": True, "data": {}},
        "fleet": {"visible": False, "data": {}},
        "contacts": {"visible": True, "data": {}},
        "price_list": {"visible": False, "data": {}},
        "working_hours": {"visible": False, "data": {}},
        "presentation": {"visible": True, "data": {}},
        "custom": {"visible": False, "data": {}},
    }


def _truncate(v: str, n: int) -> str:
    return str(v or "")[:n]


def _sanitize_json(value, *, depth: int = 0):
    if depth > 8:
        return None
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:200]:
            key = _truncate(str(k), 96)
            out[key] = _sanitize_json(v, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize_json(x, depth=depth + 1) for x in value[:200]]
    if isinstance(value, str):
        return _truncate(value, 5000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _truncate(str(value), 5000)


def _org_profile(db: Session, *, workspace_type: str, workspace_id: str) -> WorkspaceOrganizationProfile | None:
    return (
        db.query(WorkspaceOrganizationProfile)
        .filter(
            WorkspaceOrganizationProfile.workspace_type == workspace_type,
            WorkspaceOrganizationProfile.workspace_id == workspace_id,
        )
        .first()
    )



def _public_contact_points(db: Session, *, workspace_type: str, workspace_id: str) -> list[dict]:
    rows = (
        db.query(WorkspaceContactPoint)
        .filter(
            WorkspaceContactPoint.workspace_type == workspace_type,
            WorkspaceContactPoint.workspace_id == workspace_id,
            WorkspaceContactPoint.is_public == True,  # noqa: E712
        )
        .order_by(
            WorkspaceContactPoint.is_primary.desc(),
            WorkspaceContactPoint.sort_order.asc(),
            WorkspaceContactPoint.created_at.asc(),
        )
        .all()
    )
    out: list[dict] = []
    for row in rows:
        if not any([row.email, row.phone, row.website_url]):
            continue
        out.append(
            {
                "id": str(row.id),
                "contact_kind": row.contact_kind,
                "label": row.label,
                "email": row.email,
                "phone": row.phone,
                "website_url": row.website_url,
                "is_primary": bool(row.is_primary),
                "sort_order": int(row.sort_order or 0),
            }
        )
    return out


def _public_addresses(db: Session, *, workspace_type: str, workspace_id: str) -> list[dict]:
    rows = (
        db.query(WorkspaceAddress)
        .filter(
            WorkspaceAddress.workspace_type == workspace_type,
            WorkspaceAddress.workspace_id == workspace_id,
            WorkspaceAddress.is_public == True,  # noqa: E712
        )
        .order_by(
            WorkspaceAddress.is_primary.desc(),
            WorkspaceAddress.sort_order.asc(),
            WorkspaceAddress.created_at.asc(),
        )
        .all()
    )
    out: list[dict] = []
    for row in rows:
        if not any([row.country_code, row.line1, row.line2, row.city, row.postal_code]):
            continue
        out.append(
            {
                "id": str(row.id),
                "address_kind": row.address_kind,
                "label": row.label,
                "country_code": row.country_code,
                "line1": row.line1,
                "line2": row.line2,
                "city": row.city,
                "postal_code": row.postal_code,
                "is_primary": bool(row.is_primary),
                "sort_order": int(row.sort_order or 0),
            }
        )
    return out


def _active_logo_asset(db: Session, *, workspace_type: str, workspace_id: str) -> PublicBrandAsset | None:
    return (
        db.query(PublicBrandAsset)
        .filter(
            PublicBrandAsset.workspace_type == workspace_type,
            PublicBrandAsset.workspace_id == workspace_id,
            PublicBrandAsset.asset_kind == "LOGO",
            PublicBrandAsset.status == "ACTIVE",
        )
        .order_by(PublicBrandAsset.activated_at.desc(), PublicBrandAsset.created_at.desc())
        .first()
    )


def _logo_download_url(asset: PublicBrandAsset | None) -> str | None:
    if asset is None:
        return None
    s = core_get_settings()
    ttl = max(30, min(int(s.storage_download_presign_ttl_seconds), 300))
    return _s3_client().generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": asset.bucket, "Key": asset.object_key},
        ExpiresIn=ttl,
    )


def _default_page_content(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    locale: str,
    settings: PublicWorkspaceSettings,
) -> dict:
    org = _org_profile(db, workspace_type=workspace_type, workspace_id=workspace_id)
    logo = _active_logo_asset(db, workspace_type=workspace_type, workspace_id=workspace_id)

    legal_name = org.legal_name if org is not None else ("MyData Platform" if workspace_type == WORKSPACE_PLATFORM else f"Tenant {workspace_id}")
    activity_summary = org.activity_summary if org is not None else None

    public_contacts = _public_contact_points(db, workspace_type=workspace_type, workspace_id=workspace_id)
    primary_public_contact = next((x for x in public_contacts if bool(x.get("is_primary"))), public_contacts[0] if public_contacts else None)

    if primary_public_contact is None and org is not None and any([org.contact_email, org.contact_phone, org.website_url]):
        primary_public_contact = {
            "id": None,
            "contact_kind": "GENERAL",
            "label": "Primary",
            "email": org.contact_email,
            "phone": org.contact_phone,
            "website_url": org.website_url,
            "is_primary": True,
            "sort_order": 0,
        }
        public_contacts = [primary_public_contact]

    public_addresses = _public_addresses(db, workspace_type=workspace_type, workspace_id=workspace_id)

    sections = _empty_sections()
    sections["company_info"]["visible"] = bool(settings.show_company_info)
    sections["company_info"]["data"] = {
        "legal_name": legal_name,
        "vat_number": (org.vat_number if org is not None else None),
        "registration_number": (org.registration_number if org is not None else None),
        "legal_form": (org.company_size_hint if org is not None else None),
        "industry": (org.industry if org is not None else None),
        "public_addresses": public_addresses,
    }

    sections["presentation"]["visible"] = True
    sections["presentation"]["data"] = {
        "activity_summary": activity_summary,
        "presentation_text": (org.presentation_text if org is not None else None),
    }

    sections["contacts"]["visible"] = bool(settings.show_contacts)
    sections["contacts"]["data"] = {
        "email": ((primary_public_contact or {}).get("email") if isinstance(primary_public_contact, dict) else None),
        "phone": ((primary_public_contact or {}).get("phone") if isinstance(primary_public_contact, dict) else None),
        "website_url": ((primary_public_contact or {}).get("website_url") if isinstance(primary_public_contact, dict) else None),
        "items": public_contacts,
    }

    sections["fleet"]["visible"] = bool(settings.show_fleet)
    sections["price_list"]["visible"] = bool(settings.show_price_list)
    sections["working_hours"]["visible"] = bool(settings.show_working_hours)

    return {
        "schema_version": "public-page-v1",
        "workspace": {"type": workspace_type, "id": workspace_id},
        "locale": locale,
        "title": legal_name,
        "tagline": activity_summary,
        "branding": {
            "logo_asset_id": (str(logo.id) if logo is not None else None),
            "logo_url": _logo_download_url(logo),
            "primary_color": "#0B1220",
            "accent_color": "#0EA5E9",
        },
        "sections": sections,
        "seo": {
            "meta_title": legal_name,
            "meta_description": _truncate(activity_summary or legal_name, 180),
        },
    }


def _effective_locale_for_workspace(db: Session, *, workspace_type: str, workspace_id: str, requested_locale: str | None) -> str:
    policy = i18n_service.get_workspace_policy(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
    )
    return i18n_service.resolve_supported_locale(requested_locale, fallback=str(policy.get("default_locale") or "en"))


def _workspace_settings_defaults(db: Session, *, workspace_type: str, workspace_id: str) -> dict:
    legacy = None
    if workspace_type == WORKSPACE_TENANT:
        legacy = db.query(PublicProfileSettings).filter(PublicProfileSettings.tenant_id == workspace_id).first()

    return {
        "show_company_info": bool(legacy.show_company_info) if legacy is not None else True,
        "show_fleet": bool(legacy.show_fleet) if legacy is not None else False,
        "show_contacts": bool(legacy.show_contacts) if legacy is not None else True,
        "show_price_list": bool(legacy.show_price_list) if legacy is not None else False,
        "show_working_hours": bool(legacy.show_working_hours) if legacy is not None else False,
        "updated_by": (legacy.updated_by if legacy is not None else "system"),
        "updated_at": (legacy.updated_at if legacy is not None else None),
    }


def _workspace_settings_read_model(db: Session, *, workspace_type: str, workspace_id: str) -> PublicWorkspaceSettings:
    row = (
        db.query(PublicWorkspaceSettings)
        .filter(PublicWorkspaceSettings.workspace_type == workspace_type, PublicWorkspaceSettings.workspace_id == workspace_id)
        .first()
    )
    if row is not None:
        return row

    defaults = _workspace_settings_defaults(db, workspace_type=workspace_type, workspace_id=workspace_id)
    updated_at_val = defaults.get("updated_at")
    return PublicWorkspaceSettings(
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        show_company_info=bool(defaults.get("show_company_info")),
        show_fleet=bool(defaults.get("show_fleet")),
        show_contacts=bool(defaults.get("show_contacts")),
        show_price_list=bool(defaults.get("show_price_list")),
        show_working_hours=bool(defaults.get("show_working_hours")),
        updated_by=str(defaults.get("updated_by") or "system"),
        updated_at=(updated_at_val if isinstance(updated_at_val, datetime) else _now()),
    )


def _workspace_settings_payload(settings: PublicWorkspaceSettings) -> dict:
    return {
        "show_company_info": bool(settings.show_company_info),
        "show_fleet": bool(settings.show_fleet),
        "show_contacts": bool(settings.show_contacts),
        "show_price_list": bool(settings.show_price_list),
        "show_working_hours": bool(settings.show_working_hours),
        "updated_by": settings.updated_by,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def get_workspace_settings(db: Session, *, workspace_type: str, workspace_id: str) -> PublicWorkspaceSettings:
    wtype = _normalize_workspace_type(workspace_type)
    wid = _normalize_workspace_id(workspace_id)

    row = (
        db.query(PublicWorkspaceSettings)
        .filter(PublicWorkspaceSettings.workspace_type == wtype, PublicWorkspaceSettings.workspace_id == wid)
        .first()
    )
    if row is None:
        legacy = None
        if wtype == WORKSPACE_TENANT:
            legacy = db.query(PublicProfileSettings).filter(PublicProfileSettings.tenant_id == wid).first()

        row = PublicWorkspaceSettings(
            workspace_type=wtype,
            workspace_id=wid,
            show_company_info=(legacy.show_company_info if legacy is not None else True),
            show_fleet=(legacy.show_fleet if legacy is not None else False),
            show_contacts=(legacy.show_contacts if legacy is not None else True),
            show_price_list=(legacy.show_price_list if legacy is not None else False),
            show_working_hours=(legacy.show_working_hours if legacy is not None else False),
            updated_by=(legacy.updated_by if legacy is not None else "system"),
            updated_at=(legacy.updated_at if legacy is not None else _now()),
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            # Concurrent lazy-create for same workspace; recover by selecting existing row.
            db.rollback()
            row = (
                db.query(PublicWorkspaceSettings)
                .filter(PublicWorkspaceSettings.workspace_type == wtype, PublicWorkspaceSettings.workspace_id == wid)
                .first()
            )
            if row is None:
                raise
    return row


def update_workspace_settings(db: Session, *, workspace_type: str, workspace_id: str, payload: dict, actor: str) -> PublicWorkspaceSettings:
    row = get_workspace_settings(db=db, workspace_type=workspace_type, workspace_id=workspace_id)
    for key in ["show_company_info", "show_fleet", "show_contacts", "show_price_list", "show_working_hours"]:
        if key in payload:
            setattr(row, key, bool(payload.get(key)))
    row.updated_by = str(actor or "unknown")
    row.updated_at = _now()
    db.flush()
    return row


def _draft_row(db: Session, *, workspace_type: str, workspace_id: str, locale: str, page_code: str) -> PublicPageDraft | None:
    return (
        db.query(PublicPageDraft)
        .filter(
            PublicPageDraft.workspace_type == workspace_type,
            PublicPageDraft.workspace_id == workspace_id,
            PublicPageDraft.locale == locale,
            PublicPageDraft.page_code == page_code,
        )
        .first()
    )


def _latest_published_row(db: Session, *, workspace_type: str, workspace_id: str, locale: str, page_code: str) -> PublicPagePublished | None:
    return (
        db.query(PublicPagePublished)
        .filter(
            PublicPagePublished.workspace_type == workspace_type,
            PublicPagePublished.workspace_id == workspace_id,
            PublicPagePublished.locale == locale,
            PublicPagePublished.page_code == page_code,
        )
        .order_by(PublicPagePublished.version.desc(), PublicPagePublished.published_at.desc())
        .first()
    )


def get_or_create_draft(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    locale: str,
    page_code: str,
    actor: str,
) -> PublicPageDraft:
    row = _draft_row(db, workspace_type=workspace_type, workspace_id=workspace_id, locale=locale, page_code=page_code)
    if row is not None:
        return row

    settings = get_workspace_settings(db, workspace_type=workspace_type, workspace_id=workspace_id)
    content = _default_page_content(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        settings=settings,
    )
    row = PublicPageDraft(
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
        content_json=content,
        updated_by=str(actor or "unknown"),
        updated_at=_now(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent lazy-create for same draft key; recover by selecting existing row.
        db.rollback()
        row = _draft_row(db, workspace_type=workspace_type, workspace_id=workspace_id, locale=locale, page_code=page_code)
        if row is None:
            raise
    return row


def update_draft(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    locale: str,
    page_code: str,
    payload: dict,
    actor: str,
) -> PublicPageDraft:
    row = get_or_create_draft(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
        actor=actor,
    )

    clean = _sanitize_json(payload)
    raw = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > 200_000:
        raise ValueError("draft_payload_too_large")

    row.content_json = clean if isinstance(clean, dict) else {}
    row.updated_by = str(actor or "unknown")
    row.updated_at = _now()
    db.flush()
    return row


def publish_draft(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    locale: str,
    page_code: str,
    actor: str,
    note: str | None,
) -> PublicPagePublished:
    draft = get_or_create_draft(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
        actor=actor,
    )

    current_version = int(
        db.query(func.coalesce(func.max(PublicPagePublished.version), 0))
        .filter(
            PublicPagePublished.workspace_type == workspace_type,
            PublicPagePublished.workspace_id == workspace_id,
            PublicPagePublished.locale == locale,
            PublicPagePublished.page_code == page_code,
        )
        .scalar()
        or 0
    )

    row = PublicPagePublished(
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
        version=current_version + 1,
        content_json=dict(draft.content_json or {}),
        publish_note=(str(note or "").strip()[:1024] or None),
        published_by=str(actor or "unknown"),
        published_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def build_editor_state(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    locale: str,
    page_code: str,
    actor: str,
) -> dict:
    # Read-only editor GET path: no lazy writes under high concurrency.
    settings = _workspace_settings_read_model(db, workspace_type=workspace_type, workspace_id=workspace_id)

    draft = _draft_row(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
    )
    if draft is None:
        draft_payload = {
            "id": None,
            "content": _default_page_content(
                db,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                locale=locale,
                settings=settings,
            ),
            "updated_by": str(actor or "system"),
            "updated_at": None,
        }
    else:
        draft_payload = {
            "id": str(draft.id),
            "content": draft.content_json or {},
            "updated_by": draft.updated_by,
            "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        }

    published = _latest_published_row(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
    )

    assets = list_brand_assets(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        asset_kind="LOGO",
        limit=20,
    )

    return {
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "locale": locale,
        "page_code": page_code,
        "settings": _workspace_settings_payload(settings),
        "draft": draft_payload,
        "published": (
            {
                "id": str(published.id),
                "version": int(published.version),
                "content": published.content_json or {},
                "publish_note": published.publish_note,
                "published_by": published.published_by,
                "published_at": published.published_at.isoformat() if published.published_at else None,
            }
            if published is not None
            else None
        ),
        "assets": assets,
    }


def build_public_payload(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    requested_locale: str | None,
    page_code: str,
) -> dict:
    locale = _effective_locale_for_workspace(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        requested_locale=requested_locale,
    )

    published = _latest_published_row(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        locale=locale,
        page_code=page_code,
    )

    if published is not None:
        content = dict(published.content_json or {})
        meta = {
            "published": True,
            "version": int(published.version),
            "published_at": published.published_at.isoformat() if published.published_at else None,
            "published_by": published.published_by,
        }
    else:
        settings = _workspace_settings_read_model(db, workspace_type=workspace_type, workspace_id=workspace_id)
        content = _default_page_content(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            locale=locale,
            settings=settings,
        )
        meta = {"published": False, "version": None, "published_at": None, "published_by": None}

    # Refresh logo URL for every public read (short-lived URL).
    branding = content.get("branding") if isinstance(content.get("branding"), dict) else {}
    logo_id = str(branding.get("logo_asset_id") or "").strip()
    if logo_id:
        asset = (
            db.query(PublicBrandAsset)
            .filter(
                PublicBrandAsset.id == logo_id,
                PublicBrandAsset.workspace_type == workspace_type,
                PublicBrandAsset.workspace_id == workspace_id,
                PublicBrandAsset.status == "ACTIVE",
            )
            .first()
        )
        branding["logo_url"] = _logo_download_url(asset)
        content["branding"] = branding

    return {
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "locale": locale,
        "page_code": page_code,
        "meta": meta,
        "content": content,
    }


def create_logo_upload_slot(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    actor: str,
    file_name: str,
    content_type: str,
) -> dict:
    s = core_get_settings()
    safe_name = _safe_file_name(file_name)
    ct = _validate_logo_content_type(content_type)

    asset_id = str(uuid.uuid4())
    object_key = f"public-assets/{workspace_type.lower()}/{workspace_id}/logo/{asset_id}/{safe_name}"

    row = PublicBrandAsset(
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        asset_kind="LOGO",
        status="PENDING_UPLOAD",
        file_name=safe_name,
        content_type=ct,
        size_bytes=None,
        sha256=None,
        storage_provider=s.storage_provider,
        bucket=s.storage_bucket_public_assets,
        object_key=object_key,
        created_by=str(actor or "unknown"),
        created_at=_now(),
        activated_at=None,
        deactivated_at=None,
        updated_at=_now(),
    )
    db.add(row)
    db.flush()

    expires = max(60, min(int(s.storage_presign_ttl_seconds), 3600))
    upload_url = _s3_client().generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": row.bucket,
            "Key": row.object_key,
            "ContentType": row.content_type,
        },
        ExpiresIn=expires,
    )

    return {
        "id": str(row.id),
        "asset_kind": row.asset_kind,
        "bucket": row.bucket,
        "object_key": row.object_key,
        "upload_url": upload_url,
        "method": "PUT",
        "expires_in_seconds": expires,
        "max_bytes": int(s.public_logo_max_bytes),
        "allowed_content_types": sorted(_allowed_logo_content_types()),
        "mode": "SIGNED_PRESIGN",
    }


def mark_logo_uploaded(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    asset_id: str,
    size_bytes: int,
    sha256: str,
) -> dict:
    row = (
        db.query(PublicBrandAsset)
        .filter(
            PublicBrandAsset.id == asset_id,
            PublicBrandAsset.workspace_type == workspace_type,
            PublicBrandAsset.workspace_id == workspace_id,
            PublicBrandAsset.asset_kind == "LOGO",
        )
        .first()
    )
    if row is None:
        raise ValueError("public_asset_not_found")
    if row.status not in {"PENDING_UPLOAD", "ACTIVE"}:
        raise ValueError("public_asset_invalid_state")

    max_bytes = int(core_get_settings().public_logo_max_bytes)
    size_val = int(size_bytes)
    if size_val <= 0 or size_val > max_bytes:
        raise ValueError("public_logo_size_invalid")

    row.size_bytes = size_val
    row.sha256 = _validate_sha256(sha256)
    row.status = "ACTIVE"
    row.activated_at = _now()
    row.updated_at = _now()

    # Deactivate previous active logos in same workspace.
    db.query(PublicBrandAsset).filter(
        PublicBrandAsset.workspace_type == workspace_type,
        PublicBrandAsset.workspace_id == workspace_id,
        PublicBrandAsset.asset_kind == "LOGO",
        PublicBrandAsset.status == "ACTIVE",
        PublicBrandAsset.id != row.id,
    ).update(
        {
            PublicBrandAsset.status: "REPLACED",
            PublicBrandAsset.deactivated_at: _now(),
            PublicBrandAsset.updated_at: _now(),
        },
        synchronize_session=False,
    )

    db.flush()
    return {
        "id": str(row.id),
        "asset_kind": row.asset_kind,
        "status": row.status,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "logo_url": _logo_download_url(row),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_brand_assets(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    asset_kind: str = "LOGO",
    limit: int = 100,
) -> list[dict]:
    rows = (
        db.query(PublicBrandAsset)
        .filter(
            PublicBrandAsset.workspace_type == workspace_type,
            PublicBrandAsset.workspace_id == workspace_id,
            PublicBrandAsset.asset_kind == str(asset_kind or "LOGO").strip().upper(),
        )
        .order_by(PublicBrandAsset.updated_at.desc(), PublicBrandAsset.created_at.desc())
        .limit(max(1, min(int(limit), 500)))
        .all()
    )
    return [
        {
            "id": str(x.id),
            "asset_kind": x.asset_kind,
            "status": x.status,
            "file_name": x.file_name,
            "content_type": x.content_type,
            "size_bytes": x.size_bytes,
            "logo_url": (_logo_download_url(x) if x.status == "ACTIVE" else None),
            "created_at": x.created_at.isoformat() if x.created_at else None,
            "updated_at": x.updated_at.isoformat() if x.updated_at else None,
        }
        for x in rows
    ]


# Legacy wrappers kept for compatibility with previous tenant-only calls.
def get_settings(db: Session, tenant_id: str) -> PublicWorkspaceSettings:
    return get_workspace_settings(db, workspace_type=WORKSPACE_TENANT, workspace_id=tenant_id)


def update_settings(db: Session, *, tenant_id: str, payload: dict, actor: str) -> PublicWorkspaceSettings:
    return update_workspace_settings(db, workspace_type=WORKSPACE_TENANT, workspace_id=tenant_id, payload=payload, actor=actor)


def build_public_payload_legacy(tenant_id: str, settings: PublicWorkspaceSettings) -> dict:
    return {
        "tenant_id": tenant_id,
        "settings": {
            "show_company_info": bool(settings.show_company_info),
            "show_fleet": bool(settings.show_fleet),
            "show_contacts": bool(settings.show_contacts),
            "show_price_list": bool(settings.show_price_list),
            "show_working_hours": bool(settings.show_working_hours),
        },
    }