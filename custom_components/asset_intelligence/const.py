"""Constants for the Asset Intelligence integration."""
DOMAIN = "asset_intelligence"
SIGNAL_ASSETS_UPDATED = f"{DOMAIN}_assets_updated"
SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED = f"{DOMAIN}_document_storage_availability_changed"

# -----------------------------------------------------------
# PHASE 6.6 — DOCUMENT RETRIEVAL LAYER
# -----------------------------------------------------------
# Default provider when none is specified
DOCUMENT_PROVIDER_LOCAL = "local"
# Known / normalized provider types (for future validation / UI)
DOCUMENT_PROVIDER_TYPES = {
    "local",
    "filesystem",
    "file",
    "nas",
    "smb",
    "sharepoint",
    "onedrive",
    "azure_blob",
    "s3",
    "external",
}
# Document resolution status values
DOCUMENT_STATUS_RESOLVED = "resolved"
DOCUMENT_STATUS_UNRESOLVED = "unresolved"
# Document issue codes (must align with document_models.py)
DOCUMENT_ISSUE_MISSING_DOCUMENT_ID = "missing_document_id"
DOCUMENT_ISSUE_INVALID_DOCUMENT_TYPE = "invalid_document_type"
DOCUMENT_ISSUE_INVALID_METADATA_TYPE = "invalid_metadata_type"
DOCUMENT_ISSUE_INVALID_TAGS_TYPE = "invalid_tags_type"
DOCUMENT_ISSUE_UNSUPPORTED_PROVIDER = "unsupported_provider"
DOCUMENT_ISSUE_MISSING_PROVIDER_REFERENCE = "missing_provider_reference"

# -----------------------------------------------------------
# CANONICAL ENVIRONMENT MODEL
# -----------------------------------------------------------
# Authoritative environmental sections and signals
ENVIRONMENT_SECTIONS = {
    "climate": ["temperature", "humidity", "dew_point"],
    "light": ["lux", "uv"],
    "safety": ["leak"],
    "air_quality": ["voc", "formaldehyde", "ozone", "no2"],
    "particulates": ["pm2_5", "pm10"],
    "biological": ["mold_index"],
    "structural": ["pressure", "vibration"],
    "context": ["noise"],
    "control_context": ["co2"],
    "external_environment": ["sun", "uv_index", "forecast"],
}

# -----------------------------------------------------------
# SIGNAL TYPES
# -----------------------------------------------------------
# Numeric signals (float-based)
NUMERIC_SIGNALS = {
    "temperature",
    "humidity",
    "dew_point",
    "lux",
    "uv",
    "voc",
    "formaldehyde",
    "ozone",
    "no2",
    "pm2_5",
    "pm10",
    "pressure",
    "noise",
    "co2",
    "uv_index",
    "mold_index",
}

# Binary signals (True / False)
BINARY_SIGNALS = {
    "leak",
    "vibration",
}

# Derived signals (calculated, not directly sourced)
DERIVED_SIGNALS = {
    "dew_point",
    "mold_index",
    "uv_index",  # may come from external or derived blending
}

# Signals that allow aggregation strategies
AGGREGATABLE_SIGNALS = NUMERIC_SIGNALS

# Binary aggregation strategy signals
BINARY_AGGREGATION_SIGNALS = BINARY_SIGNALS

# -----------------------------------------------------------
# AGGREGATION STRATEGIES
# -----------------------------------------------------------
AGGREGATION_MEAN = "mean"
AGGREGATION_MEDIAN = "median"
AGGREGATION_PRIMARY = "primary"
VALID_AGGREGATIONS = {
    AGGREGATION_MEAN,
    AGGREGATION_MEDIAN,
    AGGREGATION_PRIMARY,
}

# -----------------------------------------------------------
# CONFIDENCE LEVELS
# -----------------------------------------------------------
CONFIDENCE_GOOD = "GOOD"
CONFIDENCE_PARTIAL = "PARTIAL"
CONFIDENCE_DEGRADED = "DEGRADED"
CONFIDENCE_STALE = "STALE"

# -----------------------------------------------------------
# DEFAULT SECTION STRUCTURE
# -----------------------------------------------------------
# Used to initialize environment safely across all systems
DEFAULT_ENVIRONMENT_STRUCTURE = {
    "climate": {
        "temperature": None,
        "humidity": None,
        "dew_point": None,
    },
    "light": {
        "lux": None,
        "uv": None,
    },
    "safety": {
        "leak": None,
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
        "sun": {
            "azimuth": None,
            "elevation": None,
        },
        "uv_index": None,
        "forecast": None,
    },
}

# -----------------------------------------------------------
# HELPER LOOKUPS (FAST RUNTIME CHECKS)
# -----------------------------------------------------------
# Flattened map: signal -> section
SIGNAL_TO_SECTION = {
    signal: section
    for section, signals in ENVIRONMENT_SECTIONS.items()
    for signal in signals
}

# All signals (set for fast lookup)
ALL_SIGNALS = set(SIGNAL_TO_SECTION.keys())
