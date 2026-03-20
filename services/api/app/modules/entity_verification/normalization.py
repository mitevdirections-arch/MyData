from __future__ import annotations

import re
from typing import Any

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


def normalize_vat_number(value: Any, *, country_code: str | None = None) -> tuple[str | None, str | None]:
    vat_raw = _clean_opt(value, 64)
    if not vat_raw:
        return None, None

    normalized = _NON_ALNUM_RE.sub("", vat_raw.upper())[:64]
    if not normalized:
        return vat_raw, None

    cc = normalize_country_code(country_code) if country_code else ""
    if cc and normalized.startswith(cc):
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

