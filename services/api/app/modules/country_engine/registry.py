from __future__ import annotations

from app.modules.country_engine.domain import CountryDefaults, CountryInfo, CountryTemplate, DateStyle, TimeStyle, UnitSystem

_COUNTRY_NAMES = {
    "GB": "United Kingdom",
    "US": "United States",
    "AE": "United Arab Emirates",
    "BG": "Bulgaria",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "NL": "Netherlands",
    "ZZ": "Other / International",
}

_EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"
}


def _norm_iso2(iso2: str) -> str:
    x = (iso2 or "").strip().upper()
    if len(x) != 2:
        return "ZZ"
    return x


def list_country_infos() -> list[CountryInfo]:
    items = [CountryInfo(iso2=k, name=v) for k, v in _COUNTRY_NAMES.items() if k != "ZZ"]
    items.sort(key=lambda x: x.name)
    items.append(CountryInfo(iso2="ZZ", name=_COUNTRY_NAMES["ZZ"]))
    return items


def get_country_template(iso2: str, purpose: str = "onboarding_company") -> CountryTemplate:
    cc = _norm_iso2(iso2)

    if cc == "US":
        defaults = CountryDefaults(
            default_locale="en-US",
            default_time_zone="America/New_York",
            date_style=DateStyle.MDY,
            time_style=TimeStyle.H12,
            unit_system=UnitSystem.IMPERIAL,
        )
        return CountryTemplate(
            country=CountryInfo(iso2=cc, name=_COUNTRY_NAMES.get(cc, cc)),
            defaults=defaults,
            tax_help="US: EIN is 9 digits (format XX-XXXXXXX).",
            tax_example="12-3456789",
            meta={"resolved_iso2": cc, "engine": "country_engine"},
        )

    if cc == "GB":
        defaults = CountryDefaults(
            default_locale="en-GB",
            default_time_zone="Europe/London",
            date_style=DateStyle.DMY,
            time_style=TimeStyle.H24,
            unit_system=UnitSystem.METRIC,
        )
        return CountryTemplate(
            country=CountryInfo(iso2=cc, name=_COUNTRY_NAMES.get(cc, cc)),
            defaults=defaults,
            tax_help="UK VAT: usually 9 digits (optionally 12).",
            tax_example="GB123456789",
            meta={"resolved_iso2": cc, "engine": "country_engine"},
        )

    if cc == "AE":
        defaults = CountryDefaults(
            default_locale="en-AE",
            default_time_zone="Asia/Dubai",
            date_style=DateStyle.DMY,
            time_style=TimeStyle.H24,
            unit_system=UnitSystem.METRIC,
        )
        return CountryTemplate(
            country=CountryInfo(iso2=cc, name=_COUNTRY_NAMES.get(cc, cc)),
            defaults=defaults,
            tax_help="UAE: TRN is 15 digits.",
            tax_example="123456789012345",
            meta={"resolved_iso2": cc, "engine": "country_engine"},
        )

    if cc in _EU:
        defaults = CountryDefaults(
            default_locale="en",
            default_time_zone="Europe/Brussels",
            date_style=DateStyle.DMY,
            time_style=TimeStyle.H24,
            unit_system=UnitSystem.METRIC,
        )
        return CountryTemplate(
            country=CountryInfo(iso2=cc, name=_COUNTRY_NAMES.get(cc, cc)),
            defaults=defaults,
            tax_help="EU VAT: country prefix + local VAT number (format varies).",
            tax_example=f"{cc}123456789",
            meta={"resolved_iso2": cc, "engine": "country_engine", "region": "EU"},
        )

    defaults = CountryDefaults(
        default_locale="en",
        default_time_zone="UTC",
        date_style=DateStyle.DMY,
        time_style=TimeStyle.H24,
        unit_system=UnitSystem.METRIC,
    )
    return CountryTemplate(
        country=CountryInfo(iso2=cc, name=_COUNTRY_NAMES.get(cc, cc)),
        defaults=defaults,
        tax_help="Universal tax ID (lenient).",
        tax_example=None,
        meta={"resolved_iso2": cc, "engine": "country_engine", "fallback": cc == "ZZ"},
    )
