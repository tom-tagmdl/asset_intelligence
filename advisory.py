from __future__ import annotations

from typing import Any, Iterable


# -----------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------

SEVERITY_INFO = "info"
SEVERITY_LOW = "low"
SEVERITY_MODERATE = "moderate"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"

PRIORITY_ORDER = [
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MODERATE,
    SEVERITY_LOW,
    SEVERITY_INFO,
]


# -----------------------------------------------------------
# ADVISORY PROFILE
# -----------------------------------------------------------
# Canonical signal path -> advisory metadata
#
# Notes:
# - This file only consumes canonical section/signal names.
# - No legacy names are supported.
# - Messages/actions are recommendation-oriented only.
# - Evaluation remains the source of truth for decisioning.
# -----------------------------------------------------------

ADVISORY_PROFILE: Dict[str, Dict[str, Any]] = {
    "climate.temperature": {
        "high": {
            "type": "temperature_high",
            "severity": SEVERITY_MODERATE,
            "message": "Reduce room temperature to protect the asset.",
            "recommended_action": "adjust_thermostat_cool",
        },
        "low": {
            "type": "temperature_low",
            "severity": SEVERITY_MODERATE,
            "message": "Increase room temperature to protect the asset.",
            "recommended_action": "adjust_thermostat_heat",
        },
    },
    "climate.humidity": {
        "high": {
            "type": "humidity_high",
            "severity": SEVERITY_MODERATE,
            "message": "Reduce humidity to lower risk of mold, corrosion, or warping.",
            "recommended_action": "dehumidify",
        },
        "low": {
            "type": "humidity_low",
            "severity": SEVERITY_LOW,
            "message": "Increase humidity to reduce drying or cracking risk.",
            "recommended_action": "humidify",
        },
    },
    "climate.dew_point": {
        "high": {
            "type": "dew_point_high",
            "severity": SEVERITY_MODERATE,
            "message": "Lower condensation risk by reducing dew point conditions.",
            "recommended_action": "reduce_condensation_risk",
        },
        "low": {
            "type": "dew_point_low",
            "severity": SEVERITY_INFO,
            "message": "Dew point is below the preferred range for this asset.",
            "recommended_action": "review_climate_control",
        },
    },
    "light.lux": {
        "high": {
            "type": "lux_high",
            "severity": SEVERITY_MODERATE,
            "message": "Reduce light exposure to protect the asset.",
            "recommended_action": "reduce_lighting",
        },
        "low": {
            "type": "lux_low",
            "severity": SEVERITY_INFO,
            "message": "Light level is below the preferred range for this asset.",
            "recommended_action": "review_lighting",
        },
    },
    "light.uv": {
        "high": {
            "type": "uv_high",
            "severity": SEVERITY_HIGH,
            "message": "Reduce UV exposure immediately to protect the asset.",
            "recommended_action": "block_uv",
        },
        "low": {
            "type": "uv_low",
            "severity": SEVERITY_INFO,
            "message": "UV is below the preferred range for this asset.",
            "recommended_action": "review_light_profile",
        },
    },
    "air_quality.voc": {
        "high": {
            "type": "voc_high",
            "severity": SEVERITY_MODERATE,
            "message": "Improve ventilation or filtration to reduce VOC exposure.",
            "recommended_action": "improve_ventilation",
        }
    },
    "air_quality.formaldehyde": {
        "high": {
            "type": "formaldehyde_high",
            "severity": SEVERITY_HIGH,
            "message": "Reduce formaldehyde exposure through ventilation or source control.",
            "recommended_action": "reduce_formaldehyde",
        }
    },
    "air_quality.ozone": {
        "high": {
            "type": "ozone_high",
            "severity": SEVERITY_HIGH,
            "message": "Reduce ozone exposure to protect the asset.",
            "recommended_action": "reduce_ozone_exposure",
        }
    },
    "air_quality.no2": {
        "high": {
            "type": "no2_high",
            "severity": SEVERITY_HIGH,
            "message": "Reduce NO2 exposure through ventilation or source control.",
            "recommended_action": "reduce_no2_exposure",
        }
    },
    "particulates.pm2_5": {
        "high": {
            "type": "pm2_5_high",
            "severity": SEVERITY_MODERATE,
            "message": "Reduce fine particulate exposure with filtration or source reduction.",
            "recommended_action": "filter_air",
        }
    },
    "particulates.pm10": {
        "high": {
            "type": "pm10_high",
            "severity": SEVERITY_MODERATE,
            "message": "Reduce coarse particulate exposure with filtration or cleaning.",
            "recommended_action": "reduce_particulates",
        }
    },
    "biological.mold_index": {
        "high": {
            "type": "mold_index_high",
            "severity": SEVERITY_HIGH,
            "message": "Address mold risk conditions immediately.",
            "recommended_action": "inspect_for_mold",
        }
    },
    "safety.leak": {
        "present": {
            "type": "water_leak",
            "severity": SEVERITY_CRITICAL,
            "message": "Water leak detected — immediate action is required.",
            "recommended_action": "stop_water_source",
        }
    },
    "structural.pressure": {
        "high": {
            "type": "pressure_high",
            "severity": SEVERITY_LOW,
            "message": "Pressure is above the preferred range for this asset.",
            "recommended_action": "review_pressure_conditions",
        },
        "low": {
            "type": "pressure_low",
            "severity": SEVERITY_LOW,
            "message": "Pressure is below the preferred range for this asset.",
            "recommended_action": "review_pressure_conditions",
        },
    },
    "structural.vibration": {
        "high": {
            "type": "vibration_high",
            "severity": SEVERITY_HIGH,
            "message": "Reduce vibration exposure to protect the asset.",
            "recommended_action": "isolate_vibration",
        }
    },
    "context.noise": {
        "high": {
            "type": "noise_high",
            "severity": SEVERITY_LOW,
            "message": "Reduce sustained noise exposure if it affects this asset's environment.",
            "recommended_action": "reduce_noise",
        }
    },
    "control_context.co2": {
        "high": {
            "type": "co2_high",
            "severity": SEVERITY_MODERATE,
            "message": "Improve ventilation to reduce CO2 concentration.",
            "recommended_action": "increase_ventilation",
        }
    },
    "external_environment.sun": {
        "high": {
            "type": "sun_exposure_high",
            "severity": SEVERITY_HIGH,
            "message": "Direct sun risk is elevated — reduce exposure or relocate the asset.",
            "recommended_action": "close_blinds",
        }
    },
    "external_environment.uv_index": {
        "high": {
            "type": "uv_index_high",
            "severity": SEVERITY_HIGH,
            "message": "External UV index is elevated — reduce direct exposure.",
            "recommended_action": "block_uv",
        }
    },
}


