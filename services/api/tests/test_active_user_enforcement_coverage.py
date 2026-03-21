from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.modules.licensing.service import LicensingPolicyError, service as licensing_service
from app.modules.profile.service import WORKSPACE_TENANT, service as workspace_service
from app.modules.profile.user_domain_service import service as user_domain_service


class _FakeQuery:
    def __init__(self, *, first_row=None) -> None:
        self._first_row = first_row

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def first(self):
        return self._first_row


class _FakeDB:
    def __init__(self, *, first_row=None) -> None:
        self._first_row = first_row

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(first_row=self._first_row)

    def add(self, *_args, **_kwargs) -> None:
        return None

    def flush(self) -> None:
        return None


class _SequencedDB:
    def __init__(self, first_rows: list[object | None]) -> None:
        self._first_rows = list(first_rows)

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        row = self._first_rows.pop(0) if self._first_rows else None
        return _FakeQuery(first_row=row)

    def flush(self) -> None:
        return None


def test_set_workspace_user_roles_requires_existing_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _FakeDB(first_row=None)
    monkeypatch.setattr(workspace_service, "_ensure_default_roles", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="user_membership_required"):
        workspace_service.set_workspace_user_roles(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id="tenant-coverage",
            user_id="new-user",
            role_codes=[],
            actor="tester",
        )


def test_user_domain_lazy_workspace_user_creation_is_seat_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _FakeDB(first_row=None)
    monkeypatch.setattr(
        licensing_service,
        "assert_workspace_user_seat_available",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LicensingPolicyError(
                "CORE_SEAT_LIMIT_EXCEEDED",
                payload={"seat_limit": 3, "active_user_count": 3, "attempted_user_count": 4},
            )
        ),
    )

    with pytest.raises(ValueError, match="core_seat_limit_exceeded"):
        user_domain_service._ensure_workspace_user(  # noqa: SLF001
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id="tenant-coverage",
            user_id="new-user",
            actor="tester",
        )


def test_update_user_profile_reactivation_is_seat_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_row = SimpleNamespace(
        workspace_type=WORKSPACE_TENANT,
        workspace_id="tenant-coverage",
        user_id="existing-user",
        first_name=None,
        last_name=None,
        display_name="Existing User",
        date_of_birth=None,
        employee_code=None,
        contact_email="existing@tenant.local",
        contact_phone=None,
        address_country_code=None,
        address_line1=None,
        address_line2=None,
        address_city=None,
        address_postal_code=None,
        bank_account_holder=None,
        bank_iban=None,
        bank_swift=None,
        bank_name=None,
        bank_currency=None,
        job_title=None,
        department=None,
        employment_status="INACTIVE",
        preferred_locale="en",
        preferred_time_zone="UTC",
        date_style="YMD",
        time_style="H24",
        unit_system="metric",
        metadata_json={},
        updated_by="tester",
        updated_at=None,
    )
    workspace_user_row = SimpleNamespace(
        display_name="Existing User",
        email="existing@tenant.local",
        job_title=None,
        department=None,
        employment_status="INACTIVE",
        updated_by="tester",
        updated_at=None,
    )
    db = _SequencedDB([profile_row, workspace_user_row])

    monkeypatch.setattr(
        user_domain_service,
        "get_or_create_user_profile",
        lambda *_args, **_kwargs: {
            "workspace_type": WORKSPACE_TENANT,
            "workspace_id": "tenant-coverage",
            "user_id": "existing-user",
        },
    )
    monkeypatch.setattr(
        licensing_service,
        "assert_workspace_user_seat_available",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LicensingPolicyError(
                "CORE_SEAT_LIMIT_EXCEEDED",
                payload={"seat_limit": 3, "active_user_count": 3, "attempted_user_count": 4},
            )
        ),
    )

    with pytest.raises(ValueError, match="core_seat_limit_exceeded"):
        user_domain_service.update_user_profile(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id="tenant-coverage",
            user_id="existing-user",
            actor="tester",
            payload={"employment": {"employment_status": "ACTIVE"}},
        )
