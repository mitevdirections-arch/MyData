from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class OnboardingPublicCreateRequest(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    country_code: str = Field(min_length=2, max_length=2)
    contact_email: EmailStr
    seat_count: int = Field(ge=1, le=5000)
    notes: str | None = Field(default=None, max_length=2000)
