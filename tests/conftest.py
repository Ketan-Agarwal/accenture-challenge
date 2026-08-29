from pathlib import Path

import pytest

from app.audit import AuditRepository
from app.pipeline import ControlPlane


@pytest.fixture()
def control_plane(tmp_path: Path) -> ControlPlane:
    return ControlPlane(audit=AuditRepository(tmp_path / "test.db"))

