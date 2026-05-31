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
    plugin_status: str           # "connected"|"disconnected"|"error"|"never_connected"
    connection_mode: str | None
    last_heartbeat: datetime | None
    verification_token: str | None
    ojs_version: str | None
    created_at: datetime


class FileMethodInfo(BaseModel):
    filename: str
    content: str
    path: str


class DnsMethodInfo(BaseModel):
    record_type: str
    record_name: str
    record_value: str


class VerifyResponse(BaseModel):
    verified: bool
    method: str | None = None
    verification_token: str | None = None
    file_method: FileMethodInfo | None = None
    dns_method: DnsMethodInfo | None = None


class PluginGuideResponse(BaseModel):
    target_id: str
    api_key: str
    endpoint: str
    instructions: str
