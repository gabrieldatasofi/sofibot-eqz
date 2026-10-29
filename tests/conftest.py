import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def folders(tmp_path, monkeypatch):
    from sofibot_eqz import config

    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "reports").mkdir()
    return tmp_path
