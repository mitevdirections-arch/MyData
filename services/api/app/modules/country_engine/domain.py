from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DateStyle(str, Enum):
    DMY = "DMY"
    MDY = "MDY"
    YMD = "YMD"


class TimeStyle(str, Enum):
    H24 = "H24"
    H12 = "H12"


class UnitSystem(str, Enum):
    METRIC = "metric"
    IMPERIAL = "imperial"
    MIXED = "mixed"


class CountryInfo(BaseModel):
    iso2: str = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1)


class CountryDefaults(BaseModel):
    default_locale: str = "en"
    default_time_zone: str = "UTC"
    date_style: DateStyle = DateStyle.DMY
    time_style: TimeStyle = TimeStyle.H24
    unit_system: UnitSystem = UnitSystem.METRIC


class CountryTemplate(BaseModel):
    version: str = "v1"
    purpose: str = "onboarding_company"
    country: CountryInfo
    defaults: CountryDefaults
    tax_help: str | None = None
    tax_example: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
