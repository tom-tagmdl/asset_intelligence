from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS = {"root_path"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return a safe diagnostics payload for a config entry."""
    runtime = entry.runtime_data if isinstance(getattr(entry, "runtime_data", None), dict) else {}
    store = runtime.get("store")
    document_storage = runtime.get("document_storage")

    store_config = {}
    if store and hasattr(store, "get_document_storage_config"):
        try:
            store_config = store.get_document_storage_config() or {}
        except Exception:
            store_config = {}

    assets = getattr(store, "assets", {}) if store else {}
    rooms = getattr(store, "rooms", {}) if store else {}

    return {
        "integration": DOMAIN,
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": dict(entry.data or {}),
            "options": dict(entry.options or {}),
        },
        "runtime": {
            "document_storage_available": runtime.get("document_storage_available"),
            "document_storage_config": async_redact_data(store_config, REDACT_KEYS),
            "asset_count": len(assets) if isinstance(assets, dict) else 0,
            "room_count": len(rooms) if isinstance(rooms, dict) else 0,
            "has_document_storage": bool(document_storage),
        },
    }
