from app.infra.qstash import ALLOWED_JOB_KINDS


def test_job_allowlist_contains_documented_jobs() -> None:
    assert "import_feed" in ALLOWED_JOB_KINDS
    assert "reconcile_stuck_jobs" in ALLOWED_JOB_KINDS
    assert "arbitrary_code" not in ALLOWED_JOB_KINDS
