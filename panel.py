from __future__ import annotations

import os
import logging

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.frontend import async_register_built_in_panel

from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)
_PANEL_REGISTERED_FLAG = "_panel_registered"
_STATIC_REGISTERED_FLAG = "_panel_static_registered"


def _resolve_panel_asset(frontend_dir: str, panel_candidates: list[str]) -> tuple[str, str]:
    selected_panel = next(
        (
            name
            for name in panel_candidates
            if os.path.exists(os.path.join(frontend_dir, name))
        ),
        "panel.js",
    )

    panel_js_path = os.path.join(frontend_dir, selected_panel)
    try:
        cache_token = str(int(os.path.getmtime(panel_js_path)))
    except (OSError, ValueError):
        cache_token = "1"

    return selected_panel, cache_token


async def async_setup_panel(hass):
    """Register the Asset Intelligence frontend panel."""

    domain_data = hass.data.setdefault(DOMAIN, {})

    frontend_dir = hass.config.path("custom_components/asset_intelligence/frontend")
    panel_candidates = ["panel_v5.js", "panel.js"]
    selected_panel, cache_token = await hass.async_add_executor_job(
        _resolve_panel_asset,
        frontend_dir,
        panel_candidates,
    )

    if not domain_data.get(_STATIC_REGISTERED_FLAG):
        try:
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        url_path="/asset-intelligence-static",
                        path=frontend_dir,
                        cache_headers=False,
                    )
                ]
            )
            domain_data[_STATIC_REGISTERED_FLAG] = True
        except Exception:
            _LOGGER.exception("Asset Intelligence: failed registering panel static path")
            return

    if domain_data.get(_PANEL_REGISTERED_FLAG):
        return

    try:
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Asset Intelligence",
            sidebar_icon="mdi:home-analytics",
            frontend_url_path="asset-intelligence",
            require_admin=False,
            config={
                "_panel_custom": {
                    "name": "asset-intelligence-app",
                    "js_url": f"/asset-intelligence-static/{selected_panel}?v={cache_token}",
                    "embed_iframe": False,
                }
            },
        )
        domain_data[_PANEL_REGISTERED_FLAG] = True
    except Exception:
        _LOGGER.exception("Asset Intelligence: failed registering frontend panel")