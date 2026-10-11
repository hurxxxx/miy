from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AliasArgs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_at: str | None = Field(default=None, alias="from")
    q: str = ""
    limit: int | None = None


class CountArgs(BaseModel):
    count: int = Field(..., ge=1)
