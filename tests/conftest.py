"""Tests use a temporary SQLite database, never the development one."""

import os
import tempfile
from pathlib import Path

_tmp_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