# -----------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------

def _append_advisory(target: List[Dict[str, Any]], advisory: Dict[str, Any]) -> None:
    """Append an advisory after normalizing required fields and de-duplicating by type."""
    advisory_type = advisory.get("type")
    if advisory_type and any(existing.get("type") == advisory_type for existing in target):
        return

    required_fields = {
        "type": None,
        "severity": SEVERITY_LOW,
        "message": "",
        "recommended_action": None,
        "confidence": "medium",
        "section": None,
        "signal": None,
        "signal_path": None,
        "reason": None,
    }

    normalized = dict(required_fields)
    normalized.update({k: v for k, v in advisory.items() if v is not None})
    target.append(normalized)


def _normalize_confidence(value: Any) -> str:
    """Normalize confidence labels to low|medium|high."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"low", "medium", "high"}:
            return normalized

    if isinstance(value, (int, float)):
        if value >= 0.8:
            return "high"
        if value >= 0.5:
            return "medium"
        return "low"

    return "medium"


def _normalize_status(value: Any) -> Optional[str]:
    """Normalize evaluation status strings."""
    if value is None:
        return None

    normalized = str(value).strip().lower()

    aliases = {
        "ok": "normal",
        "normal": "normal",
        "within_range": "normal",
        "within-range": "normal",
        "in_range": "normal",
        "in-range": "normal",
        "pass": "normal",
        "none": "normal",
        "low": "low",
        "below_min": "low",
        "below-min": "low",
        "below_range": "low",
        "below-range": "low",
        "high": "high",
        "above_max": "high",
        "above-max": "high",
        "above_range": "high",
        "above-range": "high",
        "triggered": "present",
        "detected": "present",
        "present": "present",
        "alert": "present",
        "true": "present",
    }

    return aliases.get(normalized, normalized)


def _extract_breach_direction(finding: Dict[str, Any]) -> Optional[str]:
    """Extract canonical breach direction from a structured evaluation finding."""
    breach = finding.get("breach")
    status = finding.get("status")

    normalized_breach = _normalize_status(breach)
    if normalized_breach in {"low", "high", "present"}:
        return normalized_breach

    normalized_status = _normalize_status(status)
    if normalized_status in {"low", "high", "present"}:
        return normalized_status

    current = finding.get("current")
    if isinstance(current, bool) and current:
        return "present"

    if finding.get("detected") is True:
        return "present"

    return None


def _iter_signal_findings(evaluation: Dict[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    """Yield canonical (section, signal, finding) tuples from structured evaluation output.

    Expected canonical forms:
    1) Nested:
       evaluation["signal_results"] = {
           "climate": {
               "temperature": {...},
               "humidity": {...},
           },
           ...
       }

    2) Flat:
       evaluation["signal_results"] = {
           "climate.temperature": {...},
           "light.uv": {...},
           ...
       }

    Also accepts `signal_evaluations` as an equivalent structured container.
    No legacy flat environmental fields are consumed.
    """
    container: Any = (
        evaluation.get("signal_results")
        if evaluation.get("signal_results") is not None
        else evaluation.get("signal_evaluations")
    )

    if not isinstance(container, dict):
        return

    for outer_key, outer_value in container.items():
        if not isinstance(outer_value, dict):
            continue

        if "." in outer_key:
            section, signal = outer_key.split(".", 1)
            yield section, signal, outer_value
            continue

        section = outer_key
        for signal, finding in outer_value.items():
            if isinstance(finding, dict):
                yield section, signal, finding


def _build_signal_advisory(
    section: str,
    signal: str,
    finding: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Create an advisory from a canonical signal finding."""
    signal_path = f"{section}.{signal}"
    profile = ADVISORY_PROFILE.get(signal_path)
    if not profile:
        return None

    direction = _extract_breach_direction(finding)
    if not direction:
        return None

    template = profile.get(direction)
    if not template:
        return None

    confidence = _normalize_confidence(finding.get("confidence"))
    reason = finding.get("reason")

    advisory = dict(template)
    advisory.update(
        {
            "confidence": confidence,
            "section": section,
            "signal": signal,
            "signal_path": signal_path,
            "reason": reason,
        }
    )

    return advisory


