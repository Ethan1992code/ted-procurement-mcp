from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SupplierProfile(BaseModel):
    profile_id: str = Field(min_length=1)
    products: list[str] = Field(min_length=1)
    cpv_codes: list[str] = Field(default_factory=list)
    target_countries: list[str] = Field(default_factory=list)
    excluded_countries: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    moq: int | None = Field(default=None, ge=1)
    lead_time_days: int | None = Field(default=None, ge=1)
    notes: str | None = None


class SupplierProfileService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def upsert(self, **data: Any) -> dict[str, Any]:
        profile = SupplierProfile(**data).model_dump()
        self.store.upsert_supplier_profile(profile)
        return profile

    def get(self, profile_id: str) -> dict[str, Any] | None:
        return self.store.get_supplier_profile(profile_id)
