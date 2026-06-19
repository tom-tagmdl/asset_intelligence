from __future__ import annotations

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN


class AssetEntity(CoordinatorEntity, SensorEntity):
    """Base class for all Asset-backed entities.

    This is the core semantic layer for Asset Intelligence.
    It provides:
      - Coordinator-backed projection access
      - Consistent access to store-backed asset data
      - Lightweight, UI-safe attribute exposure

    IMPORTANT DESIGN PRINCIPLES:
      - No evaluation logic here
      - No I/O here
      - No store mutation here
      - Coordinator is the single source of truth for runtime state
    """

    _attr_should_poll = False  # event-driven

    def __init__(self, coordinator, store, asset_id: str, asset: Dict[str, Any]) -> None:
        super().__init__(coordinator)

        self._store = store
        self._asset_id = asset_id
        self._asset = dict(asset)

        self._attr_unique_id = f"{DOMAIN}_{asset_id}"
        self._attr_name = asset.get("name", asset_id)

    # ---------------------------------------------------------
    # STORE ACCESS (system of record)
    # ---------------------------------------------------------
    @property
    def asset(self) -> Dict[str, Any]:
        """Return latest asset state from store (system of record)."""
        stored = self._store.get(self._asset_id)
        if isinstance(stored, dict):
            return stored
        return self._asset

    def update_from_store(self, asset: Dict[str, Any]) -> None:
        """Update cached copy from store."""
        self._asset = dict(asset)
        self._attr_name = asset.get("name", self._asset_id)

    # ---------------------------------------------------------
    # COORDINATOR PROJECTION ACCESS (runtime truth)
    # ---------------------------------------------------------
    @property
    def projection(self) -> Dict[str, Any]:
        """Return coordinator-computed projection for this asset."""
        data = self.coordinator.data or {}
        projection = data.get(self._asset_id)

        if isinstance(projection, dict):
            return projection

        # Safe fallback (never evaluate here)
        area_id = self.asset.get("area_id")

        return {
            "asset_id": self._asset_id,
            "room_area_id": area_id,
            "room_environment": {
                "area_id": area_id,
                "configured": False,
                "temperature": None,
                "humidity": None,
                "light": None,
                "leak": None,
                "air_quality": {"co2": None, "voc": None, "pm25": None},
                "confidence": "STALE",
                "last_updated": None,
                "source_status": {},
            },
            "risk_state": "AMBER",
            "candidate_state": "AMBER",
            "reasons": ["Asset is not assigned to a room"] if not area_id else [],
            "pending_red_since": None,
            "debounce_action": None,
            "environment_state_since": None,
            "last_event": None,
        }

    # ---------------------------------------------------------
    # COMMON DERIVED HELPERS
    # ---------------------------------------------------------
    @property
    def room_environment(self) -> Dict[str, Any]:
        """Return normalized room environment projection."""
        projection = self.projection
        env = projection.get("room_environment")

        if isinstance(env, dict):
            base = {
                "area_id": projection.get("room_area_id") or self.asset.get("area_id"),
                "configured": False,
                "temperature": None,
                "humidity": None,
                "light": None,
                "leak": None,
                "air_quality": {"co2": None, "voc": None, "pm25": None},
                "confidence": "STALE",
                "last_updated": None,
                "source_status": {},
            }
            base.update(env)
            return base

        area_id = self.asset.get("area_id")
        return {
            "area_id": area_id,
            "configured": False,
            "temperature": None,
            "humidity": None,
            "light": None,
            "leak": None,
            "air_quality": {"co2": None, "voc": None, "pm25": None},
            "confidence": "STALE",
            "last_updated": None,
            "source_status": {},
        }

    @property
    def risk_state(self) -> str:
        return self.projection.get("risk_state") or "AMBER"

    @property
    def candidate_state(self) -> str | None:
        return self.projection.get("candidate_state")

    @property
    def reasons(self) -> list[str]:
        reasons = self.projection.get("reasons")
        if isinstance(reasons, list):
            return reasons
        if reasons is None:
            return []
        return [str(reasons)]

    @property
    def debounce_action(self) -> str | None:
        return self.projection.get("debounce_action")

    @property
    def pending_red_since(self) -> str | None:
        return self.projection.get("pending_red_since")

    @property
    def environment_state_since(self) -> str | None:
        return (
            self.projection.get("environment_state_since")
            or self.asset.get("environment_state_since")
        )

    @property
    def last_event(self) -> Dict[str, Any] | None:
        last_event = self.projection.get("last_event")
        if isinstance(last_event, dict):
            return last_event

        stored_event = self.asset.get("last_environment_event")
        if isinstance(stored_event, dict):
            return stored_event

        return None

    # ---------------------------------------------------------
    # BASE ENTITY OUTPUT
    # ---------------------------------------------------------
    @property
    def native_value(self):
        """Default primary state: asset location."""
        return self.asset.get("area_id") or "unassigned"

    @property
    def extra_state_attributes(self):
        """Minimal safe base attributes.

        IMPORTANT:
          - No heavy payloads
          - No history dumps
          - No large arrays
        """
        asset = self.asset

        return {
            "asset_id": asset.get("asset_id"),
            "name": asset.get("name"),
            "area_id": asset.get("area_id"),

            # Coordinator-derived summary
            "environment_risk_state": self.risk_state,
            "candidate_environment_risk_state": self.candidate_state,
            "environment_reasons": self.reasons,
            "environment_action": self.debounce_action,
            "environment_pending_red_since": self.pending_red_since,
            "environment_state_since": self.environment_state_since,

            # System-of-record counters only (not full history)
            "environment_event_count": asset.get("environment_event_count", 0),
            "last_environment_event": self.last_event,

            # Room snapshot summary
            "room_confidence": self.room_environment.get("confidence"),
            "room_last_updated": self.room_environment.get("last_updated"),
        }