def _collect_signal_advisories(
    evaluation: Dict[str, Any],
    advisories: List[Dict[str, Any]],
) -> None:
    """Generate advisories directly from canonical structured signal findings."""
    for section, signal, finding in _iter_signal_findings(evaluation):
        advisory = _build_signal_advisory(section, signal, finding)
        if advisory is not None:
            _append_advisory(advisories, advisory)


# -----------------------------------------------------------
# SPATIAL / SUN EXPOSURE ADVISORY
# -----------------------------------------------------------

def _spatial_advisory(
    evaluation: Dict[str, Any],
    advisories: List[Dict[str, Any]],
) -> None:
    """Generate recommendation-oriented advisories from spatial exposure outputs,
    including sensitivity-aware messaging."""

    exposure_risk = evaluation.get("exposure_risk")
    spatial_context = evaluation.get("spatial_context", {}) or {}

    if not isinstance(exposure_risk, dict):
        return

    level = str(exposure_risk.get("level", "")).strip().upper()
    reasons = exposure_risk.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]

    # ✅ NEW — sensitivity awareness from evaluation reasons
    evaluation_reasons = evaluation.get("reasons", [])
    if not isinstance(evaluation_reasons, list):
        evaluation_reasons = []

    sensitivity = "MODERATE"
    for r in evaluation_reasons:
        if isinstance(r, str) and r.startswith("exposure_sensitivity:"):
            sensitivity = r.split(":", 1)[1].upper()
            break

    if level not in {"MEDIUM", "HIGH"}:
        return

    # Optional spatial context
    facing_direction = spatial_context.get("facing_direction")
    directional_match = spatial_context.get("directional_match")
    lux = spatial_context.get("lux")
    uv = spatial_context.get("uv")

    # -----------------------------------------------------
    # Sensitivity descriptor (used in messaging)
    # -----------------------------------------------------
    sensitivity_descriptions = {
        "VERY_HIGH": "very high sensitivity (archival / light-sensitive materials)",
        "HIGH": "high sensitivity (art / wood / instruments)",
        "MODERATE": "moderate sensitivity",
        "LOW": "low sensitivity (durable materials)",
    }

    sensitivity_text = sensitivity_descriptions.get(
        sensitivity, "moderate sensitivity"
    )

    # -----------------------------------------------------
    # HIGH EXPOSURE
    # -----------------------------------------------------
    if level == "HIGH":
        reason_text = ", ".join(reasons) if reasons else "direct exposure conditions"

        message = "High sunlight exposure detected"

        if directional_match and facing_direction:
            message += f" (aligned with {facing_direction} exposure)"

        message += f" for a {sensitivity_text}"

        message += f" — {reason_text}. Reduce exposure or relocate the asset."

        _append_advisory(
            advisories,
            {
                "type": "sunlight_exposure_high",
                "severity": SEVERITY_HIGH,
                "message": message,
                "recommended_action": "reduce_direct_sun",
                "confidence": "high",
                "section": "external_environment",
                "signal": "sun",
                "signal_path": "external_environment.sun",
                "reason": "exposure_high",
            },
        )
        return

    # -----------------------------------------------------
    # MEDIUM EXPOSURE
    # -----------------------------------------------------
    message = "Moderate sunlight exposure detected"

    if directional_match and facing_direction:
        message += f" (aligned with {facing_direction} exposure)"

    message += f" for a {sensitivity_text}"

    if lux or uv:
        metrics = []
        if lux:
            metrics.append(f"lux={lux}")
        if uv:
            metrics.append(f"uv={uv}")

        if metrics:
            message += f" ({', '.join(metrics)})"

    message += " — consider reducing direct exposure."

    _append_advisory(
        advisories,
        {
            "type": "sunlight_exposure_medium",
            "severity": SEVERITY_MODERATE,
            "message": message,
            "recommended_action": "adjust_shades",
            "confidence": "medium",
            "section": "external_environment",
            "signal": "sun",
            "signal_path": "external_environment.sun",
            "reason": "exposure_medium",
        },
    )

