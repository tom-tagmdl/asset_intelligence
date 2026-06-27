from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def integration_path() -> Path:
    return Path(__file__).resolve().parents[1] / "custom_components" / "asset_intelligence"
