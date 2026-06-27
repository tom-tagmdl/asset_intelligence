from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SIGNAL_ASSETS_UPDATED, SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED


# -----------------------------------------------------------
# HELPERS
# -----------------------------------------------------------


def _default_unassigned_projection(
    asset_id: str,
    area_id: str | None = None,
) -> Dict[str, Any]:
    """Fallback projection when coordinator data is not yet available."""
    return {
        "asset_id": asset_id,
        "room_area_id": area_id,
        "risk_state": "AMBER",
        "candidate_state": "AMBER",
        "reasons": ["Asset is not assigned to a room"] if not area_id else [],
        "pending_red_since": None,
        "debounce_action": None,
        "environment_state_since": None,
        "last_event": None,
        "advisories": [],
        "primary_advisory": None,
        "exposure_risk": "NONE",
        "spatial_context": {},
    }


def _normalize_reasons(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value is None:
        return []
    return [str(value)]


# -----------------------------------------------------------
# PLATFORM SETUP
# -----------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: Any | None = getattr(entry, "runtime_data", None)
    if not isinstance(runtime, dict):
        raise RuntimeError("Asset Intelligence runtime is not available")
    store = runtime["store"]
    coordinator = runtime["coordinator"]

    entities: dict[str, AssetAtRiskBinarySensor] = {}
    known_ids: set[str] = set()

    # Add document storage availability sensor
    storage_sensor: DocumentStorageAvailableSensor = DocumentStorageAvailableSensor(coordinator)

    for asset_id, asset in store.assets.items():
        entities[asset_id] = AssetAtRiskBinarySensor(
            coordinator,
            store,
            asset_id,
            asset,
        )
        known_ids.add(asset_id)

    async_add_entities([storage_sensor] + list(entities.values()), update_before_add=False)

    async def _handle_assets_updated(initial: bool = False) -> None:
        current_ids = set(store.assets.keys())

        # -------------------------------------------------------
        # Add new entities
        # -------------------------------------------------------
        new_ids = current_ids - known_ids
        if new_ids:
            new_entities: List[AssetAtRiskBinarySensor] = []
            for asset_id in new_ids:
                ent = AssetAtRiskBinarySensor(
                    coordinator,
                    store,
                    asset_id,
                    store.assets[asset_id],
                )
                entities[asset_id] = ent
                new_entities.append(ent)

            async_add_entities(new_entities, update_before_add=False)

        # -------------------------------------------------------
        # Update existing entities
        # -------------------------------------------------------
        for asset_id in current_ids & known_ids:
            ent: AssetAtRiskBinarySensor = entities[asset_id]
            ent.update_from_store(store.assets[asset_id])
            ent.async_write_ha_state()

        # -------------------------------------------------------
        # Remove deleted entities
        # IMPORTANT:
        # Skip this during initial startup so restored entities
        # are not incorrectly removed before the integration is
        # fully authoritative.
        # -------------------------------------------------------
        if not initial:
            removed_ids: set[str] = known_ids - current_ids
            for asset_id in removed_ids:
                ent = entities.pop(asset_id)
                await ent.async_remove()

        known_ids.clear()
        known_ids.update(current_ids)

    unsub = async_dispatcher_connect(
        hass,
        SIGNAL_ASSETS_UPDATED,
        _handle_assets_updated,
    )
    entry.async_on_unload(unsub)

    # -----------------------------------------------------------
    # Force one initial update after startup
    # -----------------------------------------------------------
    await _handle_assets_updated(initial=True)


# -----------------------------------------------------------
# BINARY SENSOR
# -----------------------------------------------------------

class AssetAtRiskBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor projection for whether an asset is currently RED risk."""

    _attr_has_entity_name = True
    _attr_translation_key: str = "asset_at_risk"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_icon: str = "mdi:shield-alert-outline"

    def __init__(self, coordinator, store, asset_id: str, asset: Dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._store = store
        self._asset_id: str = asset_id
        self._asset: Dict[str, Any] = dict(asset)

        self._attr_unique_id: str = f"{DOMAIN}_{asset_id}_at_risk"
        self._attr_name: str = f"{asset.get('name', asset_id)} At Risk"

    def update_from_store(self, asset: Dict[str, Any]) -> None:
        """Refresh local cached asset metadata from store."""
        self._asset: Dict[str, Any] = dict(asset)
        self._attr_name: str = f"{asset.get('name', self._asset_id)} At Risk"

    @property
    def asset(self) -> Dict[str, Any]:
        """Return latest asset record from store if available."""
        stored_asset = self._store.get(self._asset_id)
        if isinstance(stored_asset, dict):
            return stored_asset
        return self._asset

    @property
    def projection(self) -> Dict[str, Any]:
        """Return latest coordinator projection for this asset."""
        data = self.coordinator.data or {}
        projection = data.get(self._asset_id)
        if isinstance(projection, dict):
            return projection
        return _default_unassigned_projection(self._asset_id, None)

    @property
    def device_info(self):
        """Attach this binary sensor to the same device as the asset sensor."""
        asset: Dict[str, Any] = self.asset
        asset_id: Any | str = asset.get("asset_id") or self._asset_id
        asset_name: Any | str = asset.get("name") or asset_id
        asset_type: Any | str = asset.get("asset_type") or "Asset"

        return {
            "identifiers": {(DOMAIN, asset_id)},
            "name": asset_name,
            "manufacturer": "Asset Intelligence",
            "model": str(asset_type),
        }

    @property
    def is_on(self) -> bool:
        """Final binary state only: on when risk_state is RED."""
        return self.projection.get("risk_state") == "RED"

    @property
    def extra_state_attributes(self):
        """Expose lightweight explainability attributes only."""
        projection: Dict[str, Any] = self.projection or {}
        asset: Dict[str, Any] = self.asset or {}

        reasons: List[str] = _normalize_reasons(projection.get("reasons"))

        last_event: Any | None = projection.get("last_event")
        if not isinstance(last_event, dict):
            stored_last_event: Any | None = asset.get("last_environment_event")
            last_event = (
                stored_last_event if isinstance(stored_last_event, dict) else None
            )

        return {
            "asset_id": asset.get("asset_id"),
            "area_id": projection.get("room_area_id"),
            "risk_state": projection.get("risk_state"),
            "candidate_risk_state": projection.get("candidate_state"),
            "reasons": reasons,
            "debounce_action": projection.get("debounce_action"),
            "pending_red_since": projection.get("pending_red_since"),
            "environment_state_since": (
                projection.get("environment_state_since")
                or asset.get("environment_state_since")
            ),
            "environment_event_count": asset.get("environment_event_count", 0),
            "last_environment_event": last_event,
            "exposure_risk": projection.get("exposure_risk"),
            "spatial_context": projection.get("spatial_context", {}),
            "primary_advisory": projection.get("primary_advisory"),
            "advisories": projection.get("advisories", []),
        }


class DocumentStorageAvailableSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor reflecting whether document storage is available."""

    _attr_has_entity_name = True
    _attr_translation_key: str = "document_storage_available"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_device_class = None
    _attr_icon: str = "mdi:database"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id: str = f"{DOMAIN}_document_storage_available"
        self._attr_name = "Asset Intelligence Document Storage Available"
        self._unsub_dispatcher = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass,
            SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED,
            self._handle_availability_changed,
        )
        self.async_on_remove(self._unsub_dispatcher)

    def _handle_availability_changed(self, available: bool) -> None:
        # availability changed; update HA state
        try:
            self.async_write_ha_state()
        except Exception:
            pass

    def _get_runtime(self) -> dict[str, Any] | None:
        """Resolve this sensor's runtime from config entries."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            runtime = getattr(entry, "runtime_data", None)
            if (
                isinstance(runtime, dict)
                and runtime.get("coordinator") is self.coordinator
            ):
                return runtime
        return None

    @property
    def is_on(self) -> bool:
        # Re-probe availability on every state read so NAS/network mounts that
        # settle after startup are picked up without requiring a restart.
        runtime = self._get_runtime()
        if isinstance(runtime, dict):
            ds = runtime.get("document_storage")
            if ds is None:
                return False
            try:
                available = bool(ds.is_available())
            except Exception:
                available = False
            # Keep cached value in sync so other consumers stay consistent.
            runtime["document_storage_available"] = available
            return available
        return False

    @property
    def extra_state_attributes(self):
        runtime = self._get_runtime()
        if isinstance(runtime, dict):
            ds = runtime.get("document_storage")
            if ds:
                return {
                    "provider": getattr(ds, "provider", None),
                    "documents_enabled": getattr(ds, "documents_enabled", False),
                    "requires_network_storage": getattr(ds, "requires_network_storage", True),
                    "available": bool(runtime.get("document_storage_available", False)),
                }
        return {"available": False}

