from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN


import os

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.storage"

AUDIT_MAX_ENTRIES = 200
AUDIT_MAX_STRING_LENGTH = 500
AUDIT_MAX_LIST_ITEMS = 20
AUDIT_MAX_DICT_ITEMS = 40
AUDIT_MAX_NESTING_DEPTH = 5
AUDIT_HEAVY_DETAIL_KEYS = {
    "environment_requirements",
    "room_environment",
    "documents",
    "physical_documents",
    "environment_events",
    "advisory_events",
    "custody_events",
}


def _compact_audit_value(value: Any, key: str = "", depth: int = 0) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        if len(value) > AUDIT_MAX_STRING_LENGTH:
            return f"{value[:AUDIT_MAX_STRING_LENGTH - 3]}..."
        return value

    if depth >= AUDIT_MAX_NESTING_DEPTH:
        if isinstance(value, dict):
            return {"_truncated": True, "type": "dict", "count": len(value)}
        if isinstance(value, list):
            return {"_truncated": True, "type": "list", "count": len(value)}
        return str(value)

    if isinstance(value, list):
        compacted = [
            _compact_audit_value(item, key=key, depth=depth + 1)
            for item in value[:AUDIT_MAX_LIST_ITEMS]
        ]
        if len(value) > AUDIT_MAX_LIST_ITEMS:
            compacted.append(
                {"_truncated": True, "remaining": len(value) - AUDIT_MAX_LIST_ITEMS}
            )
        return compacted

    if isinstance(value, dict):
        if key in AUDIT_HEAVY_DETAIL_KEYS and "field_changes" not in value:
            return {
                "_summary": "large_payload_omitted",
                "keys": list(value.keys())[:AUDIT_MAX_LIST_ITEMS],
                "key_count": len(value),
            }

        compacted_dict: Dict[str, Any] = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= AUDIT_MAX_DICT_ITEMS:
                compacted_dict["_truncated"] = True
                compacted_dict["_remaining_count"] = len(value) - AUDIT_MAX_DICT_ITEMS
                break

            key_text = str(child_key)
            compacted_dict[key_text] = _compact_audit_value(
                child_value,
                key=key_text,
                depth=depth + 1,
            )

        return compacted_dict

    return str(value)


def _compact_audit_details(details: Any) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {"value": _compact_audit_value(details)}

    compacted = _compact_audit_value(details)
    return compacted if isinstance(compacted, dict) else {"value": compacted}


def _normalize_audit_log_entries(entries: Any, max_entries: int = AUDIT_MAX_ENTRIES) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    normalized: list[Dict[str, Any]] = []
    for item in entries[-max_entries:]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "timestamp": item.get("timestamp"),
                "action": item.get("action"),
                "actor": item.get("actor") or "unknown",
                "details": _compact_audit_details(item.get("details") or {}),
            }
        )

    return normalized

# -----------------------------------------------------------
# FILESYSTEM STORAGE INITIALIZATION (Phase 7)
# -----------------------------------------------------------
async def async_ensure_storage(hass: HomeAssistant, options: dict) -> None:
    """Ensure filesystem storage structure exists (idempotent).

    This is intentionally separate from AssetStore.
    It manages OS-level directories, not HA storage.
    """

    base_path = options.get("storage_base_path")

    if not base_path:
        return

    base_path = os.path.expanduser(base_path)

    required_dirs = [
        base_path,
        os.path.join(base_path, "assets"),
        os.path.join(base_path, "documents"),
        os.path.join(base_path, "images"),
    ]

    def _create_dirs() -> None:
        for path in required_dirs:
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                pass

    await hass.async_add_executor_job(_create_dirs)

