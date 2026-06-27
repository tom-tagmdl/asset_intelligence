from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    BINARY_SIGNALS,
    CONFIDENCE_DEGRADED,
    CONFIDENCE_GOOD,
    CONFIDENCE_PARTIAL,
    CONFIDENCE_STALE,
    DEFAULT_ENVIRONMENT_STRUCTURE,
    ENVIRONMENT_SECTIONS,
    NUMERIC_SIGNALS,
)
from .storage import AssetStore


# -----------------------------------------------------------
# DEFAULT STRUCTURE
# -----------------------------------------------------------

def _empty_environment(area_id: str) -> dict[str, Any]:
    """Return canonical empty room environment structure."""
    env = deepcopy(DEFAULT_ENVIRONMENT_STRUCTURE)
    env.update(
        {
            "area_id": area_id,
            "configured": False,
            "windows": [],
            "confidence": CONFIDENCE_STALE,
            "last_updated": None,
            "source_status": {
                "configured_signals": 0,
                "signals_with_data": 0,
                "signals_missing": 0,
                "details": {},
            },
        }
    )
    return env


# -----------------------------------------------------------
# SAFE VALUE CONVERSION
# -----------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value in (None, "", "unknown", "unavailable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool | None:
    if value in (None, "", "unknown", "unavailable"):
        return None

    normalized = str(value).strip().lower()

    if normalized in ("on", "true", "wet", "detected", "open", "home", "problem", "vibration", "vibrate"):
        return True

    if normalized in ("off", "false", "dry", "clear", "closed", "not_home", "normal", "still"):
        return False

    return None


# -----------------------------------------------------------
# ENTITY READS
# -----------------------------------------------------------

