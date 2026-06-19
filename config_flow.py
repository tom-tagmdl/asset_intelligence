from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback

import os
import voluptuous as vol

from homeassistant.helpers import selector

from .const import DOMAIN
from .storage import AssetStore, async_ensure_storage


SettingsDict = dict[str, object]


def _normalize_storage_path(path: str | None) -> str:
    """Normalize user-entered storage path to HA-friendly absolute form."""
    if not isinstance(path, str):
        return ""

    normalized: str = os.path.expanduser(path.strip()).replace("\\", "/")
    if not normalized:
        return ""

    relative_ha_prefixes = ("media/", "share/", "config/")
    if any(normalized.startswith(prefix) for prefix in relative_ha_prefixes):
        normalized = f"/{normalized.lstrip('/')}"

    return normalized


def _has_storage_path(path: str | None) -> bool:
    """Return True when the normalized storage path is present."""
    normalized: str = _normalize_storage_path(path)
    return bool(normalized)


def _normalize_settings_input(user_input: SettingsDict) -> tuple[SettingsDict, dict[str, str]]:
    """Normalize and validate shared settings input."""
    normalized_input: SettingsDict = dict(user_input)
    errors: dict[str, str] = {}

    path: str = _normalize_storage_path(str(normalized_input.get("document_storage_path", "") or ""))
    wants_enabled = bool(normalized_input.get("documents_enabled", False))
    normalized_input["document_storage_path"] = path

    if not path:
        normalized_input["documents_enabled"] = False
    elif wants_enabled:
        if not os.path.isdir(path):
            errors["document_storage_path"] = "path_not_found"
            normalized_input["documents_enabled"] = False
        else:
            normalized_input["documents_enabled"] = True
    else:
        normalized_input["documents_enabled"] = False

    return normalized_input, errors


def _build_settings_schema(
    options: SettingsDict,
    user_input: SettingsDict | None = None,
):
    """Build the shared settings schema for options and reconfigure."""
    source = user_input if user_input is not None else options

    current_path: str = _normalize_storage_path(str(source.get("document_storage_path", "") or ""))
    current_enabled = bool(source.get("documents_enabled", False))

    return vol.Schema(
        {
            vol.Optional(
                "default_label_ids",
                default=options.get("default_label_ids", []),
                description="Default labels for new assets",
            ): selector.selector({"label": {"multiple": True}}),
            vol.Optional(
                "document_storage_path",
                description={
                    "suggested_value": current_path,
                    "label": "Document storage location (/media/... or /share/...)",
                },
            ): selector.selector({"text": {"type": "text"}}),
            vol.Optional(
                "documents_enabled",
                default=current_enabled,
                description="Enable document management",
            ): selector.selector({"boolean": {}}),
        }
    )


class AssetIntelligenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Asset Intelligence."""

    VERSION = 1

    async def async_step_user(self, user_input: SettingsDict | None = None):
        """Initial setup step (kept intentionally minimal)."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            try:
                await self._async_validate_setup()
            except Exception:
                return self.async_show_form(
                    step_id="user",
                    errors={"base": "cannot_connect"},
                )

            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Asset Intelligence",
                data={},
            )

        return self.async_show_form(step_id="user")

    async def async_step_reconfigure(self, user_input: SettingsDict | None = None):
        """Handle reconfiguration of the existing entry."""
        reconfigure_entry = self._get_reconfigure_entry()
        options = reconfigure_entry.options or {}

        if user_input is not None:
            normalized_input, errors = _normalize_settings_input(user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    options_updates=normalized_input,
                )

            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_build_settings_schema(options, normalized_input),
                errors=errors,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_settings_schema(options),
        )

    async def _async_validate_setup(self) -> None:
        """Validate that the integration can initialize before entry creation."""
        if callable(async_ensure_storage):
            await async_ensure_storage(self.hass, {})

        AssetStore(self.hass)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> AssetIntelligenceOptionsFlow:
        """Return options flow handler."""
        return AssetIntelligenceOptionsFlow(config_entry)


# -----------------------------------------------------------
# OPTIONS FLOW
# -----------------------------------------------------------

class AssetIntelligenceOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Asset Intelligence."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow with config entry."""
        try:
            super().__init__(config_entry)
        except TypeError:
            super().__init__()
        self._config_entry: config_entries.ConfigEntry = config_entry

    async def async_step_init(self, user_input: SettingsDict | None = None):
        """Manage the options."""

        config_entry: config_entries.ConfigEntry | None = getattr(self, "_config_entry", None)
        options = (config_entry.options or {}) if config_entry else {}

        errors: dict[str, str] = {}

        if user_input is not None:
            normalized_input, errors = _normalize_settings_input(user_input)
            if not errors:
                return self.async_create_entry(title="", data=normalized_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_settings_schema(options, user_input),
            errors=errors,
        )