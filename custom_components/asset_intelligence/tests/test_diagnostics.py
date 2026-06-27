from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.asset_intelligence.diagnostics import async_get_config_entry_diagnostics


class FakeStore:
    def __init__(self):
        self.assets = {"asset_1": {}, "asset_2": {}}
        self.rooms = {"room_1": {}}

    def get_document_storage_config(self):
        return {"root_path": "/config/asset-intelligence", "documents_enabled": True}


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_redacts_storage_path():
    entry = SimpleNamespace(
        title="Asset Intelligence",
        version=1,
        minor_version=0,
        data={},
        options={"documents_enabled": True},
        runtime_data={
            "store": FakeStore(),
            "document_storage": object(),
            "document_storage_available": True,
        },
    )

    result = await async_get_config_entry_diagnostics(SimpleNamespace(), entry)

    assert result["integration"] == "asset_intelligence"
    assert result["runtime"]["asset_count"] == 2
    assert result["runtime"]["room_count"] == 1
    assert result["runtime"]["document_storage_available"] is True
    assert result["runtime"]["document_storage_config"]["root_path"] == "**REDACTED**"