def _read_numeric(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if not state:
        return None
    return _safe_float(state.state)


def _read_binary(hass: HomeAssistant, entity_id: str) -> bool | None:
    state = hass.states.get(entity_id)
    if not state:
        return None
    return _safe_bool(state.state)


def _read_external_environment(hass: HomeAssistant) -> dict[str, Any]:
    """Read external context currently available from core Home Assistant.

    Today this only reads sun position from sun.sun.
    UV index / forecast are left as None until external sources are wired in.
    """
    state = hass.states.get("sun.sun")
    if not state:
        return {
            "sun": {
                "azimuth": None,
                "elevation": None,
            },
            "uv_index": None,
            "forecast": None,
        }

    return {
        "sun": {
            "azimuth": _safe_float(state.attributes.get("azimuth")),
            "elevation": _safe_float(state.attributes.get("elevation")),
        },
        "uv_index": None,
        "forecast": None,
    }


# -----------------------------------------------------------
# AGGREGATION
# -----------------------------------------------------------

def _aggregate_numeric(values: list[float], strategy: str | None) -> float | None:
    if not values:
        return None

    if strategy == "primary":
        return values[0]

    if strategy == "median":
        return float(median(values))

    # default mean
    return float(sum(values) / len(values))


def _aggregate_binary(values: List[bool], strategy: str | None) -> bool | None:
    if not values:
        return None

    # For now binary signals are treated as any_true semantics.
    # This is correct for leak detection and acceptable for vibration.
    return any(v is True for v in values)


# -----------------------------------------------------------
# SIGNAL RESOLUTION
# -----------------------------------------------------------

def _resolve_numeric_signal(
    hass: HomeAssistant,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {
            "value": None,
            "configured": False,
            "has_data": False,
            "entities": [],
            "available_entities": [],
            "missing_entities": [],
            "aggregation": None,
        }

    entity_ids = config.get("source_entities", []) or []
    aggregation = config.get("aggregation", "mean")

    values: list[float] = []
    available: list[str] = []
    missing: list[str] = []

    for eid in entity_ids:
        val = _read_numeric(hass, eid)
        if val is None:
            missing.append(eid)
        else:
            values.append(val)
            available.append(eid)

    return {
        "value": _aggregate_numeric(values, aggregation),
        "configured": bool(entity_ids),
        "has_data": bool(values),
        "entities": entity_ids,
        "available_entities": available,
        "missing_entities": missing,
        "aggregation": aggregation,
    }


def _resolve_binary_signal(
    hass: HomeAssistant,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {
            "value": None,
            "configured": False,
            "has_data": False,
            "entities": [],
            "available_entities": [],
            "missing_entities": [],
            "aggregation": "any_true",
        }

    entity_ids = config.get("source_entities", []) or []

    values: List[bool] = []
    available: list[str] = []
    missing: list[str] = []

    for eid in entity_ids:
        val = _read_binary(hass, eid)
        if val is None:
            missing.append(eid)
        else:
            values.append(val)
            available.append(eid)

    return {
        "value": _aggregate_binary(values, "any_true"),
        "configured": bool(entity_ids),
        "has_data": bool(values),
        "entities": entity_ids,
        "available_entities": available,
        "missing_entities": missing,
        "aggregation": "any_true",
    }


# -----------------------------------------------------------
# DERIVED SIGNALS
# -----------------------------------------------------------

def _calculate_dew_point_f(
    temperature_f: float | None,
    relative_humidity: float | None,
) -> float | None:
    """Approximate dew point in Fahrenheit using the Magnus formula.

    Input:
    - temperature_f: dry bulb in Fahrenheit
    - relative_humidity: RH in percent (0-100)

    Output:
    - dew point in Fahrenheit
    """
    if temperature_f is None or relative_humidity is None:
        return None

    if relative_humidity <= 0 or relative_humidity > 100:
        return None

    # Convert to Celsius for calculation
    temperature_c = (temperature_f - 32.0) * 5.0 / 9.0

    a = 17.625
    b = 243.04

    try:
        gamma = math.log(relative_humidity / 100.0) + (a * temperature_c) / (b + temperature_c)
        dew_point_c = (b * gamma) / (a - gamma)
    except (ValueError, ZeroDivisionError):
        return None

    return round((dew_point_c * 9.0 / 5.0) + 32.0, 2)


def _calculate_mold_index(
    temperature_f: float | None,
    relative_humidity: float | None,
    dew_point_f: float | None,
) -> float | None:
    """Simple preservation-oriented mold risk index (0-100).

    This is intentionally a derived environmental indicator, not a diagnosis.
    It weights RH most heavily, then warmth, then very damp air via dew point.
    """
    if relative_humidity is None:
        return None

    score = 0.0

    # RH contribution
    if relative_humidity < 55:
        score += 0
    elif relative_humidity < 60:
        score += 20
    elif relative_humidity < 65:
        score += 40
    elif relative_humidity < 70:
        score += 60
    elif relative_humidity < 75:
        score += 80
    else:
        score += 100

    # Temperature contribution
    if temperature_f is not None:
        if temperature_f >= 80:
            score += 15
        elif temperature_f >= 72:
            score += 10
        elif temperature_f >= 65:
            score += 5

    # Dew point contribution
    if dew_point_f is not None:
        if dew_point_f >= 65:
            score += 10
        elif dew_point_f >= 60:
            score += 5

    return round(min(score, 100.0), 1)


# -----------------------------------------------------------
# CONFIDENCE MODEL
# -----------------------------------------------------------

def _confidence(configured: int, available: int) -> str:
    if configured == 0:
        return CONFIDENCE_STALE

    if available == 0:
        return CONFIDENCE_STALE

    if available == configured:
        return CONFIDENCE_GOOD

    if available >= (configured / 2):
        return CONFIDENCE_PARTIAL

    return CONFIDENCE_DEGRADED


# -----------------------------------------------------------
# MAIN FUNCTION
# -----------------------------------------------------------

async def get_room_environment(
    hass: HomeAssistant,
    store: AssetStore,
    area_id: str,
) -> dict[str, Any]:
    """Read HA state + room sensor mappings and return canonical room snapshot.

    PURE FUNCTION:
    - Reads Home Assistant state
    - Resolves configured room signals
    - Derives environmental indicators
    - Returns normalized snapshot

    No persistence
    No timestamps
    No evaluation
    """
    config = store.get_room_environment(area_id)

    if not config or not isinstance(config, dict):
        return _empty_environment(area_id)

    environment = _empty_environment(area_id)
    environment["configured"] = True
    environment["windows"] = store.get_room_windows(area_id)
    environment["external_environment"] = _read_external_environment(hass)

    details: dict[str, Any] = {}
    configured_count = 0
    available_count = 0

    # -------------------------------------------------------
    # Resolve all canonical configured signals
    # -------------------------------------------------------
    for section, signal_names in ENVIRONMENT_SECTIONS.items():
        # external_environment is not driven by room config
        if section == "external_environment":
            continue

        section_config = config.get(section)
        if not isinstance(section_config, dict):
            # Leave defaults in place if section is absent
            continue

        # Ensure section exists in the output even if const defaults were altered later
        if section not in environment or not isinstance(environment.get(section), dict):
            environment[section] = {}

        for signal in signal_names:
            # Skip control_context / structural / etc. only if absent in config
            signal_config = section_config.get(signal)

            key = f"{section}.{signal}"

            if signal in BINARY_SIGNALS:
                result = _resolve_binary_signal(hass, signal_config)
            elif signal in NUMERIC_SIGNALS:
                result = _resolve_numeric_signal(hass, signal_config)
            else:
                # Unknown / derived / not directly sourced here
                result = {
                    "value": None,
                    "configured": False,
                    "has_data": False,
                    "entities": [],
                    "available_entities": [],
                    "missing_entities": [],
                    "aggregation": None,
                }

            # Store raw resolved value
            environment[section][signal] = result["value"]

            # Track source status
            details[key] = {
                "configured": result["configured"],
                "has_data": result["has_data"],
                "entities": result["entities"],
                "available_entities": result["available_entities"],
                "missing_entities": result["missing_entities"],
                "aggregation": result["aggregation"],
            }

            if result["configured"]:
                configured_count += 1
                if result["has_data"]:
                    available_count += 1

    # -------------------------------------------------------
    # Derived signals
    # -------------------------------------------------------
    climate = environment.get("climate", {})
    light = environment.get("light", {})
    biological = environment.get("biological", {})

    temp_f = _safe_float(climate.get("temperature"))
    humidity = _safe_float(climate.get("humidity"))

    # Dew point: use configured source if present and resolved; otherwise derive
    dew_point_existing = _safe_float(climate.get("dew_point"))
    dew_point_derived = (
        dew_point_existing
        if dew_point_existing is not None
        else _calculate_dew_point_f(temp_f, humidity)
    )
    climate["dew_point"] = dew_point_derived

    # Mold index: derive unless a future direct source is wired in
    mold_index_existing = _safe_float(biological.get("mold_index"))
    biological["mold_index"] = (
        mold_index_existing
        if mold_index_existing is not None
        else _calculate_mold_index(temp_f, humidity, dew_point_derived)
    )

    # Ensure these updated sections remain attached
    environment["climate"] = climate
    environment["light"] = light
    environment["biological"] = biological

    # -------------------------------------------------------
    # Confidence + source status
    # -------------------------------------------------------
    confidence = _confidence(configured_count, available_count)

    environment["confidence"] = confidence
    environment["last_updated"] = None  # coordinator owns timestamps
    environment["source_status"] = {
        "configured_signals": configured_count,
        "signals_with_data": available_count,
        "signals_missing": configured_count - available_count,
        "details": details,
    }

    # Fetch area image from Home Assistant if available
    try:
        if hasattr(hass, "areas") and hass.areas:
            area = hass.areas.async_get_area(area_id) or hass.areas.get(area_id)
            if area and hasattr(area, "picture"):
                environment["image"] = area.picture
    except Exception:
        pass  # Image fetch failed; proceed without it

    return environment