class AssetStore:
    """System of record and persistence layer for Asset Intelligence.

    Responsibilities:
    - Persist assets and rooms
    - Normalize stored schema to the current canonical structure
    - Maintain bounded history collections
    - Expose store CRUD helpers only

    This file must NOT:
    - perform evaluation
    - perform environment sensing
    - generate coordinator/runtime decisions
    - store transient projection-only runtime state
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        self.assets: Dict[str, Dict[str, Any]] = {}
        self.rooms: Dict[str, Dict[str, Any]] = {}

        # -----------------------------------------------------------
        # Phase 5 — Document storage configuration
        # -----------------------------------------------------------
        self.document_storage: Dict[str, Any] = {}

        # -----------------------------------------------------------
        # Phase 4G — Policy Definitions
        # -----------------------------------------------------------
        self.label_profiles: Dict[str, Dict[str, Any]] = {}
        self.system_defaults: Dict[str, Any] = {}

    # -----------------------------------------------------------
    # LOAD / SAVE
    # -----------------------------------------------------------
    async def async_load(self) -> None:
        """Load persisted data and normalize it to the current schema."""
        stored = await self._store.async_load()

        if not isinstance(stored, dict):
            self.assets = {}
            self.rooms = {}
            self.document_storage = self._empty_document_storage_config()
            return

        raw_assets = stored.get("assets", {})
        raw_rooms = stored.get("rooms", {})
        raw_document_storage = stored.get("document_storage", {})
        raw_label_profiles = stored.get("label_profiles", {})
        raw_system_defaults = stored.get("system_defaults", {})

        self.assets = raw_assets if isinstance(raw_assets, dict) else {}
        self.rooms = raw_rooms if isinstance(raw_rooms, dict) else {}
        self.document_storage = (
            raw_document_storage if isinstance(raw_document_storage, dict) else {}
        )
        self.label_profiles = (
            raw_label_profiles if isinstance(raw_label_profiles, dict) else {}
        )
        self.system_defaults = (
            raw_system_defaults if isinstance(raw_system_defaults, dict) else {}
        )

        changed = False

        # Normalize existing asset records to current schema.
        for asset_id, asset in list(self.assets.items()):
            if not isinstance(asset, dict):
                self.assets[asset_id] = {}
                asset = self.assets[asset_id]
                changed = True

            if self._ensure_asset_structure(asset):
                changed = True

        # Normalize existing room records to current schema.
        for area_id, room in list(self.rooms.items()):
            if not isinstance(room, dict):
                self.rooms[area_id] = {}
                room = self.rooms[area_id]
                changed = True

            if self._ensure_room_structure(room):
                changed = True

        # Normalize top-level document storage configuration.
        if self._ensure_document_storage_structure():
            changed = True

        # -----------------------------------------------------------
        # 4G — Ensure policy defaults exist
        # -----------------------------------------------------------
        if not self.system_defaults:
            self.system_defaults = {
                "debounce": {
                    "red_transition_seconds": 300,
                    "recovery_seconds": 600,
                },
                "default_label_ids": [],
            }
            changed = True

        if not self.label_profiles:
            self.label_profiles = {
                "asset_type:painting": {
                    "debounce": {
                        "red_transition_seconds": 900,
                        "recovery_seconds": 1200,
                    }
                },
                "asset_type:electronics": {
                    "debounce": {
                        "red_transition_seconds": 120,
                        "recovery_seconds": 300,
                    }
                },
                "asset_type:books": {
                    "debounce": {
                        "red_transition_seconds": 600,
                        "recovery_seconds": 900,
                    }
                },
                "asset_type:instrument": {
                    "debounce": {
                        "red_transition_seconds": 600,
                        "recovery_seconds": 900,
                    }
                },
                "sensitivity:high": {
                    "debounce": {
                        "red_transition_seconds": 900,
                        "recovery_seconds": 1200,
                    }
                },
            }
            changed = True

        # Persist forward-only normalization so subsequent loads are stable.
        if changed:
            await self.async_save()

    async def async_save(self) -> None:
        """Persist current store state."""
        await self._store.async_save(
            {
                "version": STORAGE_VERSION,
                "assets": self.assets,
                "rooms": self.rooms,
                "document_storage": self.document_storage,
                "label_profiles": self.label_profiles,
                "system_defaults": self.system_defaults,
            }
        )

    # -----------------------------------------------------------
    # STRUCTURE NORMALIZATION
    # -----------------------------------------------------------
    def _ensure_asset_structure(self, asset: Dict[str, Any]) -> bool:
        """Ensure required asset fields exist for the canonical schema.

        Returns True if the object was modified.
        """
        changed = False

        # Area and labels are owned by Home Assistant registries, not store records.
        if "area_id" in asset:
            asset.pop("area_id", None)
            changed = True
        if "labels" in asset:
            asset.pop("labels", None)
            changed = True

        # -------------------------------------------------------
        # Core identity / metadata
        # -------------------------------------------------------
        changed |= self._ensure_list_field(asset, "audit_log")
        changed |= self._ensure_list_field(asset, "documents")
        changed |= self._ensure_list_field(asset, "physical_documents")
        changed |= self._ensure_list_field(asset, "trackers")
        changed |= self._ensure_dict_field(asset, "links")
        changed |= self._ensure_list_field(asset, "loans")

        normalized_audit = _normalize_audit_log_entries(asset.get("audit_log", []))
        if normalized_audit != asset.get("audit_log"):
            asset["audit_log"] = normalized_audit
            changed = True

        # -------------------------------------------------------
        # Canonical digital document normalization (single pass)
        # -------------------------------------------------------
        documents = asset.get("documents", [])
        if not isinstance(documents, list):
            asset["documents"] = []
            documents = asset["documents"]
            changed = True

        normalized_documents: List[Dict[str, Any]] = []
        documents_modified = False

        for item in documents:
            normalized_item = self._normalize_document_record(item)
            normalized_documents.append(normalized_item)

            if normalized_item != item:
                documents_modified = True

        if documents_modified:
            asset["documents"] = normalized_documents
            changed = True

        # -------------------------------------------------------
        # Placement model
        # -------------------------------------------------------
        placement_changed, placement = self._ensure_dict_value(asset.get("placement"))
        if placement_changed or "placement" not in asset:
            asset["placement"] = placement
            changed = True

        if "area_id" in placement:
            placement.pop("area_id", None)
            changed = True

        placement_defaults = {
            "near_window": False,
            "exposure_zone": None,
            "facing_direction": None,
        }
        for key, default_value in placement_defaults.items():
            if key not in placement:
                placement[key] = default_value
                changed = True

        # -------------------------------------------------------
        # Enclosure model
        # -------------------------------------------------------
        enclosure_changed, enclosure = self._ensure_dict_value(asset.get("enclosure"))
        if enclosure_changed or "enclosure" not in asset:
            asset["enclosure"] = enclosure
            changed = True

        enclosure_defaults = {
            "type": None,
            "sealed": None,
        }
        for key, default_value in enclosure_defaults.items():
            if key not in enclosure:
                enclosure[key] = default_value
                changed = True

        # -------------------------------------------------------
        # Environment requirements model (canonical)
        # -------------------------------------------------------
        req_changed, requirements = self._ensure_dict_value(
            asset.get("environment_requirements")
        )
        if req_changed or "environment_requirements" not in asset:
            asset["environment_requirements"] = requirements
            changed = True

        default_requirements = self._empty_environment_requirements()

        for section, section_default in default_requirements.items():
            if section not in requirements or not isinstance(requirements.get(section), dict):
                requirements[section] = deepcopy(section_default)
                changed = True
                continue

            if isinstance(section_default, dict):
                for key, value_default in section_default.items():
                    if key not in requirements[section]:
                        requirements[section][key] = deepcopy(value_default)
                        changed = True

        # -------------------------------------------------------
        # Event / history model
        # -------------------------------------------------------
        changed |= self._ensure_list_field(asset, "environment_events")
        changed |= self._ensure_list_field(asset, "advisory_events")
        changed |= self._ensure_list_field(asset, "custody_events")

        if "environment_event_count" not in asset or not isinstance(
            asset.get("environment_event_count"), int
        ):
            asset["environment_event_count"] = 0
            changed = True

        if "last_environment_event" not in asset:
            asset["last_environment_event"] = None
            changed = True

        environment_events = asset.get("environment_events", [])
        if isinstance(environment_events, list):
            actual_event_count = len(environment_events)
            if asset.get("environment_event_count") != actual_event_count:
                asset["environment_event_count"] = actual_event_count
                changed = True

            if environment_events:
                if asset.get("last_environment_event") is None:
                    asset["last_environment_event"] = environment_events[-1]
                    changed = True

        # -------------------------------------------------------
        # Persistent runtime state used by coordinator
        # -------------------------------------------------------
        state_defaults = {
            "last_environment_risk_state": None,
            "environment_state_since": None,
            "environment_pending_red_since": None,
        }
        for key, default_value in state_defaults.items():
            if key not in asset:
                asset[key] = default_value
                changed = True

        # -------------------------------------------------------
        # Profiling / measurement model
        # -------------------------------------------------------
        profile_changed, environment_profile = self._ensure_dict_value(
            asset.get("environment_profile")
        )
        if profile_changed or "environment_profile" not in asset:
            asset["environment_profile"] = environment_profile
            changed = True

        if "baseline" not in environment_profile or not isinstance(
            environment_profile.get("baseline"), dict
        ):
            environment_profile["baseline"] = {}
            changed = True

        baseline = environment_profile["baseline"]
        baseline_defaults = {
            "avg_lux": None,
            "peak_lux": None,
            "avg_uv": None,
            "peak_uv": None,
            "exposure_window": None,
            "observation_period": None,
            "observation_duration_seconds": None,
            "sample_count": 0,
            "sensors_used": [],
            "confidence": None,
            "baseline_classification": None,
            "recommendation": None,
            "generated_at": None,
        }
        for key, default_value in baseline_defaults.items():
            if key not in baseline:
                baseline[key] = deepcopy(default_value)
                changed = True

        if not isinstance(baseline.get("sensors_used"), list):
            baseline["sensors_used"] = []
            changed = True

        active_measurement_changed, active_measurement = self._ensure_dict_value(
            asset.get("active_measurement")
        )
        if active_measurement_changed or "active_measurement" not in asset:
            asset["active_measurement"] = active_measurement
            changed = True

        empty_active = self._empty_active_measurement()
        for key, default_value in empty_active.items():
            if key not in active_measurement:
                active_measurement[key] = deepcopy(default_value)
                changed = True

        if not isinstance(active_measurement.get("sensors"), list):
            active_measurement["sensors"] = []
            changed = True

        if not isinstance(active_measurement.get("observations"), list):
            active_measurement["observations"] = []
            changed = True

        sessions = asset.get("measurement_sessions")
        if not isinstance(sessions, list):
            asset["measurement_sessions"] = []
            sessions = asset["measurement_sessions"]
            changed = True

        normalized_sessions: List[Dict[str, Any]] = []
        sessions_modified = False
        for item in sessions:
            normalized_item = self._normalize_completed_session(item)
            normalized_sessions.append(normalized_item)
            if normalized_item is not item:
                sessions_modified = True

        if sessions_modified:
            asset["measurement_sessions"] = normalized_sessions
            changed = True

        return changed

    def _ensure_room_structure(self, room: Dict[str, Any]) -> bool:
        """Ensure required room fields exist for the canonical room schema."""
        changed = False
        changed |= self._ensure_dict_field(room, "environment_config")
        changed |= self._ensure_list_field(room, "windows")
        changed |= self._ensure_list_field(room, "room_events")
        return changed

    # -----------------------------------------------------------
    # ROOM CONFIG / ROOM PERSISTENCE
    # -----------------------------------------------------------
    async def set_room_environment(self, area_id: str, config: Dict[str, Any]) -> None:
        room = self.rooms.get(area_id, {})
        if not isinstance(room, dict):
            room = {}

        self._ensure_room_structure(room)
        room["environment_config"] = config if isinstance(config, dict) else {}

        self.rooms[area_id] = room
        await self.async_save()

    async def set_room_windows(self, area_id: str, windows: List[Dict[str, Any]]) -> None:
        room = self.rooms.get(area_id, {})
        if not isinstance(room, dict):
            room = {}

        self._ensure_room_structure(room)
        room["windows"] = windows if isinstance(windows, list) else []

        self.rooms[area_id] = room
        await self.async_save()

    def get_room(self, area_id: str) -> Optional[Dict[str, Any]]:
        return self.rooms.get(area_id)

    def get_room_environment(self, area_id: str) -> Optional[Dict[str, Any]]:
        room = self.rooms.get(area_id)
        if not room:
            return None
        return room.get("environment_config")

    def get_room_windows(self, area_id: str) -> List[Dict[str, Any]]:
        room = self.rooms.get(area_id)
        if not room:
            return []
        windows = room.get("windows", [])
        return windows if isinstance(windows, list) else []

    async def append_room_event(
        self,
        area_id: str,
        event: Dict[str, Any],
        max_events: int = 200,
    ) -> None:
        room = self.rooms.get(area_id)
        if not room:
            room = {}
            self.rooms[area_id] = room

        self._ensure_room_structure(room)

        events = room.get("room_events", [])
        if not isinstance(events, list):
            events = []

        events.append(event)
        room["room_events"] = events[-max_events:]

        await self.async_save()

    # -----------------------------------------------------------
    # ASSET CRUD
    # -----------------------------------------------------------
    async def add_or_replace(self, asset_dict: Dict[str, Any]) -> None:
        asset_id = asset_dict["asset_id"]
        self._ensure_asset_structure(asset_dict)
        self.assets[asset_id] = asset_dict
        await self.async_save()

    def get(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self.assets.get(asset_id)

    # -----------------------------------------------------------
    # AUDIT LOG
    # -----------------------------------------------------------
    async def append_audit_entry(
        self,
        asset_id: str,
        action: str,
        actor: str,
        details: Dict[str, Any],
        max_entries: int = 200,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        entry = {
            "timestamp": self._now_iso(),
            "action": action,
            "actor": actor or "unknown",
            "details": _compact_audit_details(details or {}),
        }

        log = asset.get("audit_log", [])
        if not isinstance(log, list):
            log = []

        log.append(entry)
        bounded_max = min(max_entries, AUDIT_MAX_ENTRIES)
        asset["audit_log"] = _normalize_audit_log_entries(log, max_entries=bounded_max)

        await self.async_save()

    # -----------------------------------------------------------
    # ENVIRONMENT EVENT MODEL (PRIMARY HISTORY)
    # -----------------------------------------------------------
    async def append_environment_event(
        self,
        asset_id: str,
        event: Dict[str, Any],
        max_events: int = 200,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        events = asset.get("environment_events", [])
        if not isinstance(events, list):
            events = []

        events.append(event)
        events = events[-max_events:]

        asset["environment_events"] = events
        asset["environment_event_count"] = len(events)
        asset["last_environment_event"] = event

        await self.async_save()

    # -----------------------------------------------------------
    # ADVISORY EVENT MODEL
    # -----------------------------------------------------------
    async def append_advisory_event(
        self,
        asset_id: str,
        event: Dict[str, Any],
        max_events: int = 200,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        events = asset.get("advisory_events", [])
        if not isinstance(events, list):
            events = []

        events.append(event)
        asset["advisory_events"] = events[-max_events:]

        await self.async_save()

    # -----------------------------------------------------------
    # CUSTODY EVENT MODEL
    # -----------------------------------------------------------
    async def append_custody_event(
        self,
        asset_id: str,
        event: Dict[str, Any],
        max_events: int = 100,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        events = asset.get("custody_events", [])
        if not isinstance(events, list):
            events = []

        events.append(event)
        asset["custody_events"] = events[-max_events:]

        await self.async_save()

    # -----------------------------------------------------------
    # ENVIRONMENT PROFILE / MEASUREMENT SESSIONS
    # -----------------------------------------------------------
    async def set_environment_profile(
        self,
        asset_id: str,
        profile: Dict[str, Any],
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)
        asset["environment_profile"] = profile if isinstance(profile, dict) else {}
        self._ensure_asset_structure(asset)

        await self.async_save()

    async def start_measurement_session(
        self,
        asset_id: str,
        session: Dict[str, Any],
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        normalized = self._empty_active_measurement()
        if isinstance(session, dict):
            normalized.update(session)

        if not isinstance(normalized.get("sensors"), list):
            normalized["sensors"] = []

        if not isinstance(normalized.get("observations"), list):
            normalized["observations"] = []

        normalized["status"] = "active"
        normalized["stop_requested"] = False
        normalized["manual_generate_requested"] = False

        asset["active_measurement"] = normalized
        self._ensure_asset_structure(asset)

        await self.async_save()

    async def update_active_measurement_session(
        self,
        asset_id: str,
        session: Dict[str, Any],
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        normalized = self._empty_active_measurement()
        if isinstance(session, dict):
            normalized.update(session)

        if not isinstance(normalized.get("sensors"), list):
            normalized["sensors"] = []

        if not isinstance(normalized.get("observations"), list):
            normalized["observations"] = []

        asset["active_measurement"] = normalized
        self._ensure_asset_structure(asset)

        await self.async_save()

    async def append_measurement_observation(
        self,
        asset_id: str,
        observation: Dict[str, Any],
        max_observations: int = 2000,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        active = asset.get("active_measurement")
        if not isinstance(active, dict):
            return

        observations = active.get("observations", [])
        if not isinstance(observations, list):
            observations = []

        observation_item = observation if isinstance(observation, dict) else {}
        observations.append(observation_item)
        observations = observations[-max_observations:]

        active["observations"] = observations
        active["last_observation_at"] = observation_item.get("observed_at") or self._now_iso()

        asset["active_measurement"] = active
        await self.async_save()

    async def request_stop_measurement_session(
        self,
        asset_id: str,
        reason: str = "manual_stop",
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        active = asset.get("active_measurement")
        if not isinstance(active, dict):
            return

        if not active.get("started_at"):
            return

        active["stop_requested"] = True
        active["stop_reason"] = reason
        active["stop_requested_at"] = self._now_iso()

        asset["active_measurement"] = active
        await self.async_save()

    async def request_manual_profile_generation(self, asset_id: str) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        active = asset.get("active_measurement")
        if not isinstance(active, dict):
            return

        if not active.get("started_at"):
            return

        active["manual_generate_requested"] = True
        active["manual_generate_requested_at"] = self._now_iso()

        asset["active_measurement"] = active
        await self.async_save()

    async def clear_active_measurement(
        self,
        asset_id: str,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)
        asset["active_measurement"] = self._empty_active_measurement()
        await self.async_save()

    async def complete_measurement_session(
        self,
        asset_id: str,
        completed_session: Dict[str, Any],
        profile: Optional[Dict[str, Any]] = None,
        max_sessions: int = 50,
    ) -> None:
        asset = self.assets.get(asset_id)
        if not asset:
            return

        self._ensure_asset_structure(asset)

        sessions = asset.get("measurement_sessions", [])
        if not isinstance(sessions, list):
            sessions = []

        normalized_session = self._normalize_completed_session(completed_session)
        sessions.append(normalized_session)
        asset["measurement_sessions"] = sessions[-max_sessions:]

        if isinstance(profile, dict):
            asset["environment_profile"] = profile

        asset["active_measurement"] = self._empty_active_measurement()
        self._ensure_asset_structure(asset)

        await self.async_save()

    # -----------------------------------------------------------
    # DOCUMENT STORAGE CONFIG
    # -----------------------------------------------------------
    async def set_document_storage_config(self, config: Dict[str, Any]) -> None:
        self.document_storage = (
            config if isinstance(config, dict) else self._empty_document_storage_config()
        )
        self._ensure_document_storage_structure()
        await self.async_save()

    def get_document_storage_config(self) -> Dict[str, Any]:
        self._ensure_document_storage_structure()
        return deepcopy(self.document_storage)

    def has_document_storage_configured(self) -> bool:
        self._ensure_document_storage_structure()
        return bool(self.document_storage.get("documents_enabled", False))

    # -----------------------------------------------------------
    # READ HELPERS / ANALYTICS HOOKS
    # -----------------------------------------------------------
    def get_environment_history(self, asset_id: str) -> List[Dict[str, Any]]:
        asset = self.assets.get(asset_id)
        if not asset:
            return []

        events = asset.get("environment_events", [])
        return events if isinstance(events, list) else []

    def get_latest_environment_event(self, asset_id: str) -> Optional[Dict[str, Any]]:
        asset = self.assets.get(asset_id)
        if not asset:
            return None
        return asset.get("last_environment_event")

    def get_advisory_history(self, asset_id: str) -> List[Dict[str, Any]]:
        asset = self.assets.get(asset_id)
        if not asset:
            return []

        events = asset.get("advisory_events", [])
        return events if isinstance(events, list) else []

    def get_room_history(self, area_id: str) -> List[Dict[str, Any]]:
        room = self.rooms.get(area_id)
        if not room:
            return []

        events = room.get("room_events", [])
        return events if isinstance(events, list) else []

    def get_environment_profile(self, asset_id: str) -> Optional[Dict[str, Any]]:
        asset = self.assets.get(asset_id)
        if not asset:
            return None

        profile = asset.get("environment_profile")
        return profile if isinstance(profile, dict) else None

    def get_active_measurement(self, asset_id: str) -> Optional[Dict[str, Any]]:
        asset = self.assets.get(asset_id)
        if not asset:
            return None

        measurement = asset.get("active_measurement")
        return measurement if isinstance(measurement, dict) else None

    def get_measurement_sessions(self, asset_id: str) -> List[Dict[str, Any]]:
        asset = self.assets.get(asset_id)
        if not asset:
            return []

        sessions = asset.get("measurement_sessions", [])
        return sessions if isinstance(sessions, list) else []

    # -----------------------------------------------------------
    # DOCUMENT MODEL NORMALIZATION (CANONICAL ONLY)
    # -----------------------------------------------------------
    def _empty_document_record(self) -> Dict[str, Any]:
        """Return canonical document metadata record."""
        return {
            "document_id": None,
            "type": None,
            "title": None,
            "filename": None,
            "provider": None,
            "provider_document_id": None,
            "mime_type": None,
            "size_bytes": None,
            "tags": [],
            "metadata": {},
        }

    def _normalize_document_record(self, doc: Any) -> dict[str, Any]:
        """Normalize a document metadata record into canonical shape."""
        normalized = self._empty_document_record()

        if not isinstance(doc, dict):
            return normalized

        # Scalars are immutable — direct assignment is safe and faster than deepcopy.
        normalized["document_id"] = doc.get("document_id")
        normalized["type"] = doc.get("type")
        normalized["title"] = doc.get("title")
        normalized["filename"] = doc.get("filename")
        normalized["provider"] = doc.get("provider")
        normalized["provider_document_id"] = doc.get("provider_document_id")
        normalized["mime_type"] = doc.get("mime_type")
        normalized["size_bytes"] = doc.get("size_bytes")

        # Lists and dicts need a shallow/deep copy to prevent aliasing.
        tags = doc.get("tags")
        normalized["tags"] = list(tags) if isinstance(tags, list) else []

        metadata = doc.get("metadata")
        normalized_metadata: dict[str, Any] = deepcopy(metadata) if isinstance(metadata, dict) else {}

        # Lift any canonical optional fields that live on the doc root into metadata.
        for optional_metadata_key in (
            "notes",
            "date",
            "checksum",
            "checksum_type",
            "version",
            "created_at",
            "created_by",
            "available",
            "file_ext",
            "uri",
            "preview_uri",
        ):
            if optional_metadata_key in doc and optional_metadata_key not in normalized_metadata:
                normalized_metadata[optional_metadata_key] = doc.get(optional_metadata_key)

        normalized["metadata"] = normalized_metadata

        if normalized.get("size_bytes") is not None and not isinstance(
            normalized.get("size_bytes"), int
        ):
            normalized["size_bytes"] = None

        return normalized

    # -----------------------------------------------------------
    # PHASE 5 — DOCUMENT STORAGE / DOCUMENT METADATA NORMALIZATION
    # -----------------------------------------------------------
    def _empty_document_storage_config(self) -> Dict[str, Any]:
        return {
            "provider": "filesystem",
            "root_path": None,
            "documents_enabled": False,
            "requires_network_storage": True,
        }

    def _ensure_document_storage_structure(self) -> bool:
        changed = False

        if not isinstance(self.document_storage, dict):
            self.document_storage = {}
            changed = True

        defaults = self._empty_document_storage_config()
        for key, default_value in defaults.items():
            if key not in self.document_storage:
                self.document_storage[key] = deepcopy(default_value)
                changed = True

        if not isinstance(self.document_storage.get("provider"), str):
            self.document_storage["provider"] = "filesystem"
            changed = True

        root_path = self.document_storage.get("root_path")
        if root_path is not None and not isinstance(root_path, str):
            self.document_storage["root_path"] = None
            changed = True

        if not isinstance(self.document_storage.get("documents_enabled"), bool):
            self.document_storage["documents_enabled"] = False
            changed = True

        if not isinstance(self.document_storage.get("requires_network_storage"), bool):
            self.document_storage["requires_network_storage"] = True
            changed = True

        return changed

    # -----------------------------------------------------------
    # INTERNAL UTIL
    # -----------------------------------------------------------
    def _empty_active_measurement(self) -> Dict[str, Any]:
        return {
            "session_id": None,
            "status": None,
            "sensors": [],
            "started_at": None,
            "duration_days": None,
            "actor": None,
            "notes": None,
            "observations": [],
            "last_observation_at": None,
            "stop_requested": False,
            "stop_requested_at": None,
            "stop_reason": None,
            "manual_generate_requested": False,
            "manual_generate_requested_at": None,
        }

    def _normalize_completed_session(self, session: Any) -> Dict[str, Any]:
        normalized: Dict[str, Any] = session if isinstance(session, dict) else {}

        defaults = {
            "session_id": None,
            "status": None,
            "started_at": None,
            "stopped_at": None,
            "requested_duration_days": None,
            "actual_duration_seconds": None,
            "actor": None,
            "notes": None,
            "sensors": [],
            "observations": [],
            "summary": {},
            "completed_at": None,
        }
        for key, default_value in defaults.items():
            if key not in normalized:
                normalized[key] = deepcopy(default_value)

        if not isinstance(normalized.get("sensors"), list):
            normalized["sensors"] = []

        if not isinstance(normalized.get("observations"), list):
            normalized["observations"] = []

        if not isinstance(normalized.get("summary"), dict):
            normalized["summary"] = {}

        return normalized

    def _empty_environment_requirements(self) -> Dict[str, Any]:
        return {
            "climate": {
                "temperature": {"min": None, "max": None},
                "humidity": {"min": None, "max": None},
                "dew_point": {"min": None, "max": None},
            },
            "light": {
                "lux": {"min": None, "max": None},
                "uv": {"min": None, "max": None},
            },
            "safety": {
                "leak": {"min": None, "max": None},
            },
            "air_quality": {
                "voc": {"min": None, "max": None},
                "formaldehyde": {"min": None, "max": None},
                "ozone": {"min": None, "max": None},
                "no2": {"min": None, "max": None},
            },
            "particulates": {
                "pm2_5": {"min": None, "max": None},
                "pm10": {"min": None, "max": None},
            },
            "biological": {
                "mold_index": {"min": None, "max": None},
            },
            "structural": {
                "pressure": {"min": None, "max": None},
                "vibration": {"min": None, "max": None},
            },
            "context": {
                "noise": {"min": None, "max": None},
            },
            "control_context": {
                "co2": {"min": None, "max": None},
            },
            "debounce": {
                "red_transition_seconds": None,
                "recovery_seconds": None,
            },
        }

    def _ensure_list_field(self, parent: Dict[str, Any], key: str) -> bool:
        value = parent.get(key)
        if not isinstance(value, list):
            parent[key] = []
            return True
        return False

    def _ensure_dict_field(self, parent: Dict[str, Any], key: str) -> bool:
        value = parent.get(key)
        if not isinstance(value, dict):
            parent[key] = {}
            return True
        return False

    def _ensure_dict_value(self, value: Any) -> tuple[bool, Dict[str, Any]]:
        if isinstance(value, dict):
            return False, value
        return True, {}

    def _now_iso(self) -> str:
        from homeassistant.util import dt as dt_util
        return dt_util.now().isoformat()