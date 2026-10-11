"""Owner-scoped equipment routes using the fixed platform record gateway."""
from typing import Literal
from uuid import UUID
from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

class Equipment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    number: str = Field(min_length=1, max_length=64)
    user: str = Field(default="", max_length=100)
    location: str = Field(min_length=1, max_length=100)
    status: Literal["in_use", "stored"]

    @field_validator("number", mode="before")
    @classmethod
    def normalize_number(cls, value):
        if not isinstance(value, str):
            raise ValueError("Invalid equipment number")
        value = value.strip().upper()
        if len(value.encode("utf-8")) > 256 or any(not c.isprintable() for c in value):
            raise ValueError("Invalid equipment number")
        return value

    @model_validator(mode="after")
    def check_user(self):
        if self.status == "stored":
            self.user = ""
        elif not self.user:
            raise ValueError("User is required for equipment in use")
        return self

class EquipmentUpdate(Equipment):
    expected_version: int = Field(ge=1, strict=True)

def install(app, settings, platform_request):
    async def call(method, path, authorization, **kwargs):
        if not authorization or not authorization.startswith("Bearer ") or not 8 <= len(authorization) <= 200:
            raise HTTPException(401, "App session required")
        context = {"installation_id": settings.installation_id, "audience": settings.origin}
        headers = {"Authorization": authorization}
        await platform_request("GET", "/session", headers=headers, params=context)
        params = {**context, **kwargs.pop("params", {})}
        return await platform_request(method, path, headers=headers, params=params, **kwargs)

    @app.get("/api/equipment")
    async def listing(after: UUID | None = None, authorization: str | None = Header(default=None)):
        return await call("GET", "/_data/equipment", authorization,
                          params={"limit": 50, **({"after": str(after)} if after else {})}, max_bytes=1024*1024)

    @app.get("/api/equipment/by-number")
    async def by_number(number: str, authorization: str | None = Header(default=None)):
        try:
            validated = Equipment(name="lookup", number=number, location="lookup", status="stored")
        except ValidationError:
            raise HTTPException(422, "Invalid equipment number") from None
        return await call("GET", "/_data/equipment/by-key", authorization, params={"record_key": validated.number})

    @app.get("/api/equipment/{record_id}")
    async def detail(record_id: UUID, authorization: str | None = Header(default=None)):
        return await call("GET", f"/_data/equipment/{record_id}", authorization)

    @app.post("/api/equipment", status_code=201)
    async def create(data: Equipment, authorization: str | None = Header(default=None)):
        return await call("POST", "/_data/equipment", authorization, success_codes=(201,),
                          json={"payload": data.model_dump(), "record_key": data.number})

    @app.put("/api/equipment/{record_id}")
    async def update(record_id: UUID, data: EquipmentUpdate, authorization: str | None = Header(default=None)):
        current = await call("GET", f"/_data/equipment/{record_id}", authorization)
        if current["payload"]["number"] != data.number:
            raise HTTPException(422, "Equipment number cannot change")
        return await call("PUT", f"/_data/equipment/{record_id}", authorization,
                          json={"payload": data.model_dump(exclude={"expected_version"}),
                                "expected_version": data.expected_version})
