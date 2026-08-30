from app.audit import AuditRepository


def test_audit_repository_uses_configured_database_path(tmp_path, monkeypatch):
    configured = tmp_path / "nested" / "container-audit.db"
    monkeypatch.setenv("CONTROLPLANE_DB_PATH", str(configured))

    repository = AuditRepository()

    assert repository.path == configured
    assert configured.exists()
