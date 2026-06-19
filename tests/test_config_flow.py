from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asset_intelligence.config_flow import (
    AssetIntelligenceConfigFlow,
    _has_storage_path,
    _normalize_storage_path,
)
from custom_components.asset_intelligence.const import DOMAIN


def test_normalize_storage_path_relative_path():
    assert _normalize_storage_path("share/asset-docs") == "/share/asset-docs"


def test_normalize_storage_path_trims_and_expands():
    assert _normalize_storage_path("  /config/asset-intelligence  ") == "/config/asset-intelligence"


def test_has_storage_path():
    assert _has_storage_path("/share/assets") is True
    assert _has_storage_path("") is False


@pytest.mark.asyncio
async def test_async_step_user_creates_entry_after_validation():
    flow = AssetIntelligenceConfigFlow()
    flow.hass = SimpleNamespace()
    flow._async_current_entries = MagicMock(return_value=[])
    flow._async_validate_setup = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()

    result = await flow.async_step_user({"confirm": True})

    assert result["type"] == "create_entry"
    assert result["title"] == "Asset Intelligence"
    assert result["data"] == {}
    flow._async_validate_setup.assert_awaited_once()
    flow.async_set_unique_id.assert_awaited_once_with(DOMAIN)


@pytest.mark.asyncio
async def test_async_step_user_aborts_when_single_entry_exists():
    flow = AssetIntelligenceConfigFlow()
    flow.hass = SimpleNamespace()
    flow._async_current_entries = MagicMock(return_value=[object()])

    result = await flow.async_step_user()

    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.asyncio
async def test_async_step_user_returns_form_when_validation_fails():
    flow = AssetIntelligenceConfigFlow()
    flow.hass = SimpleNamespace()
    flow._async_current_entries = MagicMock(return_value=[])
    flow._async_validate_setup = AsyncMock(side_effect=Exception("boom"))
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()

    result = await flow.async_step_user({"confirm": True})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    flow.async_set_unique_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_step_reconfigure_updates_existing_entry(tmp_path):
    storage_path = tmp_path / "documents"
    storage_path.mkdir()

    flow = AssetIntelligenceConfigFlow()
    flow.hass = SimpleNamespace()
    flow._get_reconfigure_entry = MagicMock(
        return_value=SimpleNamespace(
            options={"default_label_ids": []},
            title="Asset Intelligence",
        )
    )
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )

    result = await flow.async_step_reconfigure(
        {
            "default_label_ids": [],
            "document_storage_path": str(storage_path),
            "documents_enabled": True,
        }
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    flow.async_set_unique_id.assert_awaited_once()
    flow._abort_if_unique_id_mismatch.assert_called_once()
    flow.async_update_reload_and_abort.assert_called_once()
