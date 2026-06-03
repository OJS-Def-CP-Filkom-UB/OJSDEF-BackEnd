import app.models.scan_job as sj
import app.models.ojs_target as ot


def test_scan_job_has_diagnostic_columns():
    cols = sj.ScanJob.__table__.columns.keys()
    assert "diagnostic_code" in cols
    assert "diagnostic_detail" in cols


def test_target_has_force_heartbeat():
    cols = ot.OJSTarget.__table__.columns.keys()
    assert "force_heartbeat" in cols
