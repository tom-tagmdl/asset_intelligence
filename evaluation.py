from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (CONFIDENCE_GOOD)

# -----------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------

RISK_GREEN = "GREEN"
RISK_AMBER = "AMBER"
RISK_RED = "RED"

DEFAULT_TEMPERATURE_HYSTERESIS = 1.0
DEFAULT_HUMIDITY_HYSTERESIS = 2.0
DEFAULT_LIGHT_HYSTERESIS = 10.0
DEFAULT_RED_DEBOUNCE_MINUTES = 5

# Phase 4C spatial guidance thresholds.
# These are warning / classification thresholds only.
# They do NOT create RED on their own.
DEFAULT_SPATIAL_WINDOW_LIGHT_WARNING_LUX = 300.0
DEFAULT_SPATIAL_EXPOSURE_LOW_LUX = 200.0
DEFAULT_SPATIAL_EXPOSURE_HIGH_LUX = 500.0


# -----------------------------------------------------------
# TIME HELPERS
# -----------------------------------------------------------

def _now_iso_local() -> str:
    return dt_util.now().isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _minutes_elapsed(ts: str | None) -> float | None:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    delta = dt_util.now() - dt
    return delta.total_seconds() / 60.0


# -----------------------------------------------------------
# GENERAL HELPERS
# -----------------------------------------------------------

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float))


def _append_unique(target: List[str], message: str) -> None:
    if message not in target:
        target.append(message)


