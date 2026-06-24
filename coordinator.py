"""Coordinator runtime for Asset Intelligence.
This module is the runtime orchestration layer for the integration.
Responsibilities:
- Build one shared room environment snapshot per room per cycle
- Evaluate all assets against that shared room snapshot
- Apply runtime persistence side effects
- Append environment events on effective state transition
- Maintain lightweight in-memory projections for entities
- Notify subscribers when a refresh cycle completes
This module deliberately keeps:
- storage.py as the full system of record
- environment.py as the room sensing model
- evaluation.py as the pure decision engine
- advisory.py as the pure recommendation engine
- entities as lightweight projections only
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .advisory import generate_asset_advisory
from .const import DOMAIN
from .environment import get_room_environment
from .evaluation import evaluate_asset_environment, evaluate_room_human_health
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from .services.document_retrieval import DocumentRetrievalService
from .storage import AssetStore
_LOGGER = logging.getLogger(__name__)
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=5)
COORDINATOR_SIGNAL = f"{DOMAIN}_coordinator_updated"

@dataclass(slots=True)
class AssetProjection:
    """Lightweight in-memory projection exposed to entities."""
    asset_id: str
    room_area_id: str | None
    room_environment: dict[str, Any]
    risk_state: str
    candidate_state: str | None
    reasons: list[str]
    pending_red_since: str | None
    debounce_action: str | None
    environment_state_since: str | None
    last_event: dict[str, Any] | None
    exposure_risk: dict[str, Any] | None = None
    spatial_context: dict[str, Any] | None = None
    resolved_debounce: dict[str, Any] | None = None

class AssetIntelligenceCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Central runtime coordinator for Asset Intelligence."""
    def __init__(
        self,
        hass: HomeAssistant,
        store: AssetStore,
        *,
        update_interval: timedelta | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=update_interval or DEFAULT_UPDATE_INTERVAL,
        )
        self.store = store
        # ---------------------------------------------------------
        # Phase 6.6 — Document Retrieval Service
        # ---------------------------------------------------------
        self.document_retrieval = DocumentRetrievalService(
            hass=self.hass,
            store=self.store,
        )
        # Latest per-room environment snapshot cache
        self._room_environment_cache: dict[str | None, dict[str, Any]] = {}
        # Latest per-asset typed projection cache
        self._projection_index: dict[str, AssetProjection] = {}
        # ---------------------------------------------------------
        # Phase 4E — Measurement Runtime Cache
        # ---------------------------------------------------------
        # Tracks in-progress measurement sessions (NOT persisted here)
        self._active_measurements: dict[str, dict[str, Any]] = {}
    def _get_device_area_id(self, asset_id: str) -> str | None:
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device({(DOMAIN, asset_id)})
        if device:
            return device.area_id
        return None
    def _resolve_runtime_area_id(self, asset_id: str) -> str | None:
        """Return runtime area id for an asset from Home Assistant device registry."""
        return self._get_device_area_id(asset_id)

    def _get_registry_labels(self, asset_id: str) -> list[str]:
        """Return labels for an asset from Home Assistant registries.

        We prefer HA registry ownership and never read labels from store records.
        """
        labels: set[str] = set()

        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device({(DOMAIN, asset_id)})
        if device and hasattr(device, "labels"):
            labels.update(str(label) for label in (getattr(device, "labels") or []) if label)

        entity_registry = er.async_get(self.hass)
        tracked_entities = (
            ("sensor", f"{DOMAIN}_{asset_id}"),
            ("binary_sensor", f"{DOMAIN}_{asset_id}_at_risk"),
        )
        for platform, unique_id in tracked_entities:
            entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)
            if not entity_id:
                continue
            entry = entity_registry.async_get(entity_id)
            if entry and hasattr(entry, "labels"):
                labels.update(str(label) for label in (getattr(entry, "labels") or []) if label)

        return sorted(labels)
    @property
    def room_environment_cache(self) -> dict[str | None, dict[str, Any]]:
        """Return the latest per-room environment cache."""
        return self._room_environment_cache
    @property
    def projection_index(self) -> dict[str, AssetProjection]:
        """Return the current in-memory asset projection index."""
        return self._projection_index
    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Run a full refresh cycle.
        Refresh cycle:
        1. Normalize store structure
        2. Group assets by room
        3. Build one room environment snapshot per room
        4. Evaluate all assets
        5. Generate advisory output
        6. Apply runtime persistence side effects
        7. Save store if changed
        8. Rebuild projection cache
        9. Notify subscribers
        """
        try:
            self._ensure_store_loaded_and_normalized()
            cycle_timestamp = self._utcnow_iso()
            assets = self.store.assets
            room_assets = self._group_assets_by_room(assets)
            room_environment_cache, room_health_changed = await self._async_build_room_environment_cache(
                room_assets,
                cycle_timestamp,
            )
            changed = room_health_changed
            projection_payload: dict[str, dict[str, Any]] = {}
            projection_index: dict[str, AssetProjection] = {}
            for asset_id, asset in assets.items():
                linked_profile = None
                self._ensure_asset_structure(asset)
                room_area_id = self._resolve_runtime_area_id(asset_id)
                labels = self._get_registry_labels(asset_id)
                room_environment = room_environment_cache.get(
                    room_area_id,
                    self._empty_room_environment(room_area_id, cycle_timestamp),
                )
                # ---------------------------------------------------------
                # Phase 4G — Resolve debounce policy (runtime)
                # ---------------------------------------------------------
                resolved_debounce = self._resolve_debounce_policy(asset, labels)
                requirements = asset.get("environment_requirements")
                if not isinstance(requirements, dict):
                    requirements = {}
                    asset["environment_requirements"] = requirements
                requirements["debounce"] = resolved_debounce
                limits_configured = self._has_configured_environment_limits(asset)
                if limits_configured:
                    runtime_asset = dict(asset)
                    runtime_asset["labels"] = labels
                    evaluation = evaluate_asset_environment(runtime_asset, room_environment)
                    if not isinstance(evaluation, dict):
                        raise UpdateFailed(
                            f"evaluate_asset_environment returned non-dict for asset '{asset_id}'"
                        )
                    advisory = generate_asset_advisory(evaluation)
                    evaluation["advisories"] = advisory.get("advisories", [])
                    evaluation["primary_advisory"] = advisory.get("primary_advisory")
                else:
                    evaluation = {
                        "risk_state": "UNCONFIGURED",
                        "candidate_state": "UNCONFIGURED",
                        "reasons": ["No environmental limits configured"],
                        "pending_red_since": None,
                        "debounce_action": None,
                        "environment_state_since": None,
                        "last_event": None,
                        "advisories": [],
                        "primary_advisory": None,
                        "exposure_risk": "NONE",
                        "spatial_context": {},
                    }
                # Attach profile reference (lightweight, no full copy)

                # ---------------------------------------------------------
                # Phase 4H — Advisory ↔ Profile Linking
                # ---------------------------------------------------------
                environment_profile = asset.get("environment_profile", {})
                if isinstance(environment_profile, dict):
                    baseline = environment_profile.get("baseline", {})
                else:
                    baseline = {}
                linked_profile = {
                    "observation_count": baseline.get("observation_count"),
                    "observation_start": baseline.get("observation_start"),
                    "observation_end": baseline.get("observation_end"),
                    "confidence": baseline.get("confidence"),
                }
                # ---------------------------------------------------------
                # Phase 4E — Measurement Session Tracking
                # ---------------------------------------------------------
                measurement_changed = self._update_measurement_tracking(
                    asset_id=asset_id,
                    asset=asset,
                    room_environment=room_environment,
                    cycle_timestamp=cycle_timestamp,
                )
                changed = changed or measurement_changed
                asset_changed, projection = self._apply_runtime_side_effects(
                    asset_id=asset_id,
                    asset=asset,
                    room_area_id=room_area_id,
                    room_environment=room_environment,
                    evaluation=evaluation,
                    cycle_timestamp=cycle_timestamp,
                )
                changed = changed or asset_changed
                has_environment = (
                    room_area_id is not None
                    and isinstance(self.store.get_room(room_area_id), dict)
                )
                projection_payload[asset_id] = {
                    "asset_id": projection.asset_id,
                    "area_id": projection.room_area_id,
                    "labels": labels,
                    "environment": self.store.get_room(room_area_id) if room_area_id else None,
                    "has_environment": has_environment,
                    "limits_configured": limits_configured,
                    "room_area_id": projection.room_area_id,
                    "room_environment": projection.room_environment,
                    "room_windows": room_environment.get("windows", []),
                    "risk_state": projection.risk_state,
                    "candidate_state": projection.candidate_state,
                    "reasons": projection.reasons,
                    "pending_red_since": projection.pending_red_since,
                    "debounce_action": projection.debounce_action,
                    "environment_state_since": projection.environment_state_since,
                    "last_event": projection.last_event,
                    "advisories": evaluation.get("advisories", []),
                    "primary_advisory": evaluation.get("primary_advisory"),
                    "exposure_risk": evaluation.get("exposure_risk"),
                    "spatial_context": evaluation.get("spatial_context", {}),
                    "resolved_debounce": resolved_debounce,
                }
                projection_index[asset_id] = projection
            if changed:
                await self.store.async_save()
            self._room_environment_cache = room_environment_cache
            self._projection_index = projection_index
            async_dispatcher_send(self.hass, COORDINATOR_SIGNAL)
            return projection_payload
        except Exception as err:
            raise UpdateFailed(f"Coordinator refresh failed: {err}") from err
    async def async_request_refresh_for_asset(self, asset_id: str) -> None:
        """Request a full refresh.
        We deliberately refresh the full coordinator cycle rather than
        evaluating one asset in isolation, so all assets in a room continue
        to share the same snapshot for determinism.
        """
        _LOGGER.debug("Manual refresh requested for asset_id=%s", asset_id)
        await self.async_request_refresh()
    def get_asset_projection(self, asset_id: str) -> dict[str, Any]:
        """Return a lightweight projection dictionary for an asset."""
        return self.data.get(asset_id, {}) if self.data else {}
    def get_asset_record(self, asset_id: str) -> dict[str, Any] | None:
        """Return the underlying asset record from the store."""
        asset = self.store.get(asset_id)
        return asset if isinstance(asset, dict) else None
        
    # ---------------------------------------------------------
    # Phase 6.6 — Document Retrieval (Coordinator Interface)
    # ---------------------------------------------------------
    async def async_get_asset_documents(
        self, asset_id: str
    ):
        """Return all documents for an asset via retrieval service.
        This method:
        - Delegates to DocumentRetrievalService
        - Returns normalized resolution set
        - Never exposes raw store structures
        """
        return await self.document_retrieval.async_get_documents_for_asset(
            asset_id
        )
    async def async_get_asset_document(
        self, asset_id: str, document_id: str
    ):
        """Return a single document for an asset via retrieval service.
        This method:
        - Delegates to DocumentRetrievalService
        - Returns normalized resolution result
        - Safe for missing assets or documents
        """
        return await self.document_retrieval.async_get_document_for_asset(
            asset_id,
            document_id,
        )
    def _ensure_store_loaded_and_normalized(self) -> None:
        """Ensure current store records are normalized before evaluation."""
        if not hasattr(self.store, "assets") or not isinstance(self.store.assets, dict):
            self.store.assets = {}
        if not hasattr(self.store, "rooms") or not isinstance(self.store.rooms, dict):
            self.store.rooms = {}
        for asset_id, asset in list(self.store.assets.items()):
            if not isinstance(asset, dict):
                self.store.assets[asset_id] = {}
                asset = self.store.assets[asset_id]
            self._ensure_asset_structure(asset)
        for area_id, room in list(self.store.rooms.items()):
            if not isinstance(room, dict):
                self.store.rooms[area_id] = {}
                room = self.store.rooms[area_id]
            self._ensure_room_structure(room)
    def _ensure_asset_structure(self, asset: dict[str, Any]) -> None:
        """Ensure required store fields exist on an asset.
        Coordinator fallback defaults must align to the canonical environment model.
        No legacy environment requirement fields are created here.
        """
        ensure = getattr(self.store, "_ensure_asset_structure", None)
        if callable(ensure):
            ensure(asset)
            return
        # -----------------------------------------------------
        # General asset structure
        # -----------------------------------------------------
        asset.setdefault("audit_log", [])
        asset.setdefault("documents", [])
        asset.setdefault("physical_documents", [])
        asset.setdefault("trackers", [])
        asset.setdefault("links", {})
        asset.setdefault("loans", [])
        # -----------------------------------------------------
        # Placement
        # -----------------------------------------------------
        placement = asset.get("placement")
        if not isinstance(placement, dict):
            placement = {}
        placement.setdefault("near_window", False)
        placement.setdefault("exposure_zone", None)
        placement.setdefault("facing_direction", None)
        placement.pop("area_id", None)
        asset["placement"] = placement
        # -----------------------------------------------------
        # Enclosure
        # -----------------------------------------------------
        enclosure = asset.get("enclosure")
        if not isinstance(enclosure, dict):
            enclosure = {}
        enclosure.setdefault("type", None)
        asset["enclosure"] = enclosure
        # -----------------------------------------------------
        # Canonical environment requirements
        # -----------------------------------------------------
        requirements = asset.get("environment_requirements")
        if not isinstance(requirements, dict):
            requirements = {}
        def _ensure_signal_range(section_name: str, signal_name: str) -> None:
            section = requirements.get(section_name)
            if not isinstance(section, dict):
                section = {}
            signal = section.get(signal_name)
            if not isinstance(signal, dict):
                signal = {}
            signal.setdefault("min", None)
            signal.setdefault("max", None)
            section[signal_name] = signal
            requirements[section_name] = section
        # Canonical environmental sections/signals
        canonical_signals = {
            "climate": ["temperature", "humidity", "dew_point"],
            "light": ["lux", "uv"],
            "air_quality": ["voc", "formaldehyde", "ozone", "no2"],
            "particulates": ["pm2_5", "pm10"],
            "biological": ["mold_index"],
            "safety": ["leak"],
            "structural": ["pressure", "vibration"],
            "context": ["noise"],
            "control_context": ["co2"],
            "external_environment": ["sun", "uv_index", "forecast"],
        }
        for section_name, signals in canonical_signals.items():
            for signal_name in signals:
                _ensure_signal_range(section_name, signal_name)
        # Keep debounce as non-environment runtime policy metadata
        debounce = requirements.get("debounce")
        if not isinstance(debounce, dict):
            debounce = {}
        debounce.setdefault("red_transition_seconds", None)
        debounce.setdefault("recovery_seconds", None)
        requirements["debounce"] = debounce
        asset["environment_requirements"] = requirements
        # -----------------------------------------------------
        # Custody / events
        # -----------------------------------------------------
        asset.setdefault("custody", {})
        asset.setdefault("custody_events", [])
        asset.setdefault("environment_events", [])
        asset.setdefault("advisory_events", [])
        asset.setdefault("environment_event_count", 0)
        asset.setdefault("last_environment_event", None)
        asset.setdefault("last_room_environment_snapshot", None)
        # -----------------------------------------------------
        # Environment profile
        # -----------------------------------------------------
        profile = asset.get("environment_profile")
        if not isinstance(profile, dict):
            profile = {}
        baseline = profile.get("baseline")
        if not isinstance(baseline, dict):
            baseline = {}
        baseline.setdefault("avg_temperature", None)
        baseline.setdefault("avg_humidity", None)
        baseline.setdefault("avg_lux", None)
        baseline.setdefault("peak_lux", None)
        baseline.setdefault("avg_uv", None)
        baseline.setdefault("peak_uv", None)
        baseline.setdefault("exposure_window", None)
        baseline.setdefault("observation_period", None)
        baseline.setdefault("observation_count", 0)
        baseline.setdefault("observation_start", None)
        baseline.setdefault("observation_end", None)
        baseline.setdefault("sensors_used", [])
        baseline.setdefault("confidence", None)
        profile["baseline"] = baseline
        asset["environment_profile"] = profile
        # -----------------------------------------------------
        # Active measurement
        # -----------------------------------------------------
        active_measurement = asset.get("active_measurement")
        if not isinstance(active_measurement, dict):
            active_measurement = {}
        active_measurement.setdefault("sensors", [])
        active_measurement.setdefault("started_at", None)
        active_measurement.setdefault("duration_days", None)
        active_measurement.setdefault("observations", [])
        active_measurement.setdefault("update_count", 0)
        active_measurement.setdefault("last_observation_at", None)
        active_measurement.setdefault("started_by", None)
        active_measurement.setdefault("stop_requested_by", None)
        active_measurement.setdefault("initial_room_environment", {})
        active_measurement.setdefault("stop_requested", False)
        active_measurement.setdefault("completed", False)
        asset["active_measurement"] = active_measurement
        asset.setdefault("measurement_sessions", [])
        # -----------------------------------------------------
        # Runtime environment state
        # -----------------------------------------------------
        asset.setdefault("environment_risk_state", None)
        asset.setdefault("last_environment_risk_state", None)
        asset.setdefault("candidate_environment_risk_state", None)
        asset.setdefault("environment_pending_red_since", None)
        asset.setdefault("environment_risk_debounce_action", None)
        asset.setdefault("environment_reasons", [])
        asset.setdefault("environment_state_since", None)
    # ---------------------------------------------------------
    # Phase 4G — Debounce Policy Resolution
    # ---------------------------------------------------------
    def _resolve_debounce_policy(
        self,
        asset: dict[str, Any],
        labels: list[str],
    ) -> dict[str, Any]:
        """Resolve debounce policy for an asset with explainability sources."""
        # -----------------------------------------------------
        # System defaults (final fallback)
        # -----------------------------------------------------
        system_defaults = self.store.system_defaults or {}
        default_debounce = (
            system_defaults.get("debounce", {})
            if isinstance(system_defaults, dict)
            else {}
        )
        resolved = {
            "red_transition_seconds": default_debounce.get("red_transition_seconds"),
            "recovery_seconds": default_debounce.get("recovery_seconds"),
        }
        source = {
            "red_transition_seconds": "system_default",
            "recovery_seconds": "system_default",
        }
        # -----------------------------------------------------
        # Label profiles
        # -----------------------------------------------------
        if isinstance(labels, list) and labels:
            for label in labels:
                profile = self.store.label_profiles.get(label)
                if not isinstance(profile, dict):
                    continue
                debounce_profile = profile.get("debounce")
                if not isinstance(debounce_profile, dict):
                    continue
                if debounce_profile.get("red_transition_seconds") is not None:
                    resolved["red_transition_seconds"] = debounce_profile.get("red_transition_seconds")
                    source["red_transition_seconds"] = f"label:{label}"
                if debounce_profile.get("recovery_seconds") is not None:
                    resolved["recovery_seconds"] = debounce_profile.get("recovery_seconds")
                    source["recovery_seconds"] = f"label:{label}"
        # -----------------------------------------------------
        # Asset override (highest priority)
        # -----------------------------------------------------
        requirements = asset.get("environment_requirements", {})
        if isinstance(requirements, dict):
            debounce_override = requirements.get("debounce", {})
            if isinstance(debounce_override, dict):
                if debounce_override.get("red_transition_seconds") is not None:
                    resolved["red_transition_seconds"] = debounce_override.get("red_transition_seconds")
                    source["red_transition_seconds"] = "asset_override"
                if debounce_override.get("recovery_seconds") is not None:
                    resolved["recovery_seconds"] = debounce_override.get("recovery_seconds")
                    source["recovery_seconds"] = "asset_override"
        # -----------------------------------------------------
        # Final structure (with explainability)
        # -----------------------------------------------------
        return {
            "red_transition_seconds": resolved.get("red_transition_seconds"),
            "recovery_seconds": resolved.get("recovery_seconds"),
            "source": source,
        }

    def _has_configured_environment_limits(self, asset: dict[str, Any]) -> bool:
        """Return True when at least one min/max environment limit is configured."""
        requirements = asset.get("environment_requirements")
        if not isinstance(requirements, dict):
            return False

        for section_name, section_value in requirements.items():
            if section_name == "debounce":
                continue
            if not isinstance(section_value, dict):
                continue

            for signal_value in section_value.values():
                if not isinstance(signal_value, dict):
                    continue
                if signal_value.get("min") is not None or signal_value.get("max") is not None:
                    return True

        return False
    def _ensure_room_structure(self, room: dict[str, Any]) -> None:
        """Ensure required room fields exist."""
        ensure = getattr(self.store, "_ensure_room_structure", None)
        if callable(ensure):
            ensure(room)
            return
        room.setdefault("environment_config", {})
        room.setdefault("windows", [])
        room.setdefault("room_events", [])
        room.setdefault("human_health", {})
        room.setdefault("human_health_profile", {})
    def _group_assets_by_room(
        self,
        assets: dict[str, dict[str, Any]],
    ) -> dict[str | None, list[dict[str, Any]]]:
        """Group assets by room/area id using runtime HA device area as source of truth."""
        grouped: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        for asset_id, asset in assets.items():
            grouped[self._resolve_runtime_area_id(asset_id)].append(asset)
        return dict(grouped)

    async def _async_build_room_environment_cache(
        self,
        room_assets: dict[str | None, list[dict[str, Any]]],
        cycle_timestamp: str,
    ) -> tuple[dict[str | None, dict[str, Any]], bool]:
        """Build one room environment snapshot per room."""
        cache: dict[str | None, dict[str, Any]] = {}
        room_health_changed = False
        all_room_ids = set(room_assets.keys()) | set(self.store.rooms.keys())
        for room_area_id in all_room_ids:
            if room_area_id is None:
                cache[room_area_id] = self._empty_room_environment(None, cycle_timestamp)
                continue
            try:
                env = await get_room_environment(self.hass, self.store, room_area_id)
                if not isinstance(env, dict):
                    env = self._empty_room_environment(room_area_id, cycle_timestamp)
            except Exception:
                _LOGGER.exception(
                    "Failed to build room environment for room_area_id=%s; using empty snapshot",
                    room_area_id,
                )
                env = self._empty_room_environment(room_area_id, cycle_timestamp)
            room_record = self.store.get_room(room_area_id) or {}
            if not isinstance(room_record, dict):
                room_record = {}
            env["windows"] = room_record.get("windows", [])
            if "external_environment" not in env:
                env["external_environment"] = {}
            normalized = self._normalize_room_environment(
                room_area_id=room_area_id,
                env=env,
                cycle_timestamp=cycle_timestamp,
            )

            existing_health = room_record.get("human_health")
            if not isinstance(existing_health, dict):
                existing_health = {}

            room_profile = self._resolve_room_human_health_profile(room_record)
            human_health = evaluate_room_human_health(
                room_environment=normalized,
                profile=room_profile,
                previous_state=existing_health.get("state"),
                previous_status_since=existing_health.get("status_since"),
            )
            normalized["human_health"] = human_health

            if room_record.get("human_health") != human_health:
                room_record["human_health"] = human_health
                self.store.rooms[room_area_id] = room_record
                room_health_changed = True

            cache[room_area_id] = normalized
        return cache, room_health_changed

    def _resolve_room_human_health_profile(self, room_record: dict[str, Any]) -> dict[str, Any]:
        """Resolve room-specific human health profile with system-default fallback."""
        system_defaults = self.store.system_defaults if isinstance(self.store.system_defaults, dict) else {}
        system_profile = system_defaults.get("human_health_profile")
        if not isinstance(system_profile, dict):
            system_profile = {}

        room_profile = room_record.get("human_health_profile")
        if not isinstance(room_profile, dict):
            room_profile = {}

        merged = dict(system_profile)
        for key, value in room_profile.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged.get(key) or {})
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value

        return merged
    def _normalize_room_environment(
        self,
        *,
        room_area_id: str | None,
        env: dict[str, Any],
        cycle_timestamp: str,
    ) -> dict[str, Any]:
        """Normalize room environment to the canonical runtime model.
        This coordinator does not support legacy room environment fields.
        It guarantees a complete canonical section/signal structure.
        """
        source_status = env.get("source_status")
        if not isinstance(source_status, dict):
            source_status = {
                "configured_signals": 0,
                "signals_with_data": 0,
                "signals_missing": 0,
                "details": {},
            }
        windows = env.get("windows")
        if not isinstance(windows, list):
            windows = []
        def _section(name: str) -> dict[str, Any]:
            value = env.get(name)
            return value if isinstance(value, dict) else {}
        def _signal(section: dict[str, Any], key: str) -> Any:
            return section.get(key)
        climate = _section("climate")
        light = _section("light")
        air_quality = _section("air_quality")
        particulates = _section("particulates")
        biological = _section("biological")
        safety = _section("safety")
        structural = _section("structural")
        context = _section("context")
        control_context = _section("control_context")
        external_environment = _section("external_environment")
        return {
            "area_id": env.get("area_id", room_area_id),
            "configured": bool(env.get("configured", False)),
            "climate": {
                "temperature": _signal(climate, "temperature"),
                "humidity": _signal(climate, "humidity"),
                "dew_point": _signal(climate, "dew_point"),
            },
            "light": {
                "lux": _signal(light, "lux"),
                "uv": _signal(light, "uv"),
            },
            "air_quality": {
                "voc": _signal(air_quality, "voc"),
                "formaldehyde": _signal(air_quality, "formaldehyde"),
                "ozone": _signal(air_quality, "ozone"),
                "no2": _signal(air_quality, "no2"),
            },
            "particulates": {
                "pm2_5": _signal(particulates, "pm2_5"),
                "pm10": _signal(particulates, "pm10"),
            },
            "biological": {
                "mold_index": _signal(biological, "mold_index"),
            },
            "safety": {
                "leak": _signal(safety, "leak"),
            },
            "structural": {
                "pressure": _signal(structural, "pressure"),
                "vibration": _signal(structural, "vibration"),
            },
            "context": {
                "noise": _signal(context, "noise"),
            },
            "control_context": {
                "co2": _signal(control_context, "co2"),
            },
            "external_environment": {
                "sun": _signal(external_environment, "sun"),
                "uv_index": _signal(external_environment, "uv_index"),
                "forecast": _signal(external_environment, "forecast"),
            },
            # Spatial/runtime metadata
            "windows": windows,
            "confidence": env.get("confidence"),
            "last_updated": cycle_timestamp,
            "source_status": source_status,
            "human_health": env.get("human_health") if isinstance(env.get("human_health"), dict) else {},
        }
    # ---------------------------------------------------------
    # Phase 4E — Measurement Tracking Logic
    # ---------------------------------------------------------
    def _update_measurement_tracking(
        self,
        *,
        asset_id: str,
        asset: dict[str, Any],
        room_environment: dict[str, Any],
        cycle_timestamp: str,
    ) -> bool:
        """Track active measurement session and collect canonical observations."""
        measurement_changed = False
        measurement = asset.get("active_measurement")
        if not isinstance(measurement, dict):
            return measurement_changed
        if not measurement.get("started_at") or measurement.get("completed"):
            return measurement_changed
        # Initialize runtime cache if needed
        runtime = self._active_measurements.setdefault(
            asset_id,
            {
                "started_at": measurement.get("started_at"),
                "samples": [],
            },
        )
        room_snapshot = self._snapshot_measurement_room_environment(room_environment)
        asset_sensor_snapshot = self._collect_asset_sensor_snapshot(asset)
        observation = {
            "timestamp": cycle_timestamp,
            "room_environment": room_snapshot,
            "asset_sensors": asset_sensor_snapshot,
        }
        runtime["samples"].append(observation)
        measurement.setdefault("observations", []).append(observation)
        measurement["update_count"] = int(measurement.get("update_count") or 0) + 1
        measurement["last_observation_at"] = cycle_timestamp
        measurement_changed = True
        if measurement.get("stop_requested") and not measurement.get("completed"):
            profile = self._finalize_measurement_profile(
                asset_id=asset_id,
                asset=asset,
                room_environment=room_environment,
            )
            room_area_id = self._resolve_runtime_area_id(asset_id)
            asset["environment_profile"] = profile
            sessions = asset.setdefault("measurement_sessions", [])
            sessions.append(
                {
                    "started_at": measurement.get("started_at"),
                    "completed_at": cycle_timestamp,
                    "started_by": measurement.get("started_by"),
                    "stop_requested_at": measurement.get("stop_requested_at"),
                    "stop_requested_by": measurement.get("stop_requested_by"),
                    "room_area_id": room_area_id,
                    "observation_count": int(measurement.get("update_count") or 0),
                    "initial_room_environment": measurement.get("initial_room_environment")
                    if isinstance(measurement.get("initial_room_environment"), dict)
                    else {},
                    "profile": profile,
                    "profile_summary": profile.get("baseline", {}),
                }
            )

            audit_log = asset.get("audit_log")
            if not isinstance(audit_log, list):
                audit_log = []
                asset["audit_log"] = audit_log
            audit_log.append(
                {
                    "timestamp": cycle_timestamp,
                    "action": "stop_measurement",
                    "actor": measurement.get("stop_requested_by") or measurement.get("started_by") or "system",
                    "details": {
                        "started_at": measurement.get("started_at"),
                        "completed_at": cycle_timestamp,
                        "room_area_id": room_area_id,
                        "observation_count": int(measurement.get("update_count") or 0),
                        "last_observation_at": measurement.get("last_observation_at"),
                        "initial_room_environment": measurement.get("initial_room_environment")
                        if isinstance(measurement.get("initial_room_environment"), dict)
                        else {},
                        "profile": profile,
                    },
                }
            )
            if len(audit_log) > 200:
                del audit_log[:-200]

            self.hass.bus.async_fire(
                f"{DOMAIN}_environment_profile_completed",
                {
                    "asset_id": asset_id,
                    "occurred_at": cycle_timestamp,
                    "profile": profile,
                },
            )
            measurement["completed"] = True
            measurement["completed_at"] = cycle_timestamp
            asset["active_measurement"] = None
            self._active_measurements.pop(asset_id, None)
            measurement_changed = True
        return measurement_changed
    def _finalize_measurement_profile(
        self,
        *,
        asset_id: str,
        asset: dict,
        room_environment: dict,
    ) -> dict:
        """Compute a baseline environment profile from collected canonical samples."""
        runtime = self._active_measurements.get(asset_id)
        if not isinstance(runtime, dict):
            return {"baseline": {}}
        samples = runtime.get("samples", [])
        if not samples:
            return {"baseline": {}}
        numeric_series: dict[str, list[float]] = {}
        units_by_key: dict[str, str | None] = {}
        last_values_by_key: dict[str, float] = {}

        for sample in samples:
            if not isinstance(sample, dict):
                continue

            room_snapshot = sample.get("room_environment")
            if isinstance(room_snapshot, dict):
                for section, signal_map in room_snapshot.items():
                    if not isinstance(signal_map, dict):
                        continue
                    for signal, raw_value in signal_map.items():
                        numeric_value = self._coerce_numeric(raw_value)
                        if numeric_value is None:
                            continue
                        metric_key = f"room.{section}.{signal}"
                        numeric_series.setdefault(metric_key, []).append(numeric_value)
                        last_values_by_key[metric_key] = numeric_value

            asset_sensor_snapshot = sample.get("asset_sensors")
            if isinstance(asset_sensor_snapshot, dict):
                for entity_id, payload in asset_sensor_snapshot.items():
                    if not isinstance(payload, dict):
                        continue
                    numeric_value = self._coerce_numeric(payload.get("value"))
                    if numeric_value is None:
                        continue
                    metric_key = f"asset.{entity_id}"
                    numeric_series.setdefault(metric_key, []).append(numeric_value)
                    last_values_by_key[metric_key] = numeric_value
                    unit_value = payload.get("unit")
                    if unit_value not in (None, ""):
                        units_by_key[metric_key] = str(unit_value)

        room_units: dict[str, str] = {}
        source_status = room_environment.get("source_status")
        details = source_status.get("details") if isinstance(source_status, dict) else {}
        if isinstance(details, dict):
            for field_path, field_status in details.items():
                if not isinstance(field_status, dict):
                    continue
                entity_id = field_status.get("entity_id")
                if not entity_id:
                    continue
                state_obj = self.hass.states.get(str(entity_id))
                if state_obj:
                    unit = state_obj.attributes.get("unit_of_measurement")
                    if unit not in (None, ""):
                        room_units[str(field_path)] = str(unit)

        metrics: list[dict[str, Any]] = []
        for metric_key, values in sorted(numeric_series.items()):
            if not values:
                continue

            source = "room"
            display_name = metric_key
            unit = units_by_key.get(metric_key)

            if metric_key.startswith("room."):
                suffix = metric_key[len("room."):]
                parts = suffix.split(".")
                if len(parts) >= 2:
                    section = parts[0].replace("_", " ").title()
                    signal = parts[1].replace("_", " ").title()
                    display_name = f"{section} - {signal}"
                unit = unit or room_units.get(suffix)
            elif metric_key.startswith("asset."):
                source = "asset"
                entity_id = metric_key[len("asset."):]
                state_obj = self.hass.states.get(entity_id)
                friendly_name = state_obj.attributes.get("friendly_name") if state_obj else None
                display_name = str(friendly_name or entity_id)
                if unit in (None, "") and state_obj:
                    unit = state_obj.attributes.get("unit_of_measurement")

            metrics.append(
                {
                    "key": metric_key,
                    "source": source,
                    "name": display_name,
                    "unit": unit,
                    "avg": round(sum(values) / len(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                    "last": round(last_values_by_key.get(metric_key, values[-1]), 2),
                    "samples": len(values),
                }
            )

        timestamps = [sample.get("timestamp") for sample in samples if sample.get("timestamp")]

        sensors_used: list[str] = []
        if isinstance(details, dict):
            for field_path, field_status in details.items():
                if not isinstance(field_status, dict):
                    continue
                if not field_status.get("configured"):
                    continue
                entity_id = field_status.get("entity_id")
                if entity_id:
                    sensors_used.append(f"room:{field_path} ({entity_id})")

        links = asset.get("links") if isinstance(asset.get("links"), dict) else {}
        linked_entity_ids = links.get("entity_ids") if isinstance(links, dict) else []
        if isinstance(linked_entity_ids, list):
            for entity_id in linked_entity_ids:
                if isinstance(entity_id, str) and entity_id.strip():
                    sensors_used.append(f"asset:{entity_id.strip()}")

        baseline = {
            "avg_temperature": next((m.get("avg") for m in metrics if m.get("key") == "room.climate.temperature"), None),
            "avg_humidity": next((m.get("avg") for m in metrics if m.get("key") == "room.climate.humidity"), None),
            "avg_lux": next((m.get("avg") for m in metrics if m.get("key") == "room.light.lux"), None),
            "peak_lux": next((m.get("max") for m in metrics if m.get("key") == "room.light.lux"), None),
            "avg_uv": next((m.get("avg") for m in metrics if m.get("key") == "room.light.uv"), None),
            "peak_uv": next((m.get("max") for m in metrics if m.get("key") == "room.light.uv"), None),
            "observation_count": len(samples),
            "observation_start": timestamps[0] if timestamps else None,
            "observation_end": timestamps[-1] if timestamps else None,
            "observation_period": None,
            "sensors_used": sorted(set(sensors_used)),
            "confidence": None,
        }
        if timestamps and len(timestamps) >= 2:
            try:
                start = datetime.fromisoformat(timestamps[0])
                end = datetime.fromisoformat(timestamps[-1])
                baseline["observation_period"] = int((end - start).total_seconds())
            except Exception:
                baseline["observation_period"] = None
        sample_count = len(samples)
        if sample_count >= 500:
            confidence = "HIGH"
        elif sample_count >= 200:
            confidence = "MEDIUM"
        elif sample_count >= 50:
            confidence = "LOW"
        else:
            confidence = None
        baseline["confidence"] = confidence
        exposure_window = self._calculate_exposure_window(
            asset=asset,
            room_environment=room_environment,
        )
        baseline["exposure_window"] = exposure_window
        return {
            "baseline": baseline,
            "metrics": metrics,
        }

    def _snapshot_measurement_room_environment(
        self,
        room_environment: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(room_environment, dict):
            return {}

        sections = (
            "climate",
            "light",
            "air_quality",
            "particulates",
            "biological",
            "safety",
            "structural",
            "context",
            "control_context",
            "external_environment",
        )
        snapshot: dict[str, dict[str, Any]] = {}
        for section in sections:
            value = room_environment.get(section)
            if isinstance(value, dict):
                snapshot[section] = dict(value)
        return snapshot

    def _collect_asset_sensor_snapshot(
        self,
        asset: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        links = asset.get("links") if isinstance(asset.get("links"), dict) else {}
        entity_ids = links.get("entity_ids") if isinstance(links, dict) else []
        if not isinstance(entity_ids, list):
            return {}

        snapshot: dict[str, dict[str, Any]] = {}
        for entity_id in entity_ids:
            if not isinstance(entity_id, str) or not entity_id.strip():
                continue

            normalized_entity_id = entity_id.strip()
            state_obj = self.hass.states.get(normalized_entity_id)
            if state_obj is None:
                continue

            snapshot[normalized_entity_id] = {
                "value": state_obj.state,
                "unit": state_obj.attributes.get("unit_of_measurement"),
                "device_class": state_obj.attributes.get("device_class"),
            }

        return snapshot

    def _coerce_numeric(self, value: Any) -> float | None:
        if value in (None, "", "unknown", "unavailable", "none"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    def _apply_runtime_side_effects(
        self,
        *,
        asset_id: str,
        asset: dict[str, Any],
        room_area_id: str | None,
        room_environment: dict[str, Any],
        evaluation: dict[str, Any],
        cycle_timestamp: str,
    ) -> tuple[bool, AssetProjection]:
        """Apply runtime persistence side effects for a single asset.
        All writes and side effects belong here, not in entities and not in
        evaluation.py.
        """
        changed = False
        previous_risk_state = self._normalize_state(asset.get("last_environment_risk_state"))
        current_stored_pending = asset.get("environment_pending_red_since")
        previous_state_since = asset.get("environment_state_since")
        previous_last_event = asset.get("last_environment_event")
        previous_room_snapshot = (
            asset.get("last_room_environment_snapshot")
            if isinstance(asset.get("last_room_environment_snapshot"), dict)
            else None
        )
        
        risk_state = (
            self._normalize_state(evaluation.get("risk_state"))
            or previous_risk_state
            or "GREEN"
        )
        candidate_state = (
            self._normalize_state(evaluation.get("candidate_state")) or risk_state
        )
        reasons = self._normalize_reasons(evaluation.get("reasons"))
        resolved_debounce = asset.get("environment_requirements", {}).get("debounce")

        exposure_risk = evaluation.get("exposure_risk")
        spatial_context = evaluation.get("spatial_context", {})
        debounce_action = self._normalize_debounce_action(evaluation.get("debounce_action"))
        current_room_snapshot = self._extract_room_environment_snapshot(room_environment)
        room_field_changes = self._build_room_environment_field_changes(
            previous_room_snapshot,
            current_room_snapshot,
        )
        # -----------------------------------------------------
        # Debounce persistence
        # -----------------------------------------------------
        pending_red_since = current_stored_pending
        if debounce_action == "start_red":
            if not current_stored_pending:
                pending_red_since = cycle_timestamp
                asset["environment_pending_red_since"] = pending_red_since
                changed = True
        elif debounce_action == "clear_red_pending":
            if current_stored_pending is not None:
                pending_red_since = None
                asset["environment_pending_red_since"] = None
                changed = True
        else:
            pending_red_since = current_stored_pending
        # -----------------------------------------------------
        # Persist explainability / current projection summary
        # -----------------------------------------------------
        if asset.get("candidate_environment_risk_state") != candidate_state:
            asset["candidate_environment_risk_state"] = candidate_state
            changed = True
        if asset.get("environment_risk_debounce_action") != debounce_action:
            asset["environment_risk_debounce_action"] = debounce_action
            changed = True
        if asset.get("environment_reasons") != reasons:
            asset["environment_reasons"] = reasons
            changed = True
        if asset.get("environment_risk_state") != risk_state:
            asset["environment_risk_state"] = risk_state
            changed = True
        # -----------------------------------------------------
        # Exposure persistence (Phase 4F)
        # -----------------------------------------------------
        if asset.get("exposure_risk") != exposure_risk:
            asset["exposure_risk"] = exposure_risk
            changed = True
        if asset.get("spatial_context") != spatial_context:
            asset["spatial_context"] = spatial_context
            changed = True
        # -----------------------------------------------------
        # Initial state bootstrap (no event on first observation)
        # -----------------------------------------------------
        if previous_risk_state is None:
            asset["last_environment_risk_state"] = risk_state
            if not previous_state_since:
                asset["environment_state_since"] = cycle_timestamp
            asset["last_room_environment_snapshot"] = current_room_snapshot
            changed = True
            projection = AssetProjection(
                asset_id=asset_id,
                room_area_id=room_area_id,
                room_environment=room_environment,
                risk_state=risk_state,
                candidate_state=candidate_state,
                reasons=reasons,
                pending_red_since=pending_red_since,
                debounce_action=debounce_action,
                environment_state_since=asset.get("environment_state_since"),
                last_event=previous_last_event if isinstance(previous_last_event, dict) else None,
                exposure_risk=exposure_risk,
                spatial_context=spatial_context,
                resolved_debounce=resolved_debounce,
                # removed profile_reference
            )
            self._log_projection(
                asset_id=asset_id,
                room_area_id=room_area_id,
                previous_risk_state=previous_risk_state,
                risk_state=risk_state,
                candidate_state=candidate_state,
                debounce_action=debounce_action,
                pending_red_since=pending_red_since,
                reasons=reasons,
            )
            return changed, projection
        # -----------------------------------------------------
        # Effective state transition handling
        # -----------------------------------------------------
        last_event = previous_last_event if isinstance(previous_last_event, dict) else None
        if previous_risk_state != risk_state:
            asset["last_environment_risk_state"] = risk_state
            asset["environment_state_since"] = cycle_timestamp
            changed = True
            profile_reference = (
                asset.get("profile_reference")
                or asset.get("asset_type")
                or "default"
            )            
            event = self._build_environment_event(
                asset_id=asset_id,
                room_area_id=room_area_id,
                prior_state=previous_risk_state,
                new_state=risk_state,
                candidate_state=candidate_state,
                reasons=reasons,
                room_environment=room_environment,
                exposure_risk=exposure_risk,
                spatial_context=spatial_context,
                pending_red_since=pending_red_since,
                debounce_action=debounce_action,
                occurred_at=cycle_timestamp,
                profile_reference=profile_reference,
            )
            if room_field_changes:
                event["changed_fields"] = list(room_field_changes.keys())
                event["field_changes"] = room_field_changes
            # -----------------------------------------------------
            # Phase 4H — Outcome Observation
            # -----------------------------------------------------
            previous_event = previous_last_event if isinstance(previous_last_event, dict) else None
            if previous_event:
                previous_env = previous_event.get("room_environment", {})
                current_env = room_environment
                def _extract_signal(env, path):
                    section, key = path.split(".", 1)
                    return env.get(section, {}).get(key)
                # Simple comparisons (expandable)
                comparison = {
                    "temperature_delta": None,
                    "humidity_delta": None,
                    "lux_delta": None,
                    "uv_delta": None,
                }
                try:
                    prev_temp = _extract_signal(previous_env, "climate.temperature")
                    curr_temp = _extract_signal(current_env, "climate.temperature")
                    if prev_temp is not None and curr_temp is not None:
                        comparison["temperature_delta"] = round(curr_temp - prev_temp, 2)
                    prev_humidity = _extract_signal(previous_env, "climate.humidity")
                    curr_humidity = _extract_signal(current_env, "climate.humidity")
                    if prev_humidity is not None and curr_humidity is not None:
                        comparison["humidity_delta"] = round(curr_humidity - prev_humidity, 2)
                    prev_lux = _extract_signal(previous_env, "light.lux")
                    curr_lux = _extract_signal(current_env, "light.lux")
                    if prev_lux is not None and curr_lux is not None:
                        comparison["lux_delta"] = round(curr_lux - prev_lux, 2)
                    prev_uv = _extract_signal(previous_env, "light.uv")
                    curr_uv = _extract_signal(current_env, "light.uv")
                    if prev_uv is not None and curr_uv is not None:
                        comparison["uv_delta"] = round(curr_uv - prev_uv, 2)
                except Exception:
                    comparison = {}
                event["outcome_comparison"] = comparison

            events = asset.get("environment_events")
            if not isinstance(events, list):
                events = []
            events.append(event)
            max_events = 200
            events = events[-max_events:]
            asset["environment_events"] = events
            asset["last_environment_event"] = event
            asset["environment_event_count"] = len(events)
            asset["last_room_environment_snapshot"] = current_room_snapshot
            changed = True
            last_event = event
        else:
            if not previous_state_since:
                asset["environment_state_since"] = cycle_timestamp
                changed = True

            if room_field_changes:
                events = asset.get("environment_events")
                if not isinstance(events, list):
                    events = []

                change_event = self._build_room_environment_change_event(
                    asset_id=asset_id,
                    room_area_id=room_area_id,
                    risk_state=risk_state,
                    candidate_state=candidate_state,
                    field_changes=room_field_changes,
                    room_environment=room_environment,
                    occurred_at=cycle_timestamp,
                )
                events.append(change_event)
                max_events = 200
                events = events[-max_events:]
                asset["environment_events"] = events
                asset["last_environment_event"] = change_event
                asset["environment_event_count"] = len(events)
                asset["last_room_environment_snapshot"] = current_room_snapshot
                changed = True
                last_event = change_event
        projection = AssetProjection(
            asset_id=asset_id,
            room_area_id=room_area_id,
            room_environment=room_environment,
            risk_state=risk_state,
            candidate_state=candidate_state,
            reasons=reasons,
            pending_red_since=pending_red_since,
            debounce_action=debounce_action,
            environment_state_since=asset.get("environment_state_since"),
            last_event=last_event,
            exposure_risk=exposure_risk,
            spatial_context=spatial_context,
            resolved_debounce=resolved_debounce,
        )
        self._log_projection(
            asset_id=asset_id,
            room_area_id=room_area_id,
            previous_risk_state=previous_risk_state,
            risk_state=risk_state,
            candidate_state=candidate_state,
            debounce_action=debounce_action,
            pending_red_since=pending_red_since,
            reasons=reasons,
        )
        return changed, projection

    def _extract_room_environment_snapshot(self, room_environment: dict[str, Any]) -> dict[str, Any]:
        """Extract stable room metric snapshot used for change detection."""
        if not isinstance(room_environment, dict):
            return {}

        signals = {
            "climate": ["temperature", "humidity", "dew_point"],
            "light": ["lux", "uv"],
            "air_quality": ["voc", "formaldehyde", "ozone", "no2"],
            "particulates": ["pm2_5", "pm10"],
            "biological": ["mold_index"],
            "safety": ["leak"],
            "structural": ["pressure", "vibration"],
            "context": ["noise"],
            "control_context": ["co2"],
        }

        snapshot: dict[str, Any] = {}
        for section, keys in signals.items():
            section_data = room_environment.get(section)
            if not isinstance(section_data, dict):
                section_data = {}
            snapshot[section] = {key: section_data.get(key) for key in keys}

        return snapshot

    def _flatten_room_snapshot(self, value: Any, prefix: str = "") -> dict[str, Any]:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, child in value.items():
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                out.update(self._flatten_room_snapshot(child, child_prefix))
            return out
        return {prefix: value}

    def _build_room_environment_field_changes(
        self,
        previous_snapshot: dict[str, Any] | None,
        current_snapshot: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        if not previous_snapshot or not isinstance(previous_snapshot, dict):
            return {}

        before_flat = self._flatten_room_snapshot(previous_snapshot)
        after_flat = self._flatten_room_snapshot(current_snapshot)
        all_paths = sorted(set(before_flat.keys()) | set(after_flat.keys()))

        changes: dict[str, dict[str, Any]] = {}
        for path in all_paths:
            before = before_flat.get(path)
            after = after_flat.get(path)
            if before == after:
                continue
            changes[path] = {
                "before": before,
                "after": after,
            }

        return changes

    def _build_room_environment_change_event(
        self,
        *,
        asset_id: str,
        room_area_id: str | None,
        risk_state: str,
        candidate_state: str | None,
        field_changes: dict[str, dict[str, Any]],
        room_environment: dict[str, Any],
        occurred_at: str,
    ) -> dict[str, Any]:
        return {
            "type": "room_environment_changed",
            "asset_id": asset_id,
            "occurred_at": occurred_at,
            "risk_state": risk_state,
            "candidate_state": candidate_state,
            "room_area_id": room_area_id,
            "changed_fields": list(field_changes.keys()),
            "field_changes": field_changes,
            "room_environment": self._extract_room_environment_snapshot(room_environment),
            "summary": f"{len(field_changes)} room measurement(s) changed",
        }
    def _build_environment_event(
        self,
        *,
        asset_id: str,
        room_area_id: str | None,
        prior_state: str | None,
        new_state: str,
        candidate_state: str | None,
        reasons: list[str],
        room_environment: dict[str, Any],
        exposure_risk: dict[str, Any] | None,
        spatial_context: dict[str, Any] | None,
        profile_reference: dict[str, Any] | None,
        pending_red_since: str | None,
        debounce_action: str | None,
        occurred_at: str,
    ) -> dict[str, Any]:
        """Build a single immutable canonical environment event record."""
        return {
            "type": "environment_risk_state_changed",
            "asset_id": asset_id,
            "occurred_at": occurred_at,
            "prior_state": prior_state,
            "new_state": new_state,
            "candidate_state": candidate_state,
            "reasons": reasons,
            "room_area_id": room_area_id,
            "room_environment": {
                "climate": room_environment.get(
                    "climate",
                    {
                        "temperature": None,
                        "humidity": None,
                        "dew_point": None,
                    },
                ),
                "light": room_environment.get(
                    "light",
                    {
                        "lux": None,
                        "uv": None,
                    },
                ),
                "air_quality": room_environment.get(
                    "air_quality",
                    {
                        "voc": None,
                        "formaldehyde": None,
                        "ozone": None,
                        "no2": None,
                    },
                ),
                "particulates": room_environment.get(
                    "particulates",
                    {
                        "pm2_5": None,
                        "pm10": None,
                    },
                ),
                "biological": room_environment.get(
                    "biological",
                    {
                        "mold_index": None,
                    },
                ),
                "safety": room_environment.get(
                    "safety",
                    {
                        "leak": None,
                    },
                ),
                "structural": room_environment.get(
                    "structural",
                    {
                        "pressure": None,
                        "vibration": None,
                    },
                ),
                "context": room_environment.get(
                    "context",
                    {
                        "noise": None,
                    },
                ),
                "control_context": room_environment.get(
                    "control_context",
                    {
                        "co2": None,
                    },
                ),
                "external_environment": room_environment.get(
                    "external_environment",
                    {
                        "sun": None,
                        "uv_index": None,
                        "forecast": None,
                    },
                ),
                "confidence": room_environment.get("confidence"),
                "last_updated": room_environment.get("last_updated"),
            },
            "pending_red_since": pending_red_since,
            "debounce_action": debounce_action,
            "exposure_risk": exposure_risk,
            "spatial_context": spatial_context,
            "profile_reference": profile_reference,
        }
    def _calculate_exposure_window(
        self,
        *,
        asset: dict,
        room_environment: dict,
    ) -> dict | None:
        """Derive an interpretable exposure window using placement, windows, and sun."""
        placement = asset.get("placement", {})
        if not isinstance(placement, dict):
            return None
        if not placement.get("near_window"):
            return None
        facing_direction = placement.get("facing_direction")
        if facing_direction in (None, "", "unknown"):
            return None
        room_windows = room_environment.get("windows", [])
        if not isinstance(room_windows, list) or not room_windows:
            return None
        external_environment = room_environment.get("external_environment", {})
        if not isinstance(external_environment, dict):
            return None
        sun = external_environment.get("sun", {})
        if not isinstance(sun, dict):
            return None
        sun_azimuth = sun.get("azimuth")
        sun_elevation = sun.get("elevation")
        if sun_azimuth is None or sun_elevation is None:
            return None
        # No exposure if sun is below horizon
        if sun_elevation <= 0:
            return None
        def _normalize_direction(value: Any) -> str | None:
            if value in (None, "", "unknown"):
                return None
            text = str(value).strip().upper()
            aliases = {
                "NORTH": "N",
                "SOUTH": "S",
                "EAST": "E",
                "WEST": "W",
                "NORTHEAST": "NE",
                "NORTH-EAST": "NE",
                "SOUTHEAST": "SE",
                "SOUTH-EAST": "SE",
                "SOUTHWEST": "SW",
                "SOUTH-WEST": "SW",
                "NORTHWEST": "NW",
                "NORTH-WEST": "NW",
            }
            return aliases.get(text, text)
        normalized_asset_direction = _normalize_direction(facing_direction)
        if normalized_asset_direction is None:
            return None
        normalized_windows = []
        for window in room_windows:
            if isinstance(window, dict):
                normalized_windows.append(
                    {
                        "direction": _normalize_direction(window.get("direction")),
                        "exposure_type": window.get("exposure_type", window.get("type")),
                        "glass": window.get("glass"),
                        "area": window.get("area"),
                    }
                )
        matching_windows = [
            window
            for window in normalized_windows
            if window.get("direction") == normalized_asset_direction
        ]
        if not matching_windows:
            return None
        def _azimuth_matches_direction(azimuth: float, direction: str) -> bool:
            azimuth = azimuth % 360.0
            ranges = {
                "N": [(315.0, 360.0), (0.0, 45.0)],
                "NE": [(22.5, 67.5)],
                "E": [(45.0, 135.0)],
                "SE": [(112.5, 157.5)],
                "S": [(135.0, 225.0)],
                "SW": [(202.5, 247.5)],
                "W": [(225.0, 315.0)],
                "NW": [(292.5, 337.5)],
            }
            for start, end in ranges.get(direction, []):
                if start <= azimuth <= end:
                    return True
            return False
        exposure_active_now = any(
            _azimuth_matches_direction(float(sun_azimuth), window["direction"])
            for window in matching_windows
            if window.get("direction")
        )
        now_utc = datetime.now(timezone.utc)
        exposure_start = None
        exposure_end = None
        for offset_minutes in range(0, 720, 10):
            projected_time = now_utc + timedelta(minutes=offset_minutes)
            projected_azimuth = (float(sun_azimuth) + (offset_minutes * 0.25)) % 360.0
            if any(
                _azimuth_matches_direction(projected_azimuth, window["direction"])
                for window in matching_windows
                if window.get("direction")
            ):
                if exposure_start is None:
                    exposure_start = projected_time
                exposure_end = projected_time
        if exposure_start is None:
            return None
        return {
            "start": exposure_start.isoformat(),
            "end": exposure_end.isoformat(),
            "direction": normalized_asset_direction,
            "active_now": exposure_active_now,
            "matching_window_count": len(matching_windows),
            "confidence": "MEDIUM",
        }
    def _normalize_state(self, value: Any) -> str | None:
        """Normalize environment state values."""
        if value is None:
            return None
        text = str(value).strip().upper()
        if not text:
            return None
        return text
    def _normalize_reasons(self, value: Any) -> list[str]:
        """Normalize reasons into a list of strings."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item not in (None, "")]
        return [str(value)]
    def _normalize_debounce_action(self, value: Any) -> str | None:
        """Normalize debounce action text."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    def _empty_room_environment(
        self,
        room_area_id: str | None = None,
        cycle_timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Return an empty-but-valid canonical room environment snapshot."""
        return {
            "area_id": room_area_id,
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
            "last_updated": cycle_timestamp,
            "source_status": {
                "configured_signals": 0,
                "signals_with_data": 0,
                "signals_missing": 0,
                "details": {},
            },
            "human_health": {
                "profile_name": "baseline_adult",
                "state": "UNKNOWN",
                "confidence": "LOW",
                "status_since": cycle_timestamp,
                "evaluated_at": cycle_timestamp,
                "reasons": [],
                "advisory_state": "UNKNOWN",
                "advisory_confidence": "LOW",
                "advisory_reasons": [],
                "missing_signals": [],
                "observed_signals": 0,
                "total_signals": 0,
                "readings": {},
                "ranges": {},
            },
        }
    def _log_projection(
        self,
        *,
        asset_id: str,
        room_area_id: str | None,
        previous_risk_state: str | None,
        risk_state: str,
        candidate_state: str | None,
        debounce_action: str | None,
        pending_red_since: str | None,
        reasons: list[str],
    ) -> None:
        _LOGGER.debug(
            (
                "Asset evaluated asset_id=%s room_area_id=%s previous_risk_state=%s "
                "risk_state=%s candidate_state=%s debounce_action=%s "
                "pending_red_since=%s reasons=%s"
            ),
            asset_id,
            room_area_id,
            previous_risk_state,
            risk_state,
            candidate_state,
            debounce_action,
            pending_red_since,
            reasons,
        )
    def _utcnow_iso(self) -> str:
        """Return current UTC timestamp as ISO 8601 string."""
        return datetime.now(timezone.utc).isoformat()


