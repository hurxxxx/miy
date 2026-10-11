"""Private-notes business rules stay in this app; the gateway stores generic records."""

from uuid import UUID

from fastapi import Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


def install(app, settings, platform_request):
    def parameters(authorization):
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 200:
            raise HTTPException(status_code=401, detail="App session required")
        return {
            "headers": {"Authorization": authorization},
            "params": {"installation_id": settings.installation_id, "audience": settings.origin},
        }

    @app.get("/api/notes")
    async def notes(after: UUID | None = None, authorization: str | None = Header(default=None)):
        options = parameters(authorization)
        options["params"]["limit"] = 20
        if after:
            options["params"]["after"] = str(after)
        return await platform_request("GET", "/_data/notes", max_bytes=512 * 1024, **options)

    @app.post("/api/notes", status_code=201)
    async def create(data: Note, authorization: str | None = Header(default=None)):
        return await platform_request(
            "POST",
            "/_data/notes",
            success_codes=(201,),
            json={"payload": data.model_dump()},
            **parameters(authorization),
        )

    @app.delete("/api/notes/{record_id}", status_code=204)
    async def delete(
        record_id: UUID,
        expected_version: int = Query(ge=1),
        authorization: str | None = Header(default=None),
    ):
        options = parameters(authorization)
        options["params"]["expected_version"] = expected_version
        await platform_request(
            "DELETE", f"/_data/notes/{record_id}", success_codes=(204,), **options
        )
