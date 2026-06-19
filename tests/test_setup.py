from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asset_intelligence.__init__ import async_setup_entry
from custom_components.asset_intelligence.const import DOMAIN


class FakeStore:
    def __init__(self, hass):
        self.hass = hass
        self.system_defaults = {}

    async def async_load(self):
        return None

    def get_document_storage_config(self):
        return {}

    async def set_document_storage_config(self, config):
        self.document_storage_config = config


class FakeCoordinator:
    def __init__(self, hass, store):
        self.hass = hass
        self.store = store
        self.async_config_entry_first_refresh = AsyncMock()


class FakeDocumentStorage:
    def __init__(self, hass, config):
        self.hass = hass
        self.config = config

    def is_available(self):
        return True


class FakeUnavailableDocumentStorage(FakeDocumentStorage):
    def is_available(self):
        return False


@pytest.mark.asyncio
async def test_async_setup_entry_registers_runtime_and_services():
    hass = SimpleNamespace()
    hass.data = {}
    hass.services = SimpleNamespace(
        async_register=MagicMock(),
    )
    hass.config_entries = SimpleNamespace(
        async_forward_entry_setups=AsyncMock(),
    )
    hass.bus = SimpleNamespace(async_fire=MagicMock())

    entry = SimpleNamespace(
        entry_id="entry_1",
        options={},
        add_update_listener=MagicMock(return_value=lambda: None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__.async_ensure_storage", AsyncMock()),
        patch("custom_components.asset_intelligence.__init__.AssetStore", FakeStore),
        patch("custom_components.asset_intelligence.__init__.AssetIntelligenceCoordinator", FakeCoordinator),
        patch("custom_components.asset_intelligence.__init__.DocumentStorage", FakeDocumentStorage),
        patch("custom_components.asset_intelligence.__init__._ensure_document_view_registered"),
        patch("custom_components.asset_intelligence.__init__.async_setup_panel", AsyncMock()),
        patch("custom_components.asset_intelligence.__init__.async_dispatcher_send"),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert DOMAIN in hass.data
    assert isinstance(entry.runtime_data, dict)
    assert entry.runtime_data["store"].__class__ is FakeStore
    assert entry.runtime_data["coordinator"].__class__ is FakeCoordinator
    assert hass.services.async_register.call_count >= 2
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    entry.add_update_listener.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_marks_document_storage_unavailable_without_failing():
    hass = SimpleNamespace()
    hass.data = {}
    hass.services = SimpleNamespace(async_register=MagicMock())
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock())
    hass.bus = SimpleNamespace(async_fire=MagicMock())

    entry = SimpleNamespace(
        entry_id="entry_1",
        options={},
        add_update_listener=MagicMock(return_value=lambda: None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__.async_ensure_storage", AsyncMock()),
        patch("custom_components.asset_intelligence.__init__.AssetStore", FakeStore),
        patch("custom_components.asset_intelligence.__init__.AssetIntelligenceCoordinator", FakeCoordinator),
        patch("custom_components.asset_intelligence.__init__.DocumentStorage", FakeUnavailableDocumentStorage),
        patch("custom_components.asset_intelligence.__init__._ensure_document_view_registered"),
        patch("custom_components.asset_intelligence.__init__.async_setup_panel", AsyncMock()),
        patch("custom_components.asset_intelligence.__init__.async_dispatcher_send"),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert entry.runtime_data["document_storage_available"] is False
