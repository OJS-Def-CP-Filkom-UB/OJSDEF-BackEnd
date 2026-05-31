from typing import Literal
from pydantic import BaseModel
from datetime import datetime


class StartScanRequest(BaseModel):
    target_id: str
    scan_type: str  # internal|external|full


class ScanProgress(BaseModel):
    stage: Literal["external_scan", "internal_audit", "scoring", "report_gen"]
    current_step: int
    total_steps: int
    message: str  # Bahasa Indonesia, contoh: "Memeriksa header HTTP..."


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
