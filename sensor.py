from __future__ import annotations
from datetime import datetime
import json
from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, SIGNAL_ASSETS_UPDATED



UID_COUNT = "asset_intelligence_count"
UID_ASSETS = "asset_intelligence_assets"

# -----------------------------------------------------------
# HELPERS
# -----------------------------------------------------------
def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts

def _audit_summary(audit_log: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for entry in reversed(audit_log[-10:]):
        ts: str = _fmt_ts(entry.get("timestamp"))
        actor = entry.get("actor", "unknown")
        action = entry.get("action", "")
        details = entry.get("details", {}) or {}
        filename = (
            details.get("file_name")
            or details.get("document_id")
            or ""
        )
        if filename:
            out.append(f"{ts} — {actor} → {action} ({filename})")
        else:
            out.append(f"{ts} — {actor} → {action}")
    return out

def _last_action(audit_log: List[Dict[str, Any]]) -> str | None:
    if not audit_log:
        return None
    last: Dict[str, Any] = audit_log[-1]
    ts: str = _fmt_ts(last.get("timestamp"))
    actor = last.get("actor", "unknown")
    action = last.get("action", "")
    details: Any | None = last.get("details")
    if not isinstance(details, dict):
        details = {}
    filename = (
        details.get("file_name")
        or details.get("document_id")
        or ""
    )

    if filename:
        return f"{action} ({filename}) by {actor} at {ts}"
    return f"{action} by {actor} at {ts}"

def _friendly_area_name(area_id: str) -> str:
    return area_id.replace("_", " ").replace("-", " ").title()

def _resolve_area_name(hass: HomeAssistant, area_id: str | None) -> str | None:
    if not area_id:
        return None
    area_registry = ar.async_get(hass)
    area = area_registry.async_get_area(area_id)
    return area.name if area else None

def _normalize_advisories(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    advisories: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            advisories.append(item)
    return advisories

def _normalize_primary_advisory(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None

def _compact_dict_entries(value: Any, max_items: int = 40) -> Any:
    if not isinstance(value, dict):
        return value

    compact: Dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= max_items:
            compact["_truncated"] = True
            compact["_remaining_count"] = len(value) - max_items
            break
        compact[key] = item
    return compact

def _compact_audit_details(details: Any) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {}

    # These can be very large and are not needed for timeline detail rendering.
    skip_keys: set[str] = {
        "environment_requirements",
        "room_environment",
        "documents",
        "physical_documents",
    }

    compact: Dict[str, Any] = {}
    for key, value in details.items():
        if key in skip_keys:
            continue

        # Preserve field_changes structure as-is for proper rendering
        if key == "field_changes" and isinstance(value, dict):
            compact[key] = value
            continue

        if isinstance(value, str) and len(value) > 500:
            compact[key] = f"{value[:497]}..."
            continue

        if isinstance(value, list) and len(value) > 30:
            compact[key] = value[:30]
            compact[f"{key}_truncated"] = True
            continue

        if isinstance(value, dict):
            compact[key] = _compact_dict_entries(value)
            continue

        compact[key] = value

    return compact

def _compact_audit_log(audit_log: Any, max_entries: int = 20) -> List[Dict[str, Any]]:
    if not isinstance(audit_log, list):
        return []

    compact_entries: List[Dict[str, Any]] = []
    for entry in audit_log[-max_entries:]:
        if not isinstance(entry, dict):
            continue
        compact_entries.append(
            {
                "timestamp": entry.get("timestamp"),
                "action": entry.get("action"),
                "actor": entry.get("actor"),
                "details": _compact_audit_details(entry.get("details")),
            }
        )

    return compact_entries


def _compact_event_entry(entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        return {}

    skip_keys: set[str] = {
        "environment_requirements",
        "documents",
        "physical_documents",
    }

    compact: Dict[str, Any] = {}
    for key, value in entry.items():
        if key in skip_keys:
            continue

        if isinstance(value, str) and len(value) > 500:
            compact[key] = f"{value[:497]}..."
            continue

        if isinstance(value, list) and len(value) > 30:
            compact[key] = value[:30]
            compact[f"{key}_truncated"] = True
            continue

        if isinstance(value, dict):
            compact[key] = _compact_dict_entries(value)
            continue

        compact[key] = value

    return compact


def _compact_event_log(event_log: Any, max_entries: int = 30) -> List[Dict[str, Any]]:
    if not isinstance(event_log, list):
        return []

    compact_entries: List[Dict[str, Any]] = []
    for entry in event_log[-max_entries:]:
        compact_entry: Dict[str, Any] = _compact_event_entry(entry)
        if compact_entry:
            compact_entries.append(compact_entry)

    return compact_entries


def _to_epoch_ms(value: Any) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except Exception:
        return 0


def _project_document_for_state(doc: Any) -> Dict[str, Any] | None:
    if not isinstance(doc, dict):
        return None

    metadata_obj = doc.get("metadata")
    metadata: Dict[str, Any] = metadata_obj if isinstance(metadata_obj, dict) else {}
    projected_metadata = {
        "date": metadata.get("date"),
        "physical_exists": metadata.get("physical_exists"),
        "physical_location": metadata.get("physical_location"),
        "physical_notes": metadata.get("physical_notes"),
        "physical_recorded_at": metadata.get("physical_recorded_at"),
        "physical_recorded_by": metadata.get("physical_recorded_by"),
        "physical_only": metadata.get("physical_only"),
    }

    return {
        "document_id": doc.get("document_id"),
        "type": doc.get("type"),
        "title": doc.get("title"),
        "filename": doc.get("filename"),
        "provider": doc.get("provider"),
        "provider_document_id": doc.get("provider_document_id"),
        "mime_type": doc.get("mime_type"),
        "size_bytes": doc.get("size_bytes"),
        "tags": doc.get("tags", []),
        "date": doc.get("date") or metadata.get("date"),
        "metadata": projected_metadata,
    }


def _estimate_attr_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return 0


def _truncate_string(value: Any, limit: int = 220) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    return f"{value[:limit - 3]}..."


def _compact_document_projection(doc: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        "document_id": doc.get("document_id"),
        "type": doc.get("type"),
        "title": _truncate_string(doc.get("title"), 140),
        "date": doc.get("date"),
        "filename": _truncate_string(doc.get("filename"), 120),
        "provider": doc.get("provider"),
        "provider_document_id": _truncate_string(doc.get("provider_document_id"), 260),
        "mime_type": doc.get("mime_type"),
        "size_bytes": doc.get("size_bytes"),
        "tags": (doc.get("tags") or [])[:10],
    }
    metadata: Any | None = doc.get("metadata")
    if isinstance(metadata, dict):
        compact["metadata"] = {
            "date": metadata.get("date"),
            "physical_exists": metadata.get("physical_exists"),
            "physical_location": metadata.get("physical_location"),
            "physical_notes": _truncate_string(metadata.get("physical_notes"), 180),
            "physical_recorded_at": metadata.get("physical_recorded_at"),
            "physical_recorded_by": metadata.get("physical_recorded_by"),
            "physical_only": metadata.get("physical_only"),
        }
    return compact


def _compact_sensor_attributes_for_recorder(attrs: Dict[str, Any], max_bytes: int = 15000) -> Dict[str, Any]:
    if not isinstance(attrs, dict):
        return attrs

    if _estimate_attr_size(attrs) <= max_bytes:
        return attrs

    reduced: Dict[str, Any] = dict(attrs)

    reduced["audit_log"] = _compact_audit_log(reduced.get("audit_log"), max_entries=8)

    env_events: Any | None = reduced.get("environment_events")
    if isinstance(env_events, list) and len(env_events) > 8:
        reduced["environment_events"] = env_events[-8:]

    custody_events: Any | None = reduced.get("custody_events")
    if isinstance(custody_events, list) and len(custody_events) > 8:
        reduced["custody_events"] = custody_events[-8:]

    docs: Any | None = reduced.get("documents")
    if isinstance(docs, list):
        compact_docs: List[Dict[str, Any]] = [_compact_document_projection(d) for d in docs if isinstance(d, dict)]
        if len(compact_docs) > 12:
            reduced["documents"] = compact_docs[:12]
            reduced["documents_truncated"] = True
            reduced["documents_total"] = len(compact_docs)
        else:
            reduced["documents"] = compact_docs

    summary: Any | None = reduced.get("audit_summary")
    if isinstance(summary, list) and len(summary) > 8:
        reduced["audit_summary"] = summary[:8]

    if _estimate_attr_size(reduced) <= max_bytes:
        return reduced

    for key in [
        "advisories",
        "spatial_context",
        "descriptions",
        "type_metadata",
        "environment_requirements",
        "room_environment",
        "last_environment_event",
        "physical_document_locations",
    ]:
        if key in reduced:
            reduced.pop(key, None)
            reduced[f"{key}_truncated"] = True
        if _estimate_attr_size(reduced) <= max_bytes:
            break

    return reduced

# -----------------------------------------------------------
# DEFAULT STRUCTURES
# -----------------------------------------------------------
def _default_room_environment(area_id: str | None = None) -> Dict[str, Any]:
    return {
        "area_id": area_id,
        "configured": False,
        "climate": {
            "temperature": None,
            "humidity": None,
            "dew_point": None,
        },
        "light": {
            "lux": None,
            "uv": None,
        },
        "air_quality": {
            "voc": None,
            "formaldehyde": None,
            "ozone": None,
            "no2": None,
        },
        "particulates": {
            "pm2_5": None,
            "pm10": None,
        },
        "biological": {
            "mold_index": None,
        },
        "safety": {
            "leak": None,
        },
        "structural": {
            "pressure": None,
            "vibration": None,
        },
        "context": {
            "noise": None,
        },
        "control_context": {
            "co2": None,
        },
        "external_environment": {
            "sun": None,
            "uv_index": None,
            "forecast": None,
        },
        "windows": [],
        "confidence": "STALE",
        "last_updated": None,
        "source_status": {
            "configured_signals": 0,
            "signals_with_data": 0,
            "signals_missing": 0,
            "details": {},
        },
    }

def _default_unassigned_projection(asset_id: str, area_id: str | None = None) -> Dict[str, Any]:
    return {
        "asset_id": asset_id,
        "room_area_id": area_id,
        "room_environment": _default_room_environment(area_id),
        "risk_state": "AMBER",
        "candidate_state": "AMBER",
        "reasons": ["Asset is not assigned to a room"],
        "pending_red_since": None,
        "debounce_action": None,
        "environment_state_since": None,
        "last_event": None,
        "advisories": [],
        "primary_advisory": None,
        "exposure_risk": "NONE",
        "spatial_context": {},
    }

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
    count_sensor: AssetCountSensor = AssetCountSensor(store)
    assets_sensor: AssetListSensor = AssetListSensor(store)
    asset_entities_by_id: dict[str, AssetRecordEntity] = {}
    known_asset_ids: set[str] = set()
    room_entities_by_area: dict[str, RoomEnvironmentEntity] = {}
    known_room_ids: set[str] = set()
    for asset_id, asset in store.assets.items():
        asset_entities_by_id[asset_id] = AssetRecordEntity(coordinator, store, asset_id, asset)
        known_asset_ids.add(asset_id)
    for area_id in getattr(store, "rooms", {}).keys():
        room_ent = RoomEnvironmentEntity(coordinator, store, area_id)
        room_entities_by_area[area_id] = room_ent
        known_room_ids.add(area_id)
    async_add_entities(
        [
            count_sensor,
            assets_sensor,
            *asset_entities_by_id.values(),
            *room_entities_by_area.values(),
        ],
        update_before_add=False,
    )
    async def _handle_assets_updated(initial: bool = False) -> None:
        count_sensor.async_write_ha_state()
        assets_sensor.async_write_ha_state()
        current_asset_ids = set(store.assets.keys())
        # -----------------------------
        # ASSET / RISK SENSOR ENTITIES
        # -----------------------------
        new_asset_ids = current_asset_ids - known_asset_ids
        if new_asset_ids:
            new_entities: List[SensorEntity] = []
            for asset_id in new_asset_ids:
                asset = store.assets[asset_id]
                asset_ent = AssetRecordEntity(coordinator, store, asset_id, asset)
                asset_entities_by_id[asset_id] = asset_ent
                new_entities.append(asset_ent)
            async_add_entities(new_entities, update_before_add=False)
        for asset_id in current_asset_ids & known_asset_ids:
            asset = store.assets[asset_id]
            asset_ent: AssetRecordEntity = asset_entities_by_id[asset_id]
            asset_ent.update_from_store(asset)
            asset_ent.async_write_ha_state()
        if not initial:
            removed_asset_ids: set[str] = known_asset_ids - current_asset_ids
            for asset_id in removed_asset_ids:
                ent = asset_entities_by_id.pop(asset_id)
                await ent.async_remove()
        known_asset_ids.clear()
        known_asset_ids.update(current_asset_ids)
        # -----------------------------
        # ROOM ENVIRONMENT ENTITIES
        # -----------------------------
        current_room_ids: set[Any] = set(getattr(store, "rooms", {}).keys())
        new_room_ids: set[Any] = current_room_ids - known_room_ids
        if new_room_ids:
            new_room_entities: List[RoomEnvironmentEntity] = []
            for area_id in new_room_ids:
                ent = RoomEnvironmentEntity(coordinator, store, area_id)
                room_entities_by_area[area_id] = ent
                new_room_entities.append(ent)
            async_add_entities(new_room_entities, update_before_add=False)
        for area_id in current_room_ids & known_room_ids:
            ent = room_entities_by_area[area_id]
            ent.async_write_ha_state()
        removed_rooms: set[str] = known_room_ids - current_room_ids
        for area_id in removed_rooms:
            ent = room_entities_by_area.pop(area_id)
            await ent.async_remove()
        known_room_ids.clear()
        known_room_ids.update(current_room_ids)
    unsub = async_dispatcher_connect(
        hass,
        SIGNAL_ASSETS_UPDATED,
        _handle_assets_updated,
    )
    entry.async_on_unload(unsub)
    # -----------------------------------------------------------
    # ✅ Force one initial live write so restored entities do not
    # remain unavailable after restart.
    # -----------------------------------------------------------
    await _handle_assets_updated(initial=True)


# -----------------------------------------------------------
# SUMMARY SENSORS
# -----------------------------------------------------------
class AssetCountSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key: str = "asset_count"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unique_id: str = UID_COUNT
    _attr_should_poll = False
    _attr_icon: str = "mdi:counter"
    def __init__(self, store) -> None:
        self._store: Any = store
    @property
    def native_value(self) -> int:
        return len(self._store.assets)

class AssetListSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key: str = "asset_list"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unique_id: str = UID_ASSETS
    _attr_should_poll = False
    _attr_icon: str = "mdi:format-list-bulleted"
    def __init__(self, store) -> None:
        self._store: Any = store
    @property
    def native_value(self) -> int:
        return len(self._store.assets)
    @property
    def extra_state_attributes(self):
        assets = []
        for asset_id, asset in self._store.assets.items():
            assets.append(
                {
                    "asset_id": asset_id,
                    "name": asset.get("name"),
                    "asset_type": asset.get("asset_type"),
                    "document_count": asset.get("document_count"),
                    "updated_at": asset.get("updated_at"),
                    "updated_by": asset.get("updated_by"),
                    "environment_requirements": asset.get("environment_requirements"),
                }
            )
        system_defaults: Any | Dict[Any, Any] = getattr(self._store, "system_defaults", {}) or {}
        return {
            "assets": assets,
            "system_defaults": system_defaults,
            "default_label_ids": list(
                system_defaults.get("default_label_ids", []) or []
            ),
        }

# -----------------------------------------------------------
# ROOM ENVIRONMENT ENTITY
# -----------------------------------------------------------
class RoomEnvironmentEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_icon: str = "mdi:home-thermometer-outline"
    def __init__(self, coordinator, store, area_id: str) -> None:
        super().__init__(coordinator)
        self._store = store
        self._area_id: str = area_id
        self._attr_unique_id: str = f"{DOMAIN}_room_environment_{area_id}"
        self._attr_name: str = f"Asset Intelligence {_friendly_area_name(area_id)} Environment"
    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    @property
    def _environment(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        env = None
        # 1. Try projection (fast path — when room has assets)
        for projection in data.values():
            if projection.get("room_area_id") == self._area_id:
                env = projection.get("room_environment")
                break
        # 2. Fallback: compute from room environment cache
        if not isinstance(env, dict):
            cache: Any | Dict[Any, Any] = getattr(self.coordinator, "room_environment_cache", {}) or {}
            env: Any | None = cache.get(self._area_id)
        # 3. Final fallback: default empty
        if not isinstance(env, dict):
            return _default_room_environment(self._area_id)
        merged: Dict[str, Any] = _default_room_environment(self._area_id)
        merged.update(env)
        merged.setdefault("area_id", self._area_id)
        merged.setdefault("configured", True if env else False)
        merged.setdefault("windows", [])
        merged.setdefault("confidence", "STALE")
        merged.setdefault("last_updated", None)
        merged.setdefault("source_status", {})
        return merged

    @property
    def _room_record(self) -> Dict[str, Any]:
        room: Any | None = getattr(self._store, "rooms", {}).get(self._area_id)
        if isinstance(room, dict):
            return room
        return {}
    @property
    def native_value(self):
        env: Dict[str, Any] = self._environment
        return env.get("confidence", "STALE")
    @property
    def extra_state_attributes(self):
        env: Dict[str, Any] = self._environment
        room: Dict[str, Any] = self._room_record
        windows = room.get("windows", [])
        if not isinstance(windows, list):
            windows = []
        room_events = room.get("room_events", [])
        if not isinstance(room_events, list):
            room_events = []
        return {
            "area_id": env.get("area_id", self._area_id),
            "configured": env.get("configured", False),
            "climate": env.get(
                "climate",
                {
                    "temperature": None,
                    "humidity": None,
                    "dew_point": None,
                },
            ),
            "light": env.get(
                "light",
                {
                    "lux": None,
                    "uv": None,
                },
            ),
            "air_quality": env.get(
                "air_quality",
                {
                    "voc": None,
                    "formaldehyde": None,
                    "ozone": None,
                    "no2": None,
                },
            ),
            "particulates": env.get(
                "particulates",
                {
                    "pm2_5": None,
                    "pm10": None,
                },
            ),
            "biological": env.get(
                "biological",
                {
                    "mold_index": None,
                },
            ),
            "safety": env.get(
                "safety",
                {
                    "leak": None,
                },
            ),
            "structural": env.get(
                "structural",
                {
                    "pressure": None,
                    "vibration": None,
                },
            ),
            "context": env.get(
                "context",
                {
                    "noise": None,
                },
            ),
            "control_context": env.get(
                "control_context",
                {
                    "co2": None,
                },
            ),
            "external_environment": env.get(
                "external_environment",
                {
                    "sun": None,
                    "uv_index": None,
                    "forecast": None,
                },
            ),
            "windows": windows,
            "room_events_count": len(room_events),
            "confidence": env.get("confidence", "STALE"),
            "last_updated": env.get("last_updated"),
            "source_status": env.get("source_status", {}),
            "image": env.get("image"),
        }

# -----------------------------------------------------------
# BASE ASSET PROJECTION SENSOR
# -----------------------------------------------------------
class _AssetCoordinatorBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_should_poll = False
    def __init__(self, coordinator, store, asset_id: str, asset: Dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._store = store
        self._asset_id: str = asset_id
        self._asset: Dict[str, Any] = dict(asset)
    def update_from_store(self, asset: Dict[str, Any]) -> None:
        self._asset: Dict[str, Any] = dict(asset)
    @property
    def asset(self) -> Dict[str, Any]:
        stored_asset = self._store.get(self._asset_id)
        if isinstance(stored_asset, dict):
            return stored_asset
        return self._asset
    @property
    def projection(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        projection = data.get(self._asset_id)
        if isinstance(projection, dict):
            return projection
        return _default_unassigned_projection(self._asset_id, None)
    @property
    def room_environment(self) -> Dict[str, Any]:
        projection: Dict[str, Any] = self.projection
        env: Any | None = projection.get("room_environment")
        area_id: Any | None = projection.get("room_area_id")
        if isinstance(env, dict):
            merged: Dict[str, Any] = _default_room_environment(area_id)
            merged.update(env)
            merged.setdefault("area_id", area_id)
            merged.setdefault("configured", False)
            merged.setdefault("windows", [])
            merged.setdefault("confidence", "STALE")
            merged.setdefault("last_updated", None)
            merged.setdefault("source_status", {})
            return merged
        return _default_room_environment(area_id)
    @property
    def risk_state(self) -> str:
        projection: Dict[str, Any] = self.projection
        return projection.get("risk_state") or "AMBER"
    @property
    def candidate_state(self) -> str | None:
        projection: Dict[str, Any] = self.projection
        return projection.get("candidate_state")
    @property
    def reasons(self) -> List[str]:
        projection: Dict[str, Any] = self.projection
        reasons: Any | None = projection.get("reasons")
        if isinstance(reasons, list):
            return reasons
        if reasons is None:
            return []
        return [str(reasons)]
    @property
    def advisories(self) -> List[Dict[str, Any]]:
        projection: Dict[str, Any] = self.projection
        return _normalize_advisories(projection.get("advisories"))
    @property
    def primary_advisory(self) -> Dict[str, Any] | None:
        projection: Dict[str, Any] = self.projection
        return _normalize_primary_advisory(projection.get("primary_advisory"))
    @property
    def primary_advisory_message(self) -> str | None:
        primary: Dict[str, Any] | None = self.primary_advisory
        if not primary:
            return None
        message: Any | None = primary.get("message")
        return str(message) if message not in (None, "") else None
    @property
    def exposure_risk(self) -> str | None:
        projection: Dict[str, Any] = self.projection
        exposure_risk: Any | None = projection.get("exposure_risk")
        if exposure_risk in (None, ""):
            return None
        return str(exposure_risk)
    @property
    def spatial_context(self) -> Dict[str, Any]:
        projection: Dict[str, Any] = self.projection
        spatial_context: Any | None = projection.get("spatial_context")
        if isinstance(spatial_context, dict):
            return spatial_context
        return {}
    @property
    def debounce_action(self) -> str | None:
        projection: Dict[str, Any] = self.projection
        return projection.get("debounce_action")
    @property
    def pending_red_since(self) -> str | None:
        projection: Dict[str, Any] = self.projection
        return projection.get("pending_red_since")
    @property
    def environment_state_since(self) -> str | None:
        projection: Dict[str, Any] = self.projection
        return projection.get("environment_state_since") or self.asset.get("environment_state_since")
    @property
    def last_event(self) -> Dict[str, Any] | None:
        projection: Dict[str, Any] = self.projection
        last_event: Any | None = projection.get("last_event")
        if isinstance(last_event, dict):
            return last_event
        stored_last_event: Any | None = self.asset.get("last_environment_event")
        if isinstance(stored_last_event, dict):
            return stored_last_event
        return None
    # -----------------------------------------------------------
    # DEVICE MODEL
    # -----------------------------------------------------------
    @property
    def device_info(self):
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

# -----------------------------------------------------------
# ASSET RECORD ENTITY
# -----------------------------------------------------------
class AssetRecordEntity(_AssetCoordinatorBaseSensor):
    _attr_icon: str = "mdi:archive"
    def __init__(self, coordinator, store, asset_id: str, asset: Dict[str, Any]) -> None:
        super().__init__(coordinator, store, asset_id, asset)
        self._attr_unique_id: str = f"{DOMAIN}_{asset_id}"
        self._attr_name = asset.get("name", asset_id)
    def update_from_store(self, asset: Dict[str, Any]) -> None:
        super().update_from_store(asset)
        self._attr_name = asset.get("name", self._asset_id)
    @property
    def native_value(self) -> Any | str:
        return self.projection.get("room_area_id") or "unassigned"
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        asset: Dict[str, Any] = self.asset
        audit_log = asset.get("audit_log", []) or []
        compact_audit_log: List[Dict[str, Any]] = _compact_audit_log(audit_log)
        physical_documents: Any | None = asset.get("physical_documents")
        if not isinstance(physical_documents, list):
            physical_documents = []

        normalized_physical_documents = []
        for entry in physical_documents:
            if not isinstance(entry, dict):
                continue
            normalized_physical_documents.append(
                {
                    "type": entry.get("type"),
                    "location": entry.get("location"),
                    "notes": entry.get("notes") or entry.get("description") or "",
                    "description": entry.get("description") or entry.get("notes") or "",
                    "document_id": entry.get("document_id"),
                    "provider_document_id": entry.get("provider_document_id"),
                    "title": entry.get("title"),
                    "recorded_at": entry.get("recorded_at"),
                    "recorded_by": entry.get("recorded_by"),
                }
            )

        loans: Any | None = asset.get("loans")
        if not isinstance(loans, list):
            loans = []
        links: Any | None = asset.get("links")
        if not isinstance(links, dict):
            links = {}
        linked_device_id = links.get("device_id")
        linked_entity_ids = links.get("entity_ids")
        if not isinstance(linked_entity_ids, list):
            linked_entity_ids = []
        room_env: Dict[str, Any] = self.room_environment
        last_event: Dict[str, Any] | None = self.last_event
        room_area_id: Any | None = self.projection.get("room_area_id")
        room_area_name: str | None = _resolve_area_name(self.hass, room_area_id)
        room_configured = bool(room_env.get("configured", False))
        # ✅ FIX: move these OUTSIDE dict
        _raw_docs: Any | None = asset.get("documents")
        _docs = _raw_docs if isinstance(_raw_docs, list) else []
        document_storage_config = getattr(
            self._store,
            "get_document_storage_config",
            lambda: {},
        )()
        documents_enabled = bool(document_storage_config.get("documents_enabled", False))
        attrs = {
            "asset_id": asset.get("asset_id"),
            "name": asset.get("name"),
            "asset_type": asset.get("asset_type"),
            "location_detail": asset.get("location_detail"),
            "created_at": asset.get("created_at"),
            "updated_at": asset.get("updated_at"),
            "created_by": asset.get("created_by"),
            "updated_by": asset.get("updated_by"),
            "last_action": _last_action(audit_log),
            "audit_summary": _audit_summary(audit_log),
            "audit_log": compact_audit_log,
            "document_count": asset.get("document_count"),
            "document_summary": asset.get("document_summary", []),
            "last_document_id": asset.get("last_document_id"),
            "last_document_title": asset.get("last_document_title"),
            "physical_document_locations": normalized_physical_documents,
            "trackers": asset.get("trackers", []),
            "type_metadata": asset.get("type_metadata", {}),
            "environment_requirements": asset.get("environment_requirements") or {},
            "purchase": asset.get("purchase", {}),
            "valuation": asset.get("valuation", {}),
            "manufacturer_detail": asset.get("manufacturer_detail", ""),
            "warranty": asset.get("warranty", {}),
            "descriptions": asset.get("descriptions", {}),
            "placement": asset.get("placement", {}),
            "enclosure": asset.get("enclosure", {}),
            "custody": asset.get("custody", {}),
            "links": links,
            "linked_device_id": linked_device_id,
            "linked_entity_ids": linked_entity_ids,
            "loans": loans,
            "schema_version": asset.get("schema_version"),
            "quantity": asset.get("quantity", 1),
            # ✅ Safe document storage flag
            "document_storage_configured": documents_enabled,
            "documents_enabled": documents_enabled,
            # ✅ Safe documents projection
            "documents": [
                projected
                for d in _docs
                for projected in [_project_document_for_state(d)]
                if projected is not None
            ],
            "room_environment": {
                "area_id": room_area_id,
                "area_name": room_area_name,
                "configured": room_configured,
                "climate": room_env.get("climate"),
                "light": room_env.get("light"),
                "air_quality": room_env.get("air_quality"),
                "particulates": room_env.get("particulates"),
                "biological": room_env.get("biological"),
                "safety": room_env.get("safety"),
                "structural": room_env.get("structural"),
                "context": room_env.get("context"),
                "control_context": room_env.get("control_context"),
                "external_environment": room_env.get("external_environment"),
                "windows": room_env.get("windows", []),
                "confidence": room_env.get("confidence"),
                "last_updated": room_env.get("last_updated"),
                "source_status": {},
            },
            "room_environment_room": room_area_name,
            "room_environment_configured": room_configured,
            "environment_risk_state": self.risk_state,
            "candidate_environment_risk_state": self.candidate_state,
            "environment_risk_reasons": self.reasons,
            "environment_pending_red_since": self.pending_red_since,
            "environment_risk_debounce_action": self.debounce_action,
            "advisories": self.advisories,
            "primary_advisory": self.primary_advisory,
            "primary_advisory_message": self.primary_advisory_message,
            "exposure_risk": self.exposure_risk,
            "spatial_context": self.spatial_context,
            "last_environment_risk_state": asset.get("last_environment_risk_state"),
            "environment_state_since": self.environment_state_since,
            "environment_event_count": asset.get("environment_event_count", 0),
            "last_environment_event": last_event,
        }
        return _compact_sensor_attributes_for_recorder(attrs)
