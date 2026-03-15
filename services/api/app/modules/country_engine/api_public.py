from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.modules.country_engine.registry import get_country_template, list_country_infos

router = APIRouter(prefix="/public/country-engine", tags=["public-country-engine"])


@router.get("/version")
def version() -> dict:
    return {
        "engine": "country_engine",
        "api_version": "v1",
        "template_version": "v1",
    }


@router.get("/countries")
def countries() -> list[dict]:
    return [x.model_dump() for x in list_country_infos()]


@router.get("/template/{iso2}")
def template(iso2: str, purpose: str = Query(default="onboarding_company")) -> dict:
    if purpose != "onboarding_company":
        raise HTTPException(status_code=400, detail="purpose_not_supported")
    tpl = get_country_template(iso2=iso2, purpose=purpose)
    return tpl.model_dump()