# -----------------------------------------------------------
# CONFIDENCE / DATA QUALITY ADVISORY
# -----------------------------------------------------------

def _confidence_advisory(
    evaluation: Dict[str, Any],
    advisories: List[Dict[str, Any]],
) -> None:
    """Add a data quality advisory when overall evaluation confidence is reduced."""
    confidence = _normalize_confidence(evaluation.get("confidence"))
    confidence_reduced = bool(evaluation.get("confidence_reduced", False))

    if confidence == "low" or confidence_reduced:
        _append_advisory(
            advisories,
            {
                "type": "data_quality",
                "severity": SEVERITY_INFO,
                "message": "Environmental confidence is reduced — verify sensor availability, placement, or freshness.",
                "recommended_action": "check_sensors",
                "confidence": "low",
                "reason": "confidence_reduced",
            },
        )


# -----------------------------------------------------------
# PRIMARY ADVISORY SELECTION
# -----------------------------------------------------------

def _priority_index(severity: str) -> int:
    """Return severity index for ordering."""
    try:
        return PRIORITY_ORDER.index(severity)
    except ValueError:
        return len(PRIORITY_ORDER)


def _select_primary_advisory(advisories: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Select the primary advisory for UI display.

    Ordering:
    1. Highest severity
    2. Highest confidence
    3. Stable sort order thereafter
    """
    if not advisories:
        return None

    confidence_rank = {"high": 0, "medium": 1, "low": 2}

    sorted_advisories = sorted(
        advisories,
        key=lambda advisory: (
            _priority_index(str(advisory.get("severity", SEVERITY_INFO))),
            confidence_rank.get(str(advisory.get("confidence", "medium")), 99),
        ),
    )

    return sorted_advisories[0]


# -----------------------------------------------------------
# MAIN ENTRY POINT
# -----------------------------------------------------------

def generate_asset_advisory(evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """Generate recommendation-oriented asset advisories from canonical evaluation output.

    Architectural scope:
    - PURE function
    - No persistence
    - No coordinator interaction
    - No direct sensing
    - No legacy field compatibility
    - Consumes canonical evaluation output only
    """
    advisories: List[Dict[str, Any]] = []

    # Structured canonical signal-based advisories
    _collect_signal_advisories(evaluation, advisories)

    # Spatial exposure recommendations
    _spatial_advisory(evaluation, advisories)

    # Confidence / data quality
    _confidence_advisory(evaluation, advisories)

    primary = _select_primary_advisory(advisories)

    return {
        "advisories": advisories,
        "primary_advisory": primary,
    }
