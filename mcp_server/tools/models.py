"""Pydantic v2 input models for MCP tool validation.

Models validate tool arguments internally. They are NOT used as function
parameters (which would change the MCP wire protocol). Instead, tools
construct models from their flat args for validation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_TEAMS: list[str] = [
    "agents",
    "data_team",
    "product_team",
    "ops_team",
    "finance_team",
    "gtm_team",
    "agents/chief_of_staff",
]


class QueryTemplateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(
        ..., description="SQL template name", min_length=1, max_length=128
    )
    params: dict | None = Field(default=None, description="Template parameters")


class QuerySqlInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sql: str = Field(
        ...,
        description="SQL query with :param_name placeholders",
        min_length=1,
        max_length=10_000,
    )
    params: dict | None = Field(default=None, description="Bind parameters")
    context: str = Field(
        default="mcp_query",
        description="Audit context tag",
        min_length=1,
        max_length=128,
    )


class GetSchemaInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    table_name: str | None = Field(
        default=None, description="Table to inspect", min_length=1, max_length=128
    )


class SearchMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., description="Search query", min_length=1, max_length=2000)
    team: str | None = Field(default=None, min_length=1, max_length=64)
    top_k: int = Field(default=10, ge=1, le=100)
    bm25_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    temporal_half_life: int | None = Field(default=None, ge=1, le=365)


class SaveMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    content: str = Field(
        ..., description="Memory content", min_length=1, max_length=50_000
    )
    summary: str | None = Field(default=None, max_length=500)
    team: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(default=None, max_length=20)
    importance: float = Field(default=0.5)
    ttl_hours: int | None = Field(default=None, ge=1, le=8760)

    @field_validator("importance")
    @classmethod
    def clamp_importance(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class IndexSessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_summary: str = Field(..., min_length=1, max_length=50_000)
    key_learnings: list[str] | None = Field(default=None)


class QueryAuditLogInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    action: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=50)

    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, v: int) -> int:
        return max(1, min(1000, v))


class PrivacyAuditLogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=100)

    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, v: int) -> int:
        return max(1, min(500, v))


class ReadReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    team: str = Field(...)
    filename: str = Field(..., min_length=1, max_length=255)

    @field_validator("team")
    @classmethod
    def validate_team(cls, v: str) -> str:
        if v not in VALID_TEAMS:
            raise ValueError(f"Unknown team: {v!r}. Valid: {', '.join(VALID_TEAMS)}")
        return v

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("path traversal characters not allowed in filename")
        return v


class StripeSubscriptionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(default="active", max_length=32)


class StripeChargesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=25, ge=1, le=100)
    created_after: int | None = Field(default=None, ge=0)
