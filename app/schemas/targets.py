from pydantic import BaseModel
from datetime import datetime


class CreateTargetRequest(BaseModel):
    name: str
    url: str


class TargetResponse(BaseModel):
    id: str
    name: str
    url: str
    is_verified: bool
    plugin_connected: bool
    ojs_version: str | None
    created_at: datetime


class VerifyResponse(BaseModel):
    verified: bool
    method: str | None = None


class PluginGuideResponse(BaseModel):
    target_id: str
    api_key: str
    endpoint: str
    instructions: str
