from __future__ import annotations

import re
from typing import Any

from app.modules.entity_verification.schemas import ViesApplicabilityStatus

EU_COUNTRY_CODES = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "EL",
    "ES",
    "FI",
    "FR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
    "GR",
}
VIES_SCOPE_COUNTRY_CODES = set(EU_COUNTRY_CODES) | {"XI"}

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_WS_RE = re.compile(r"\s+")


def _clean(value: Any, size: int) -> str:
    return str(value or "").strip()[:size]


def _clean_opt(value: Any, size: int) -> str | None:
    out = _clean(value, size)
    return out if out else None


def normalize_country_code(value: Any) -> str:
    cc = _clean(value, 8).upper()
    if not cc:
        raise ValueError("country_code_required")
    if cc == "GR":
        return "EL"
    return cc


def normalize_legal_name(value: Any) -> str:
    raw = _clean(value, 255)
    if not raw:
        raise ValueError("legal_name_required")
    return _WS_RE.sub(" ", raw).strip()


def normalize_legal_name_key(value: Any) -> str:
    legal_name = normalize_legal_name(value).upper()
    return _NON_ALNUM_RE.sub("", legal_name)[:255]


def normalize_vat_number(
    value: Any = None,
    *,
    country_code: str | None = None,
    vat_number: Any = None,
) -> tuple[str | None, str | None]:
    source = value if vat_number is None else vat_number
    vat_raw = _clean_opt(source, 64)
    if not vat_raw:
        return None, None

    normalized = _NON_ALNUM_RE.sub("", vat_raw.upper())[:64]
    if not normalized:
        return vat_raw, None

    cc = normalize_country_code(country_code) if country_code else ""
    if cc and normalized.startswith(cc):
        return vat_raw, normalized
    if cc == "EL" and normalized.startswith("GR"):
        return vat_raw, f"EL{normalized[2:]}"
    # Keep explicit foreign prefixes untouched; applicability logic must see them as suspect.
    if cc and len(normalized) >= 2 and normalized[:2].isalpha():
        return vat_raw, normalized
    if cc and len(normalized) <= 62:
        return vat_raw, f"{cc}{normalized}"
    return vat_raw, normalized


def normalize_registration_number(value: Any) -> tuple[str | None, str | None]:
    reg_raw = _clean_opt(value, 64)
    if not reg_raw:
        return None, None
    normalized = _NON_ALNUM_RE.sub("", reg_raw.upper())[:64]
    return reg_raw, normalized or None


def normalize_address_lite(
    *,
    address_line: Any = None,
    postal_code: Any = None,
    city: Any = None,
    website_url: Any = None,
) -> dict[str, str | None]:
    return {
        "address_line": _clean_opt(address_line, 255),
        "postal_code": _clean_opt(postal_code, 32),
        "city": _clean_opt(city, 128),
        "website_url": _clean_opt(website_url, 512),
    }


def is_eu_vat_eligible(*, country_code: str | None, vat_number_normalized: str | None) -> bool:
    if not vat_number_normalized:
        return False
    cc = normalize_country_code(country_code) if country_code else ""
    if not cc or cc not in EU_COUNTRY_CODES:
        return False
    return str(vat_number_normalized).upper().startswith(cc)


def is_country_in_vies_scope(country_code: str | None) -> bool:
    if not country_code:
        return False
    try:
        cc = normalize_country_code(country_code)
    except Exception:  # noqa: BLE001
        return False
    return cc in VIES_SCOPE_COUNTRY_CODES


def _is_vat_body_plausible(body: str) -> bool:
    if not body:
        return False
    if not body.isalnum():
        return False
    return 4 <= len(body) <= 14


def get_vies_applicability_status(
    *,
    country_code: str | None,
    vat_number: str | None,
) -> ViesApplicabilityStatus:
    if not country_code or not str(country_code).strip():
        return ViesApplicabilityStatus.INSUFFICIENT_DATA
    if not vat_number or not str(vat_number).strip():
        return ViesApplicabilityStatus.INSUFFICIENT_DATA

    try:
        cc = normalize_country_code(country_code)
    except Exception:  # noqa: BLE001
        return ViesApplicabilityStatus.INSUFFICIENT_DATA

    if cc not in VIES_SCOPE_COUNTRY_CODES:
        return ViesApplicabilityStatus.VIES_NOT_APPLICABLE

    vat_raw, vat_norm = normalize_vat_number(country_code=cc, vat_number=vat_number)
    if not vat_raw or not vat_norm:
        return ViesApplicabilityStatus.INSUFFICIENT_DATA

    normalized_input = _NON_ALNUM_RE.sub("", str(vat_raw).upper())
    if len(normalized_input) >= 2 and normalized_input[:2].isalpha():
        input_prefix = normalized_input[:2]
        if input_prefix == "GR":
            input_prefix = "EL"
        if input_prefix != cc:
            return ViesApplicabilityStatus.VIES_FORMAT_SUSPECT

    if not vat_norm.startswith(cc):
        return ViesApplicabilityStatus.VIES_FORMAT_SUSPECT

    body = vat_norm[len(cc) :]
    if not _is_vat_body_plausible(body):
        return ViesApplicabilityStatus.VIES_FORMAT_SUSPECT

    return ViesApplicabilityStatus.VIES_ELIGIBLE


def is_vies_eligible(
    *,
    country_code: str | None,
    vat_number: str | None,
) -> bool:
    return (
        get_vies_applicability_status(
            country_code=country_code,
            vat_number=vat_number,
        )
        == ViesApplicabilityStatus.VIES_ELIGIBLE
    )
