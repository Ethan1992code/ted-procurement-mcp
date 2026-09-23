from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TedSearchRequest(BaseModel):
    """Request body for TED API v3 POST /notices/search."""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(min_length=1)
    fields: list[str] = Field(min_length=1)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=25, ge=1, le=250)
    scope: Literal["LATEST", "ACTIVE", "ALL"] = "ACTIVE"
    check_query_syntax: bool = Field(default=False, alias="checkQuerySyntax")
    pagination_mode: Literal["PAGE_NUMBER", "ITERATION"] = Field(
        default="PAGE_NUMBER", alias="paginationMode"
    )
    iteration_next_token: str | None = Field(default=None, alias="iterationNextToken")
    only_latest_versions: bool = Field(default=True, alias="onlyLatestVersions")

    @model_validator(mode="after")
    def validate_page_budget(self):
        # TED caps one response page at 10,000 field cells. publication-number
        # and links are returned implicitly, so include them in the budget.
        effective_fields = set(self.fields) | {"publication-number", "links"}
        if len(effective_fields) * self.limit > 10_000:
            raise ValueError(
                "TED page field budget exceeds 10,000 cells; reduce fields or limit"
            )
        return self

    def to_payload(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)
