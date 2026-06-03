from typing import Literal
from pydantic import BaseModel
from datetime import datetime


class StartScanRequest(BaseModel):
    target_id: str
    scan_type: str  # internal|external|full


class ScanProgressLog(BaseModel):
    step:  int
    stage: str
    msg:   str
    type:  str
    ts:    int


class ScanProgress(BaseModel):
    stage:        str
    current_step: int
    total_steps:  int
    message:      str
    log_type:     str | None = None
    log:          list[ScanProgressLog] = []


class ScanResponse(BaseModel):
    id: str
    target_id: str
    scan_type: str
    status: str
    overall_score: float | None
    risk_level: str | None
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    progress: ScanProgress | None = None
    diagnostic_code: str | None = None
    diagnostic_detail: str | None = None
    created_at: datetime


class FindingResponse(BaseModel):
    id: str
    finding_type: str
    category: str
    title: str
    description: str
    affected_path: str
    evidence: str
    remediation: str
    severity: str
    cvss_score: float
    cve_id: str | None
    owasp_category: str | None
    is_false_positive: bool
