from __future__ import annotations

import os
import logging
from aiohttp import web

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.components.frontend import async_register_built_in_panel

from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)
_PANEL_REGISTERED_FLAG = "_panel_registered"
_STATIC_REGISTERED_FLAG = "_panel_static_registered"
_VERSION_VIEW_REGISTERED_FLAG = "_panel_version_view_registered"
_SNAPSHOT_VIEW_REGISTERED_FLAG = "_panel_snapshot_view_registered"
_PANEL_BUILD_INFO_KEY = "_panel_build_info"


class AssetIntelligencePanelVersionView(HomeAssistantView):
    """Expose the active panel bundle token so stale clients can self-detect."""

    url = "/api/asset_intelligence/panel_version"
    name = "api:asset_intelligence:panel_version"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        domain_data = hass.data.setdefault(DOMAIN, {})
        build_info = domain_data.get(_PANEL_BUILD_INFO_KEY)

        if not isinstance(build_info, dict) or not build_info.get("selected_panel"):
            raise web.HTTPServiceUnavailable(text="Panel build info unavailable")

        response = web.json_response(build_info)
        response.headers["Cache-Control"] = "no-store"
        return response


class AssetIntelligenceStorageSnapshotView(HomeAssistantView):
    """Expose runtime storage snapshot for frontend bootstrap in production-safe way."""

    url = "/api/asset_intelligence/storage_snapshot"
    name = "api:asset_intelligence:storage_snapshot"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]

        rooms = {}
        system_defaults = {}

        try:
            entries = hass.config_entries.async_entries(DOMAIN)
            for entry in entries:
                runtime = getattr(entry, "runtime_data", None)
                if not isinstance(runtime, dict):
                    continue

                store = runtime.get("store")
                if store is None:
                    continue

                maybe_rooms = getattr(store, "rooms", {}) or {}
                maybe_defaults = getattr(store, "system_defaults", {}) or {}

                if isinstance(maybe_rooms, dict):
                    rooms = maybe_rooms
                if isinstance(maybe_defaults, dict):
                    system_defaults = maybe_defaults
                break
        except Exception:
            _LOGGER.exception("Asset Intelligence: failed building storage snapshot")

        response = web.json_response(
            {
                "rooms": rooms,
                "system_defaults": system_defaults,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response


def _resolve_panel_asset(frontend_dir: str, panel_candidates: list[str]) -> tuple[str, str]:
    selected_panel = next(
        (
            name
            for name in panel_candidates
            if os.path.exists(os.path.join(frontend_dir, name))
        ),
        panel_candidates[0] if panel_candidates else "panel_v5.js",
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
    panel_candidates = ["panel_v5.js"]
    selected_panel, cache_token = await hass.async_add_executor_job(
        _resolve_panel_asset,
        frontend_dir,
        panel_candidates,
    )
    domain_data[_PANEL_BUILD_INFO_KEY] = {
        "selected_panel": selected_panel,
        "cache_token": cache_token,
    }

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

    if not domain_data.get(_VERSION_VIEW_REGISTERED_FLAG):
        try:
            hass.http.register_view(AssetIntelligencePanelVersionView())
            domain_data[_VERSION_VIEW_REGISTERED_FLAG] = True
        except Exception:
            _LOGGER.exception("Asset Intelligence: failed registering panel version view")
            return

    if not domain_data.get(_SNAPSHOT_VIEW_REGISTERED_FLAG):
        try:
            hass.http.register_view(AssetIntelligenceStorageSnapshotView())
            domain_data[_SNAPSHOT_VIEW_REGISTERED_FLAG] = True
        except Exception:
            _LOGGER.exception("Asset Intelligence: failed registering panel snapshot view")
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