def _as_float_or_none(value: Any) -> float | None:
    if value in (None, "", "unknown", "unavailable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _range_min_max(value: Any) -> Tuple[float | None, float | None]:
    """Normalize a range-like value into (min, max).

    Accepts:
    - {"min": x, "max": y}
    - [x, y]
    - (x, y)
    """
    if isinstance(value, dict):
        return _as_float_or_none(value.get("min")), _as_float_or_none(value.get("max"))

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return _as_float_or_none(value[0]), _as_float_or_none(value[1])

    return None, None


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


# -----------------------------------------------------------
# PHASE 4C CONTEXT HELPERS
# -----------------------------------------------------------

def _resolve_asset_area_id(asset: Dict[str, Any]) -> str | None:
    """Resolve the asset's room/area using placement-first semantics."""
    placement = _safe_dict(asset.get("placement"))
    placement_area_id = placement.get("area_id")
    if placement_area_id not in (None, "", "unknown"):
        return str(placement_area_id)

    direct_candidates = (
        "room_area_id",
        "area_id",
        "room_id",
        "room",
        "location_area_id",
        "assigned_area_id",
    )
    for key in direct_candidates:
        value = asset.get(key)
        if value not in (None, "", "unknown"):
            return str(value)

    custody = _safe_dict(asset.get("custody"))

    for key in ("area_id", "room_area_id", "location_area_id"):
        value = custody.get(key)
        if value not in (None, "", "unknown"):
            return str(value)

    current = _safe_dict(custody.get("current"))
    for key in ("area_id", "room_area_id", "location_area_id"):
        value = current.get(key)
        if value not in (None, "", "unknown"):
            return str(value)

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


def _normalize_window_entry(window: Any) -> Dict[str, Any] | None:
    if not isinstance(window, dict):
        return None

    return {
        "direction": _normalize_direction(window.get("direction")),
        "exposure_type": window.get("exposure_type", window.get("type")),
        "glass": window.get("glass"),
        "area": window.get("area"),
    }


def _normalize_room_windows(raw_windows: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for window in raw_windows:
        normalized_window = _normalize_window_entry(window)
        if normalized_window is not None:
            normalized.append(normalized_window)

    return normalized


def _azimuth_matches_direction(azimuth: float | None, direction: str | None) -> bool | None:
    if azimuth is None or direction is None:
        return None

    normalized_direction = _normalize_direction(direction)
    if normalized_direction is None:
        return None

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

    direction_ranges = ranges.get(normalized_direction)
    if not direction_ranges:
        return None

    for start, end in direction_ranges:
        if start <= azimuth <= end:
            return True

    return False


def _extract_spatial_context(asset: Dict[str, Any], room_environment: Dict[str, Any]) -> Dict[str, Any]:
    """Return read-only spatial context for explainability and future phases.

    This does not directly create RED risk by itself.
    """
    placement = _safe_dict(asset.get("placement"))

    raw_windows = room_environment.get("windows")
    room_windows = _normalize_room_windows(_safe_list(raw_windows))

    external_environment = _safe_dict(room_environment.get("external_environment"))
    sun = _safe_dict(external_environment.get("sun"))

    sun_azimuth = _as_float_or_none(sun.get("azimuth"))
    sun_elevation = _as_float_or_none(sun.get("elevation"))

    placement_direction = _normalize_direction(placement.get("facing_direction"))
    near_window = _safe_bool(placement.get("near_window"), False)

    if placement_direction:
        matching_windows = [
            window
            for window in room_windows
            if window.get("direction") == placement_direction
        ]
    elif near_window:
        matching_windows = room_windows
    else:
        matching_windows = []

    exposure_window_active: bool | None = None
    if near_window and matching_windows and sun_elevation is not None and sun_elevation > 0:
        directional_matches = []
        for window in matching_windows:
            matches = _azimuth_matches_direction(sun_azimuth, window.get("direction"))
            if matches is True:
                directional_matches.append(True)

        exposure_window_active = any(directional_matches) if directional_matches else False

    return {
        "placement": {
            "area_id": placement.get("area_id"),
            "near_window": near_window,
            "exposure_zone": placement.get("exposure_zone"),
            "facing_direction": placement_direction,
        },
        "room_windows": room_windows,
        "matching_windows": matching_windows,
        "sun": {
            "azimuth": sun_azimuth,
            "elevation": sun_elevation,
        },
        "exposure_window_active": exposure_window_active,
    }


# -----------------------------------------------------------
# ASSET POLICY RESOLUTION (CANONICAL)
# -----------------------------------------------------------

def _resolve_asset_environment_policy(asset: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical environment requirements.

    This refactor intentionally prefers the canonical
    asset["environment_requirements"] structure and does not
    translate legacy flat environment policy shapes.
    """
    requirements = _safe_dict(asset.get("environment_requirements"))
    return requirements if requirements else {}


def _requirement_block(
    asset_env: Dict[str, Any],
    section: str,
    signal: str,
) -> Dict[str, Any]:
    section_cfg = _safe_dict(asset_env.get(section))
    return _safe_dict(section_cfg.get(signal))


def _requirement_min_max(
    asset_env: Dict[str, Any],
    section: str,
    signal: str,
) -> Tuple[float | None, float | None]:
    cfg = _requirement_block(asset_env, section, signal)
    return _as_float_or_none(cfg.get("min")), _as_float_or_none(cfg.get("max"))


def _requirement_max(
    asset_env: Dict[str, Any],
    section: str,
    signal: str,
) -> float | None:
    cfg = _requirement_block(asset_env, section, signal)
    return _as_float_or_none(cfg.get("max"))


# -----------------------------------------------------------
# ROOM ENVIRONMENT ACCESSORS
# -----------------------------------------------------------


def _room_section_value(
    room_env: Dict[str, Any],
    section: str,
    signal: str,
) -> Any:
    section_data = _safe_dict(room_env.get(section))
    return section_data.get(signal)


def _room_temperature(room_env: Dict[str, Any]) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "climate", "temperature"))


def _room_humidity(room_env: Dict[str, Any]) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "climate", "humidity"))


def _room_dew_point(room_env: Dict[str, Any]) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "climate", "dew_point"))


def _room_light_lux(room_env: Dict[str, Any]) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "light", "lux"))


def _room_light_uv(room_env: Dict[str, Any]) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "light", "uv"))


def _room_safety_leak(room_env: Dict[str, Any]) -> bool | None:
    value = _room_section_value(room_env, "safety", "leak")
    if isinstance(value, bool):
        return value
    return None


def _room_air_quality_value(room_env: Dict[str, Any], key: str) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "air_quality", key))


def _room_particulate_value(room_env: Dict[str, Any], key: str) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "particulates", key))


def _room_biological_value(room_env: Dict[str, Any], key: str) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "biological", key))


def _room_structural_value(room_env: Dict[str, Any], key: str) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "structural", key))


def _room_context_value(room_env: Dict[str, Any], key: str) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "context", key))


def _room_control_context_value(room_env: Dict[str, Any], key: str) -> float | None:
    return _as_float_or_none(_room_section_value(room_env, "control_context", key))


# -----------------------------------------------------------
# CONFIG HELPERS
# -----------------------------------------------------------
def _hysteresis_config(asset_env: Dict[str, Any]) -> Dict[str, float]:
    """Optional hysteresis block remains generic and lightweight."""
    cfg = _safe_dict(asset_env.get("hysteresis"))
    return {
        "temperature": _as_float_or_none(cfg.get("temperature")) 
            if _as_float_or_none(cfg.get("temperature")) is not None
            else DEFAULT_TEMPERATURE_HYSTERESIS,

        "humidity": _as_float_or_none(cfg.get("humidity")) 
            if _as_float_or_none(cfg.get("humidity")) is not None
            else DEFAULT_HUMIDITY_HYSTERESIS,

        "light": _as_float_or_none(cfg.get("light")) 
            if _as_float_or_none(cfg.get("light")) is not None
            else DEFAULT_LIGHT_HYSTERESIS,
    }


def _debounce_config(asset_env: Dict[str, Any]) -> Dict[str, float]:
    cfg = _safe_dict(asset_env.get("debounce"))
    return {
        "red_transition_seconds": _as_float_or_none(cfg.get("red_transition_seconds"))
            if _as_float_or_none(cfg.get("red_transition_seconds")) is not None
            else DEFAULT_RED_DEBOUNCE_MINUTES,
    }


def _spatial_warning_threshold(asset_env: Dict[str, Any]) -> float:
    """Return warning-only light threshold for near-window exposure.

    If an asset-specific lux max exists, use 75% of that threshold as the
    early-warning level. Otherwise fall back to a conservative default.
    """
    max_lux = _requirement_max(asset_env, "light", "lux")
    if max_lux is not None:
        return max_lux * 0.75
    return DEFAULT_SPATIAL_WINDOW_LIGHT_WARNING_LUX


def _classify_spatial_exposure(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    spatial_context: Dict[str, Any],
) -> str:
    """Return descriptive exposure classification.

    Descriptive only; does not directly create RED.
    """
    placement = _safe_dict(spatial_context.get("placement"))
    near_window = bool(placement.get("near_window", False))
    if not near_window:
        return "NONE"

    room_lux = _room_light_lux(room_env)
    if room_lux is None:
        return "NONE"

    exposure_window_active = spatial_context.get("exposure_window_active")
    threshold = _spatial_warning_threshold(asset_env)

    high_threshold = max(threshold, DEFAULT_SPATIAL_EXPOSURE_HIGH_LUX)
    low_threshold = min(threshold, DEFAULT_SPATIAL_EXPOSURE_LOW_LUX)

    if exposure_window_active is True:
        if room_lux >= high_threshold:
            return "HIGH"
        if room_lux >= low_threshold:
            return "MODERATE"
        return "LOW"

    if exposure_window_active is None:
        if room_lux >= high_threshold:
            return "MODERATE"
        if room_lux >= low_threshold:
            return "LOW"
        return "NONE"

    # exposure_window_active is False
    if room_lux >= high_threshold:
        return "LOW"

    return "NONE"



# -----------------------------------------------------------
# DIMENSION EVALUATION
# -----------------------------------------------------------

def _evaluate_temperature(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    previous_state: str | None,
    hysteresis: Dict[str, float],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    room_value = _room_temperature(room_env)
    min_v, max_v = _requirement_min_max(asset_env, "climate", "temperature")

    if min_v is None and max_v is None:
        return

    if room_value is None:
        _append_unique(warnings, "No room temperature data available")
        return

    signals.append("climate.temperature")
    buffer = hysteresis["temperature"]

    if previous_state == RISK_RED:
        if _is_number(min_v) and room_value < (min_v + buffer):
            _append_unique(
                violations,
                f"Temperature {room_value} below minimum {min_v} (hysteresis active)",
            )
        if _is_number(max_v) and room_value > (max_v - buffer):
            _append_unique(
                violations,
                f"Temperature {room_value} above maximum {max_v} (hysteresis active)",
            )
        return

    if _is_number(min_v) and room_value < min_v:
        _append_unique(violations, f"Temperature {room_value} below minimum {min_v}")

    if _is_number(max_v) and room_value > max_v:
        _append_unique(violations, f"Temperature {room_value} above maximum {max_v}")


def _evaluate_humidity(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    previous_state: str | None,
    hysteresis: Dict[str, float],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    room_value = _room_humidity(room_env)
    min_v, max_v = _requirement_min_max(asset_env, "climate", "humidity")

    if min_v is None and max_v is None:
        return

    if room_value is None:
        _append_unique(warnings, "No room humidity data available")
        return

    signals.append("climate.humidity")
    buffer = hysteresis["humidity"]

    if previous_state == RISK_RED:
        if _is_number(min_v) and room_value < (min_v + buffer):
            _append_unique(
                violations,
                f"Humidity {room_value} below minimum {min_v} (hysteresis active)",
            )
        if _is_number(max_v) and room_value > (max_v - buffer):
            _append_unique(
                violations,
                f"Humidity {room_value} above maximum {max_v} (hysteresis active)",
            )
        return

    if _is_number(min_v) and room_value < min_v:
        _append_unique(violations, f"Humidity {room_value} below minimum {min_v}")

    if _is_number(max_v) and room_value > max_v:
        _append_unique(violations, f"Humidity {room_value} above maximum {max_v}")


def _evaluate_dew_point(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    room_value = _room_dew_point(room_env)
    max_v = _requirement_max(asset_env, "climate", "dew_point")

    if max_v is None:
        return

    if room_value is None:
        _append_unique(warnings, "No room dew point data available")
        return

    signals.append("climate.dew_point")

    if room_value > max_v:
        _append_unique(violations, f"Dew point {room_value} above maximum {max_v}")


def _evaluate_light_lux(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    previous_state: str | None,
    hysteresis: Dict[str, float],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    room_value = _room_light_lux(room_env)
    max_v = _requirement_max(asset_env, "light", "lux")

    if max_v is None:
        return

    if room_value is None:
        _append_unique(warnings, "No room light data available")
        return

    signals.append("light.lux")
    buffer = hysteresis["light"]

    if previous_state == RISK_RED:
        if room_value > (max_v - buffer):
            _append_unique(
                violations,
                f"Light {room_value} lux above maximum {max_v} (hysteresis active)",
            )
        return

    if room_value > max_v:
        _append_unique(violations, f"Light {room_value} lux above maximum {max_v}")


def _evaluate_uv(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    room_value = _room_light_uv(room_env)
    max_v = _requirement_max(asset_env, "light", "uv")

    if max_v is None:
        return

    if room_value is None:
        _append_unique(warnings, "No room UV data available")
        return

    signals.append("light.uv")

    if room_value > max_v:
        _append_unique(violations, f"UV {room_value} above maximum {max_v}")


def _evaluate_air_quality(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    checks = (
        ("voc", "VOC"),
        ("formaldehyde", "Formaldehyde"),
        ("ozone", "Ozone"),
        ("no2", "NO₂"),
    )

    for key, label in checks:
        max_v = _requirement_max(asset_env, "air_quality", key)
        if max_v is None:
            continue

        room_value = _room_air_quality_value(room_env, key)
        if room_value is None:
            _append_unique(warnings, f"No room {label} data available")
            continue

        signals.append(f"air_quality.{key}")

        if room_value > max_v:
            _append_unique(violations, f"{label} {room_value} above maximum {max_v}")


def _evaluate_particulates(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    checks = (
        ("pm2_5", "PM2.5"),
        ("pm10", "PM10"),
    )

    for key, label in checks:
        max_v = _requirement_max(asset_env, "particulates", key)
        if max_v is None:
            continue

        room_value = _room_particulate_value(room_env, key)
        if room_value is None:
            _append_unique(warnings, f"No room {label} data available")
            continue

        signals.append(f"particulates.{key}")

        if room_value > max_v:
            _append_unique(violations, f"{label} {room_value} above maximum {max_v}")


def _evaluate_biological(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    max_v = _requirement_max(asset_env, "biological", "mold_index")
    if max_v is None:
        return

    room_value = _room_biological_value(room_env, "mold_index")
    if room_value is None:
        _append_unique(warnings, "No room mold index data available")
        return

    signals.append("biological.mold_index")

    if room_value > max_v:
        _append_unique(violations, f"Mold index {room_value} above maximum {max_v}")


def _evaluate_safety(
    room_env: Dict[str, Any],
    violations: List[str],
    signals: List[str],
) -> None:
    leak = _room_safety_leak(room_env)
    if leak is None:
        return

    signals.append("safety.leak")

    if leak is True:
        _append_unique(violations, "Leak detected in room")


def _evaluate_control_context(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    warnings: List[str],
    signals: List[str],
) -> None:
    """Control-context measures create warnings, not hard RED violations."""
    max_v = _requirement_max(asset_env, "control_context", "co2")
    if max_v is None:
        return

    room_value = _room_control_context_value(room_env, "co2")
    if room_value is None:
        _append_unique(warnings, "No room CO2 data available")
        return

    signals.append("control_context.co2")

    if room_value > max_v:
        _append_unique(warnings, f"CO2 {room_value} above preferred maximum {max_v}")


def _evaluate_structural_and_context(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    warnings: List[str],
    signals: List[str],
) -> None:
    """Structural/context signals are warning-oriented for now."""
    pressure_max = _requirement_max(asset_env, "structural", "pressure")
    if pressure_max is not None:
        pressure = _room_structural_value(room_env, "pressure")
        if pressure is None:
            _append_unique(warnings, "No room pressure data available")
        else:
            signals.append("structural.pressure")
            if pressure > pressure_max:
                _append_unique(warnings, f"Pressure {pressure} above preferred maximum {pressure_max}")

    noise_max = _requirement_max(asset_env, "context", "noise")
    if noise_max is not None:
        noise = _room_context_value(room_env, "noise")
        if noise is None:
            _append_unique(warnings, "No room noise data available")
        else:
            signals.append("context.noise")
            if noise > noise_max:
                _append_unique(warnings, f"Noise {noise} above preferred maximum {noise_max}")


def _evaluate_spatial_exposure_warning(
    asset_env: Dict[str, Any],
    room_env: Dict[str, Any],
    spatial_context: Dict[str, Any],
    violations: List[str],
    warnings: List[str],
    signals: List[str],
) -> None:
    """Add a warning-only spatial exposure signal.

    This never creates RED by itself.
    """
    placement = _safe_dict(spatial_context.get("placement"))
    near_window = bool(placement.get("near_window", False))
    if not near_window:
        return

    room_lux = _room_light_lux(room_env)
    if room_lux is None:
        return

    max_lux = _requirement_max(asset_env, "light", "lux")

    # If hard lux rule already applies, standard light evaluator owns it
    if max_lux is not None and room_lux > max_lux:
        return

    exposure_window_active = spatial_context.get("exposure_window_active")
    threshold = _spatial_warning_threshold(asset_env)

    if exposure_window_active is False:
        return

    if room_lux < threshold:
        return

    signals.append("spatial_exposure")

    if exposure_window_active is True:
        _append_unique(
            warnings,
            f"Asset near window with active sunlight exposure at {room_lux} lux",
        )
    else:
        _append_unique(
            warnings,
            f"Asset near window with elevated light exposure at {room_lux} lux",
        )


# -----------------------------------------------------------
# MAIN EVALUATION
# -----------------------------------------------------------

def evaluate_asset_environment(
    asset: Dict[str, Any],
    room_environment: Dict[str, Any],
) -> Dict[str, Any]:
    asset_id = asset.get("asset_id")
    area_id = _resolve_asset_area_id(asset)

    asset_env = _resolve_asset_environment_policy(asset)
    previous_state = asset.get("last_environment_risk_state")
    pending_since = asset.get("environment_pending_red_since")

    room_confidence = room_environment.get("confidence")

    violations: List[str] = []
    warnings: List[str] = []
    signals: List[str] = []

    spatial_context = _extract_spatial_context(asset, room_environment)
    exposure_risk = _classify_spatial_exposure(asset_env, room_environment, spatial_context)

    # -----------------------------------------------------------
    # NO CONFIGURED POLICY
    # -----------------------------------------------------------
    if not asset_env:
        return {
            "asset_id": asset_id,
            "room_area_id": area_id,
            "risk_state": RISK_AMBER,
            "candidate_state": RISK_AMBER,
            "reasons": ["No environment requirements configured"],
            "pending_red_since": pending_since,
            "debounce_action": "none",
            "environment_state_since": asset.get("environment_state_since"),
            "evaluated_at": _now_iso_local(),
            "room_environment": room_environment,
            "spatial_context": spatial_context,
            "exposure_risk": exposure_risk,
            "signals": signals,
        }

    hysteresis = _hysteresis_config(asset_env)
    debounce = _debounce_config(asset_env)

    # -----------------------------------------------------------
    # CORE / PHASE 1
    # -----------------------------------------------------------
    _evaluate_temperature(
        asset_env,
        room_environment,
        previous_state,
        hysteresis,
        violations,
        warnings,
        signals,
    )
    _evaluate_humidity(
        asset_env,
        room_environment,
        previous_state,
        hysteresis,
        violations,
        warnings,
        signals,
    )
    _evaluate_dew_point(
        asset_env,
        room_environment,
        violations,
        warnings,
        signals,
    )
    _evaluate_light_lux(
        asset_env,
        room_environment,
        previous_state,
        hysteresis,
        violations,
        warnings,
        signals,
    )
    _evaluate_uv(
        asset_env,
        room_environment,
        violations,
        warnings,
        signals,
    )
    _evaluate_air_quality(
        asset_env,
        room_environment,
        violations,
        warnings,
        signals,
    )
    _evaluate_particulates(
        asset_env,
        room_environment,
        violations,
        warnings,
        signals,
    )
    _evaluate_biological(
        asset_env,
        room_environment,
        violations,
        warnings,
        signals,
    )
    _evaluate_safety(
        room_environment,
        violations,
        signals,
    )

    # -----------------------------------------------------------
    # PHASE 2 — CONTEXT / EXPLAINABILITY
    # -----------------------------------------------------------
    _evaluate_control_context(
        asset_env,
        room_environment,
        warnings,
        signals,
    )
    _evaluate_structural_and_context(
        asset_env,
        room_environment,
        warnings,
        signals,
    )

    # -----------------------------------------------------------
    # PHASE 4C — WARNING-ONLY SPATIAL RULE
    # -----------------------------------------------------------
    _evaluate_spatial_exposure_warning(
        asset_env,
        room_environment,
        spatial_context,
        violations,
        warnings,
        signals,
    )

    # -----------------------------------------------------------
    # DETERMINE CANDIDATE STATE
    # -----------------------------------------------------------
    if violations:
        candidate = RISK_RED
    elif warnings or room_confidence != CONFIDENCE_GOOD:
        candidate = RISK_AMBER
        if room_confidence and room_confidence != CONFIDENCE_GOOD:
            _append_unique(warnings, f"Room confidence is {room_confidence}")
    else:
        candidate = RISK_GREEN

    reasons = violations + warnings
    if not reasons:
        reasons.append("Environment is within configured limits")

    effective = candidate
    action = "none"

    # -----------------------------------------------------------
    # RED DEBOUNCE LOGIC
    # -----------------------------------------------------------
    if candidate == RISK_RED:
        wait = debounce["red_transition_seconds"]

        if previous_state == RISK_RED:
            effective = RISK_RED

        elif not pending_since:
            effective = RISK_AMBER
            action = "start_red"

        else:
            elapsed = _minutes_elapsed(pending_since)

            if elapsed is None or elapsed < wait:
                effective = RISK_AMBER
                action = "keep_red_pending"
            else:
                effective = RISK_RED
                action = "clear_red_pending"

    elif pending_since:
        action = "clear_red_pending"

    # -----------------------------------------------------
    # Phase 4F — Exposure Evaluation
    # -----------------------------------------------------
    exposure_result = _evaluate_exposure_risk(
        asset=asset,
        room_environment=room_environment,
    )

    exposure_risk = exposure_result.get("exposure_risk")
    spatial_context = exposure_result.get("spatial_context", {})

    # -----------------------------------------------------
    # Phase 4F — Exposure Overlay Into Core Risk
    # -----------------------------------------------------
    overlay_result = _apply_exposure_to_core_risk(
        asset=asset,
        exposure_risk=exposure_risk,
        current_effective=effective,
        current_candidate=candidate,
        current_reasons=reasons,
        current_action=action,
        current_pending_since=pending_since,
    )

    effective = overlay_result["effective"]
    candidate = overlay_result["candidate"]
    reasons = overlay_result["reasons"]
    action = overlay_result["action"]
    pending_since = overlay_result["pending_since"]

    # -----------------------------------------------------------
    # FINAL PROJECTION OUTPUT
    # -----------------------------------------------------------
    return {
        "asset_id": asset_id,
        "room_area_id": area_id,
        "room_environment": room_environment,
        "risk_state": effective,
        "candidate_state": candidate,
        "reasons": reasons,
        "pending_red_since": pending_since,
        "debounce_action": action,
        "environment_state_since": asset.get("environment_state_since"),
        "evaluated_at": _now_iso_local(),
        "spatial_context": spatial_context,
        "exposure_risk": exposure_risk,
        "signals": signals,
    }

def _evaluate_exposure_risk(
    *,
    asset: dict[str, Any],
    room_environment: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate spatial exposure risk based on:
    - Asset placement
    - Window direction
    - Sun position
    - Light conditions (lux, uv)
    """

    placement = asset.get("placement", {})
    if not isinstance(placement, dict):
        return {"exposure_risk": None, "spatial_context": {}}

    if not placement.get("near_window"):
        return {"exposure_risk": None, "spatial_context": {}}

    facing_direction = placement.get("facing_direction")
    if facing_direction in (None, "", "unknown"):
        return {"exposure_risk": None, "spatial_context": {}}

    windows = room_environment.get("windows", [])
    if not isinstance(windows, list) or not windows:
        return {"exposure_risk": None, "spatial_context": {}}

    external = room_environment.get("external_environment", {})
    sun = external.get("sun", {}) if isinstance(external, dict) else {}

    azimuth = sun.get("azimuth")
    elevation = sun.get("elevation")

    if azimuth is None or elevation is None or elevation <= 0:
        return {
            "exposure_risk": {
                "level": "NONE",
                "reason": "sun_not_visible",
            },
            "spatial_context": {
                "facing_direction": facing_direction,
                "windows_considered": len(windows),
            },
        }

    # Normalize direction
    direction = str(facing_direction).strip().upper()

    # Simple directional match
    def _azimuth_matches(direction: str, azimuth: float) -> bool:
        ranges = {
            "N": [(315, 360), (0, 45)],
            "E": [(45, 135)],
            "S": [(135, 225)],
            "W": [(225, 315)],
        }

        for start, end in ranges.get(direction, []):
            if start <= azimuth <= end:
                return True
        return False

    directional_match = _azimuth_matches(direction, float(azimuth))

    light = room_environment.get("light", {})
    lux = light.get("lux") if isinstance(light, dict) else None
    uv = light.get("uv") if isinstance(light, dict) else None

    level = "LOW"
    reasons: list[str] = []

    if directional_match:
        reasons.append("sun_aligned_with_window")

        if uv and uv > 5:
            level = "HIGH"
            reasons.append("high_uv")
        elif lux and lux > 10000:
            level = "MEDIUM"
            reasons.append("high_lux")
        else:
            level = "LOW"
    else:
        level = "NONE"

    return {
        "exposure_risk": {
            "level": level,
            "reasons": reasons,
            "azimuth": azimuth,
            "elevation": elevation,
        },
        "spatial_context": {
            "facing_direction": direction,
            "directional_match": directional_match,
            "lux": lux,
            "uv": uv,
        },
    }

def _apply_exposure_to_core_risk(
    *,
    asset: dict[str, Any],
    exposure_risk: dict[str, Any] | None,
    current_effective: str | None,
    current_candidate: str | None,
    current_reasons: list[str] | None,
    current_action: str | None,
    current_pending_since: str | None,
) -> dict[str, Any]:
    """Overlay exposure risk onto the core environment risk model.

    Sensitivity-aware rules:
    - VERY_HIGH sensitivity:
        HIGH exposure   -> RED
        MEDIUM exposure -> RED
        LOW exposure    -> YELLOW
    - HIGH sensitivity:
        HIGH exposure   -> RED
        MEDIUM exposure -> YELLOW
    - MODERATE sensitivity:
        HIGH exposure   -> YELLOW
    - LOW sensitivity:
        no exposure-driven escalation

    Existing stronger state always wins.
    RED honors the existing debounce model.
    """

    effective = _normalize_risk_state(current_effective) or "GREEN"
    candidate = _normalize_risk_state(current_candidate) or effective
    reasons = list(current_reasons or [])
    action = current_action
    pending_since = current_pending_since

    if not isinstance(exposure_risk, dict):
        return {
            "effective": effective,
            "candidate": candidate,
            "reasons": reasons,
            "action": action,
            "pending_since": pending_since,
        }

    level = str(exposure_risk.get("level", "")).strip().upper()
    exposure_reasons = exposure_risk.get("reasons", [])
    if not isinstance(exposure_reasons, list):
        exposure_reasons = [str(exposure_reasons)]

    sensitivity = _get_exposure_sensitivity_profile(asset)
    sensitivity_name = sensitivity["name"]

    normalized_exposure_reasons = [
        f"exposure:{str(reason)}"
        for reason in exposure_reasons
        if reason not in (None, "")
    ]

    for reason in normalized_exposure_reasons:
        if reason not in reasons:
            reasons.append(reason)

    sensitivity_reason = f"exposure_sensitivity:{sensitivity_name.lower()}"
    if sensitivity_reason not in reasons:
        reasons.append(sensitivity_reason)

    exposure_candidate = _map_exposure_level_to_candidate_risk(
        exposure_level=level,
        sensitivity_name=sensitivity_name,
    )

    if exposure_candidate is None:
        return {
            "effective": effective,
            "candidate": candidate,
            "reasons": reasons,
            "action": action,
            "pending_since": pending_since,
        }

    # Keep the stronger candidate state
    candidate = _max_risk_state(candidate, exposure_candidate)

    # -----------------------------------------------------
    # RED candidate path (honor debounce)
    # -----------------------------------------------------
    if candidate == "RED":
        debounce = asset.get("environment_requirements", {}).get("debounce", {})
        if not isinstance(debounce, dict):
            debounce = {}

        red_transition_seconds = debounce.get("red_transition_seconds")
        try:
            red_transition_seconds = (
                int(red_transition_seconds)
                if red_transition_seconds is not None
                else None
            )
        except (TypeError, ValueError):
            red_transition_seconds = None

        # Start pending RED if not already pending
        if not pending_since:
            action = "start_red"
            return {
                "effective": effective,
                "candidate": candidate,
                "reasons": reasons,
                "action": action,
                "pending_since": pending_since,
            }

        # If no debounce configured, allow immediate RED when already pending
        if red_transition_seconds in (None, 0):
            effective = "RED"
            action = None
            return {
                "effective": effective,
                "candidate": candidate,
                "reasons": reasons,
                "action": action,
                "pending_since": pending_since,
            }

        elapsed_seconds = _elapsed_seconds_since_iso(pending_since)
        if elapsed_seconds is not None and elapsed_seconds >= red_transition_seconds:
            effective = "RED"
            action = None
        else:
            action = "start_red"

        return {
            "effective": effective,
            "candidate": candidate,
            "reasons": reasons,
            "action": action,
            "pending_since": pending_since,
        }

    # -----------------------------------------------------
    # YELLOW candidate path
    # -----------------------------------------------------
    if candidate == "YELLOW":
        if effective == "GREEN":
            effective = "YELLOW"

        # If we were pending a RED transition, clear it because
        # exposure no longer justifies RED.
        if pending_since:
            action = "clear_red_pending"

        return {
            "effective": effective,
            "candidate": candidate,
            "reasons": reasons,
            "action": action,
            "pending_since": pending_since,
        }

    return {
        "effective": effective,
        "candidate": candidate,
        "reasons": reasons,
        "action": action,
        "pending_since": pending_since,
    }

def _get_exposure_sensitivity_profile(asset: dict[str, Any]) -> dict[str, Any]:
    """Return the exposure sensitivity profile for an asset.

    Resolution order:
    1. labels
    2. asset_type/category/subcategory
    3. classification hints
    4. conservative default

    Profiles:
    - VERY_HIGH: fragile / archival / works on paper / textiles / photographs
    - HIGH: paintings / antiques / wood / instruments / light-sensitive decor
    - MODERATE: electronics / mixed-material household assets
    - LOW: durable metal / stone / ceramic / glass-heavy assets
    """

    tokens = _extract_asset_sensitivity_tokens(asset)

    very_high_tokens = {
        "light_sensitive",
        "uv_sensitive",
        "museum_grade",
        "archival",
        "works_on_paper",
        "paper",
        "document",
        "book",
        "rare_book",
        "manuscript",
        "textile",
        "fabric",
        "photograph",
        "photo",
        "watercolor",
        "drawing",
        "print",
    }

    high_tokens = {
        "painting",
        "art",
        "canvas",
        "antique",
        "wood",
        "wood_finish",
        "musical_instrument",
        "instrument",
        "violin",
        "guitar",
        "piano",
        "organic_material",
        "decorative_finish",
    }

    low_tokens = {
        "metal",
        "stone",
        "ceramic",
        "porcelain",
        "glass",
        "mineral",
    }

    if tokens & very_high_tokens:
        return {"name": "VERY_HIGH"}

    if tokens & high_tokens:
        return {"name": "HIGH"}

    if tokens & low_tokens:
        return {"name": "LOW"}

    return {"name": "MODERATE"}


def _extract_asset_sensitivity_tokens(asset: dict[str, Any]) -> set[str]:
    """Extract normalized classification tokens from an asset without requiring schema changes."""
    tokens: set[str] = set()

    def _add_token(value: Any) -> None:
        if value in (None, ""):
            return

        if isinstance(value, str):
            normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
            if normalized:
                tokens.add(normalized)
            return

        if isinstance(value, list):
            for item in value:
                _add_token(item)
            return

        if isinstance(value, dict):
            for nested_value in value.values():
                _add_token(nested_value)

    _add_token(asset.get("labels"))
    _add_token(asset.get("asset_type"))
    _add_token(asset.get("category"))
    _add_token(asset.get("subcategory"))
    _add_token(asset.get("material"))
    _add_token(asset.get("materials"))
    _add_token(asset.get("classification"))

    return tokens

def _map_exposure_level_to_candidate_risk(
    *,
    exposure_level: str,
    sensitivity_name: str,
) -> str | None:
    """Map exposure level + asset sensitivity to a candidate core risk state."""
    level = str(exposure_level).strip().upper()
    sensitivity = str(sensitivity_name).strip().upper()

    if sensitivity == "VERY_HIGH":
        mapping = {
            "HIGH": "RED",
            "MEDIUM": "RED",
            "LOW": "YELLOW",
            "NONE": None,
        }
        return mapping.get(level)

    if sensitivity == "HIGH":
        mapping = {
            "HIGH": "RED",
            "MEDIUM": "YELLOW",
            "LOW": None,
            "NONE": None,
        }
        return mapping.get(level)

    if sensitivity == "MODERATE":
        mapping = {
            "HIGH": "YELLOW",
            "MEDIUM": None,
            "LOW": None,
            "NONE": None,
        }
        return mapping.get(level)

    if sensitivity == "LOW":
        return None

    return None

def _normalize_risk_state(value: Any) -> str | None:
    """Normalize environment risk state text."""
    if value is None:
        return None

    text = str(value).strip().upper()
    if text not in {"GREEN", "YELLOW", "RED"}:
        return None

    return text


def _max_risk_state(left: str | None, right: str | None) -> str:
    """Return the stronger of two risk states."""
    order = {
        "GREEN": 1,
        "YELLOW": 2,
        "RED": 3,
    }

    left_normalized = _normalize_risk_state(left) or "GREEN"
    right_normalized = _normalize_risk_state(right) or "GREEN"

    if order[right_normalized] > order[left_normalized]:
        return right_normalized

    return left_normalized


def _elapsed_seconds_since_iso(value: str | None) -> int | None:
    """Return elapsed seconds from an ISO timestamp until now."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return int((now - parsed.astimezone(timezone.utc)).total_seconds())
