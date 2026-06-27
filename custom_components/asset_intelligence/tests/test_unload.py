from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asset_intelligence.__init__ import DATA_SERVICES_REGISTERED, REGISTERED_SERVICES, async_setup_entry, async_unload_entry
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


@pytest.mark.asyncio
async def test_async_unload_entry_removes_services_for_last_runtime():
    hass = SimpleNamespace()
    hass.data = {DOMAIN: {DATA_SERVICES_REGISTERED: True}}
    hass.services = SimpleNamespace(
        has_service=MagicMock(return_value=True),
        async_remove=MagicMock(),
    )
    hass.config_entries = SimpleNamespace(
        async_entries=MagicMock(return_value=[]),
        async_unload_platforms=AsyncMock(return_value=True),
    )

    entry = SimpleNamespace(entry_id="entry_1")

    with patch("custom_components.asset_intelligence.__init__._iter_runtimes", return_value=[]):
        result = await async_unload_entry(hass, entry)

    assert result is True
    assert DATA_SERVICES_REGISTERED not in hass.data[DOMAIN]
    assert hass.services.async_remove.call_count == len(REGISTERED_SERVICES)


@pytest.mark.asyncio
async def test_async_setup_reload_cycle_recovers_after_unload():
    hass = SimpleNamespace()
    hass.data = {}
    hass.services = SimpleNamespace(has_service=MagicMock(return_value=True), async_remove=MagicMock(), async_register=MagicMock())
    hass.bus = SimpleNamespace(async_fire=MagicMock())

    entry = SimpleNamespace(entry_id="entry_1", options={}, add_update_listener=MagicMock(return_value=lambda: None))
    hass.config_entries = SimpleNamespace(
        async_entries=MagicMock(return_value=[entry]),
        async_forward_entry_setups=AsyncMock(return_value=None),
        async_unload_platforms=AsyncMock(return_value=True),
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
        setup_result = await async_setup_entry(hass, entry)
        unload_result = await async_unload_entry(hass, entry)
        reload_result = await async_setup_entry(hass, entry)

    assert setup_result is True
    assert unload_result is True
    assert reload_result is True
    assert isinstance(entry.runtime_data, dict)
