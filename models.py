from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

# ===========================================================
# DESIGN INTENT
# ===========================================================
#
# This module provides OPTIONAL typed helper views over the
# dict-based storage model used by Asset Intelligence.
#
# IMPORTANT:
# - Coordinator provides runtime projections
# - These models are NOT authoritative schema
#
# Use cases:
#   - structured export
#   - validation helpers
#   - internal transformation logic
#
# Do NOT rely on these to define the database schema.
# ===========================================================

# ===========================================================
# CORE LIGHTWEIGHT MODEL
# ===========================================================
@dataclass
class AssetCore:
    asset_id: str
    name: Optional[str] = None
    asset_type: Optional[str] = None
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetCore":
        return cls(
            asset_id=data.get("asset_id"),
            name=data.get("name"),
            asset_type=data.get("asset_type"),
        )
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ===========================================================
# ENVIRONMENT REQUIREMENTS (STORE-SHAPED)
# ===========================================================
@dataclass
class EnvironmentRequirements:
    temperature: Optional[Dict[str, float]] = None
    humidity: Optional[Dict[str, float]] = None
    light: Optional[Dict[str, Any]] = None
    debounce: Optional[Dict[str, Any]] = None
    hysteresis: Optional[Dict[str, Any]] = None
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "EnvironmentRequirements":
        if not isinstance(data, dict):
            return cls()
        return cls(
            temperature=data.get("temperature"),
            humidity=data.get("humidity"),
            light=data.get("light"),
            debounce=data.get("debounce"),
            hysteresis=data.get("hysteresis"),
        )
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ===========================================================
# DOCUMENT MODEL (LIGHTWEIGHT)
# ===========================================================
@dataclass
class Document:
    type: str
    uri: str
    title: Optional[str] = None
    date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        return cls(
            type=data.get("type"),
            uri=data.get("uri"),
            title=data.get("title"),
            date=data.get("date"),
            tags=data.get("tags") or [],
        )
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ===========================================================
# LINK MODEL (DEVICE + ENTITIES)
# ===========================================================
@dataclass
class AssetLink:
    device_id: Optional[str] = None
    entity_ids: List[str] = field(default_factory=list)
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AssetLink":
        if not isinstance(data, dict):
            return cls()
        return cls(
            device_id=data.get("device_id"),
            entity_ids=data.get("entity_ids") or [],
        )
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ===========================================================
# CUSTODY MODEL (STORE-ALIGNED)
# ===========================================================
@dataclass
class Custody:
    status: Optional[str] = None
    holder: Optional[str] = None
    location_detail: Optional[str] = None
    notes: Optional[str] = None
    effective_at: Optional[str] = None
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Custody":
        if not isinstance(data, dict):
            return cls()
        return cls(
            status=data.get("status"),
            holder=data.get("holder"),
            location_detail=data.get("location_detail"),
            notes=data.get("notes"),
            effective_at=data.get("effective_at"),
        )
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ===========================================================
# COORDINATOR PROJECTION MODEL
# ===========================================================
@dataclass
class AssetProjection:
    asset_id: str
    area_id: Optional[str] = None
    risk_state: Optional[str] = None
    candidate_state: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    pending_red_since: Optional[str] = None
    environment_state_since: Optional[str] = None
    @classmethod
    def from_coordinator(cls, data: Dict[str, Any]) -> "AssetProjection":
        return cls(
            asset_id=data.get("asset_id"),
            area_id=data.get("room_area_id"),
            risk_state=data.get("risk_state"),
            candidate_state=data.get("candidate_state"),
            reasons=data.get("reasons") or [],
            pending_red_since=data.get("pending_red_since"),
            environment_state_since=data.get("environment_state_since"),
        )
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ===========================================================
# SAFETY HELPERS
# ===========================================================
def safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]

def safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}
