from pydantic import BaseModel
from datetime import datetime


class ReportResponse(BaseModel):
    id: str
    job_id: str
    format: str
    file_size_bytes: int | None
    created_at: datetime
