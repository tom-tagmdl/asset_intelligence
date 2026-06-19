from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import json
import os
import uuid
from typing import Any
import logging
from aiohttp import web

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import Event, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from .const import DOMAIN, SIGNAL_ASSETS_UPDATED, SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED
from .coordinator import AssetIntelligenceCoordinator
from .document_storage import DocumentStorage
from . import storage as ai_storage
from .storage import AssetStore
from .panel import async_setup_panel
from .validation import (
    AssetValidationError,
    validate_asset_payload,
    validate_room_environment_config,
)

_LOGGER = logging.getLogger(__name__)

async_ensure_storage = getattr(ai_storage, "async_ensure_storage", None)


PLATFORMS: list[str] = ["sensor", "binary_sensor"]
MAX_INLINE_UPLOAD_BYTES = 15 * 1024 * 1024

DATA_SERVICES_REGISTERED = "_services_registered"
DATA_TRACKER_LISTENER_UNSUB = "_tracker_listener_unsub"
DATA_DOCUMENT_VIEW_REGISTERED = "_document_view_registered"

REGISTERED_SERVICES: tuple[str, ...] = (
    "add_asset",
    "update_asset",
    "delete_asset",
    "link_to_device",
    "unlink_from_device",
    "add_tracker",
    "remove_tracker",
    "configure_document_storage",
    "upload_document",
    "attach_document",
    "update_document_metadata",
    "delete_document",
    "get_document_info",
    "check_document_availability",
    "get_asset_history",
    "add_physical_document_location",
    "set_environment_requirements",
    "set_room_environment",
    "set_custody_status",
    "record_loan_out",
    "record_loan_in",
    "export_inventory",
)


def _now_iso_local() -> str:
    """Local time in ISO format (matches HA UI expectations)."""
    return dt_util.now().isoformat()


async def _resolve_actor(hass: HomeAssistant, call: ServiceCall) -> str:
    """Resolve who initiated the action.

    Priority:
      1) explicit actor field in service data
      2) HA user_id (if available)
      3) 'system'
    """
    actor = call.data.get("actor") or call.data.get("updated_by") or call.data.get("created_by")
    if actor:
        return str(actor)

    user_id = getattr(call.context, "user_id", None)
    if user_id and hasattr(hass, "auth"):
        try:
            user = await hass.auth.async_get_user(user_id)
            if user and getattr(user, "name", None):
                return str(user.name)
        except Exception:
            pass

    if user_id:
        return f"user:{user_id}"

    return "system"


def _iter_runtimes(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return configured entry runtimes only."""
    runtimes: list[dict[str, Any]] = []

    for entry in hass.config_entries.async_entries(DOMAIN):
        value = getattr(entry, "runtime_data", None)
        if (
            isinstance(value, dict)
            and "store" in value
            and "coordinator" in value
        ):
            runtimes.append(value)

    return runtimes


def _get_runtime(hass: HomeAssistant) -> dict[str, Any]:
    """Return the first configured runtime (single-entry assumption for now)."""
    runtimes = _iter_runtimes(hass)
    if not runtimes:
        raise HomeAssistantError(
            "Asset Intelligence is not configured. Please add the integration first."
        )
    return runtimes[0]


def _get_store(hass: HomeAssistant) -> AssetStore:
    """Return the first configured store."""
    runtime = _get_runtime(hass)
    store = runtime.get("store")
    if not isinstance(store, AssetStore):
        raise HomeAssistantError("Asset Intelligence runtime store is not available.")
    return store


def _get_coordinator(hass: HomeAssistant) -> AssetIntelligenceCoordinator:
    """Return the first configured coordinator."""
    runtime = _get_runtime(hass)
    coordinator = runtime.get("coordinator")
    if coordinator is None:
        raise HomeAssistantError("Asset Intelligence coordinator is not available.")
    return coordinator

def _get_document_storage(hass: HomeAssistant) -> DocumentStorage:
    runtime = _get_runtime(hass)

    storage = runtime.get("document_storage")
    if storage:
        return storage

    store = _get_store(hass)
    storage = DocumentStorage(hass, store.get_document_storage_config())

    runtime["document_storage"] = storage
    return storage


async def _refresh_runtime(hass: HomeAssistant) -> None:
    """Request a full coordinator refresh and notify entity listeners."""
    coordinator = _get_coordinator(hass)
    await coordinator.async_request_refresh()
    async_dispatcher_send(hass, SIGNAL_ASSETS_UPDATED)


def _is_allowed_source_path(path: str) -> bool:
    """Restrict to common HA readable locations for import/upload sources."""
    return (
        path.startswith("/config/")
        or path.startswith("/share/")
        or path.startswith("/media/")
    )


def _normalize_storage_path(path: str | None) -> str:
    """Normalize user-entered storage paths to HA-friendly absolute paths."""
    if not isinstance(path, str):
        return ""

    normalized = os.path.expanduser(path.strip()).replace("\\", "/")
    if not normalized:
        return ""

    relative_ha_prefixes = ("media/", "share/", "config/")
    if any(normalized.startswith(prefix) for prefix in relative_ha_prefixes):
        normalized = f"/{normalized.lstrip('/')}"

    return normalized


def _decode_inline_base64(data: Any, field_name: str) -> bytes:
    if not isinstance(data, str) or not data.strip():
        raise HomeAssistantError(f"{field_name} must be a non-empty base64 string")

    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as ex:
        raise HomeAssistantError(f"{field_name} must be valid base64") from ex

    if not decoded:
        raise HomeAssistantError(f"{field_name} decoded to an empty payload")

    if len(decoded) > MAX_INLINE_UPLOAD_BYTES:
        max_mb = MAX_INLINE_UPLOAD_BYTES // (1024 * 1024)
        raise HomeAssistantError(f"{field_name} exceeds max size of {max_mb} MB")

    return decoded


def _normalize_explicit_labels(value: Any) -> set[str] | None:
    """Normalize explicit label input from service payloads.

    Returns None when labels were not explicitly provided.
    """
    if value is None:
        return None

    if not isinstance(value, (list, tuple, set)):
        return set()

    normalized: set[str] = set()
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.add(text)
            continue

        if isinstance(item, dict):
            text = item.get("label_id") or item.get("id")
            if isinstance(text, str) and text.strip():
                normalized.add(text.strip())

    return normalized


def _apply_explicit_registry_updates(
    hass: HomeAssistant,
    *,
    asset_id: str,
    area_id: str | None,
    labels: set[str] | None,
) -> bool:
    """Apply explicit user-requested metadata updates to HA registries."""
    if area_id is None and labels is None:
        return False

    desired_area = None if area_id in (None, "", "unknown") else str(area_id)
    desired_labels = labels
    changed = False

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Keep the Asset Intelligence device metadata aligned.
    device = device_registry.async_get_device({(DOMAIN, str(asset_id))})
    if device:
        update_args: Dict[str, Any] = {}

        if device.area_id != desired_area:
            update_args["area_id"] = desired_area

        if desired_labels is not None and hasattr(device, "labels"):
            current_labels = set(getattr(device, "labels") or [])
            if current_labels != desired_labels:
                update_args["labels"] = desired_labels

        if update_args:
            try:
                device_registry.async_update_device(device.id, **update_args)
                changed = True
            except TypeError:
                # Older HA cores may not support labels on device update.
                update_args.pop("labels", None)
                if update_args:
                    device_registry.async_update_device(device.id, **update_args)
                    changed = True

    # Keep the integration entities aligned (what users most often inspect).
    tracked_entities = (
        ("sensor", f"{DOMAIN}_{asset_id}"),
        ("binary_sensor", f"{DOMAIN}_{asset_id}_at_risk"),
    )

    for platform, unique_id in tracked_entities:
        entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if not entity_id:
            continue

        entry = entity_registry.async_get(entity_id)
        if not entry:
            continue

        entity_updates: Dict[str, Any] = {}
        if entry.area_id != desired_area:
            entity_updates["area_id"] = desired_area

        if desired_labels is not None and hasattr(entry, "labels"):
            entry_labels = set(getattr(entry, "labels") or [])
            if entry_labels != desired_labels:
                entity_updates["labels"] = desired_labels

        if entity_updates:
            try:
                entity_registry.async_update_entity(entity_id, **entity_updates)
                changed = True
            except TypeError:
                # Older HA cores may not support labels on entity update.
                entity_updates.pop("labels", None)
                if entity_updates:
                    entity_registry.async_update_entity(entity_id, **entity_updates)
                    changed = True

    return changed


def _ensure_audit_fields(asset: Dict[str, Any]) -> None:
    asset.setdefault("audit_log", [])
    asset.setdefault("created_by", None)
    asset.setdefault("updated_by", None)

def _ensure_system_of_record_fields(asset: Dict[str, Any]) -> None:
    """Ensure required system-of-record fields exist.

    NOTE:
    Canonical normalization is handled by storage.py. This only guarantees presence.
    """
    if not isinstance(asset.get("documents"), list):
        asset["documents"] = []

    if not isinstance(asset.get("physical_documents"), list):
        asset["physical_documents"] = []

    if not isinstance(asset.get("trackers"), list):
        asset["trackers"] = []

    if not isinstance(asset.get("links"), dict):
        asset["links"] = {}

    if not isinstance(asset.get("loans"), list):
        asset["loans"] = []

    if not isinstance(asset.get("custody"), dict):
        asset["custody"] = {}

    _ensure_audit_fields(asset)


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
        # Prefer summaries for known heavy structures unless explicit field deltas are present.
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


def _compact_audit_details(details: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {"value": _compact_audit_value(details)}

    compacted = _compact_audit_value(details)
    return compacted if isinstance(compacted, dict) else {"value": compacted}



def _append_audit(asset: Dict[str, Any], action: str, actor: str, details: Dict[str, Any]) -> None:
    _ensure_audit_fields(asset)
    audit_log = asset.get("audit_log")
    if not isinstance(audit_log, list):
        audit_log = []

    audit_log.append(
        {
            "timestamp": _now_iso_local(),
            "action": action,
            "actor": actor,
            "details": _compact_audit_details(details or {}),
        }
    )
    asset["audit_log"] = audit_log[-AUDIT_MAX_ENTRIES:]


def _audit_safe_value(value: Any) -> Any:
    """Convert values to JSON-safe structures for durable audit records."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): _audit_safe_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_audit_safe_value(v) for v in value]

    return str(value)


def _audit_values_equal(left: Any, right: Any) -> bool:
    return _audit_safe_value(left) == _audit_safe_value(right)


def _flatten_audit_paths(value: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dict/list values to comparable dotted paths."""
    normalized = _audit_safe_value(value)

    if isinstance(normalized, dict):
        flattened: Dict[str, Any] = {}
        for key, child in normalized.items():
            key_text = str(key)
            next_prefix = f"{prefix}.{key_text}" if prefix else key_text
            flattened.update(_flatten_audit_paths(child, next_prefix))
        return flattened

    return {prefix or "$": normalized}


def _build_field_changes(before_value: Any, after_value: Any) -> Dict[str, Dict[str, Any]]:
    """Build before/after change map using dotted leaf paths."""
    before_flat = _flatten_audit_paths(before_value)
    after_flat = _flatten_audit_paths(after_value)

    changes: Dict[str, Dict[str, Any]] = {}
    all_paths = sorted(set(before_flat.keys()) | set(after_flat.keys()))

    for path in all_paths:
        before_leaf = before_flat.get(path)
        after_leaf = after_flat.get(path)
        if _audit_values_equal(before_leaf, after_leaf):
            continue

        changes[path] = {
            "before": _audit_safe_value(before_leaf),
            "after": _audit_safe_value(after_leaf),
        }

    return changes


def _build_compact_field_change(field: str, before_value: Any, after_value: Any) -> Dict[str, Any] | None:
    """Build compact audit detail for a changed top-level field."""
    if _audit_values_equal(before_value, after_value):
        return None

    if field in {"environment_requirements", "custody", "links"}:
        nested_changes = _build_field_changes(before_value or {}, after_value or {})
        return {
            "changed_paths": list(nested_changes.keys()),
            "field_changes": nested_changes,
        }

    if field in {"documents", "physical_documents", "trackers", "loans"}:
        before_list = before_value if isinstance(before_value, list) else []
        after_list = after_value if isinstance(after_value, list) else []
        return {
            "before_count": len(before_list),
            "after_count": len(after_list),
            "delta": len(after_list) - len(before_list),
        }

    return {
        "before": _audit_safe_value(before_value),
        "after": _audit_safe_value(after_value),
    }

# -----------------------------------------------------------## CANONICAL ENVIRONMENT REQUIREMENTS HELPERS
# -----------------------------------------------------------

CANONICAL_REQUIREMENT_SIGNALS: dict[str, list[str]] = {
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


def _coerce_float_or_none(value: Any) -> float | None:
    """Convert numeric-like input to float, otherwise None."""
    if value is None:
        return None

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalize_requirement_range(value: Any) -> dict[str, float | None]:
    """Normalize a requirement signal to {'min': ..., 'max': ...}."""
    if not isinstance(value, dict):
        return {"min": None, "max": None}

    return {
        "min": _coerce_float_or_none(value.get("min")),
        "max": _coerce_float_or_none(value.get("max")),
    }


def _empty_environment_requirements_payload() -> dict[str, Any]:
    """Return the fully populated canonical environment requirements structure."""
    payload: dict[str, Any] = {}

    for section, signals in CANONICAL_REQUIREMENT_SIGNALS.items():
        payload[section] = {}
        for signal in signals:
            payload[section][signal] = {"min": None, "max": None}

    return payload


def _normalize_existing_environment_requirements(existing: Any) -> dict[str, Any]:
    """Normalize any existing requirements into canonical structure."""
    normalized = _empty_environment_requirements_payload()

    if not isinstance(existing, dict):
        return normalized

    for section, signals in CANONICAL_REQUIREMENT_SIGNALS.items():
        section_value = existing.get(section)
        if not isinstance(section_value, dict):
            continue

        for signal in signals:
            normalized[section][signal] = _normalize_requirement_range(
                section_value.get(signal)
            )

    debounce = existing.get("debounce")
    if isinstance(debounce, dict):
        normalized["debounce"] = {
            "red_transition_seconds": _coerce_float_or_none(
                debounce.get("red_transition_seconds")
            ),
            "recovery_seconds": _coerce_float_or_none(
                debounce.get("recovery_seconds")
            ),
        }

    return normalized


def _validate_environment_requirements_payload(payload: Any) -> dict[str, Any]:
    """Validate canonical environment requirements payload."""
    if not isinstance(payload, dict):
        raise HomeAssistantError(
            "environment_requirements must be a dictionary using canonical sections/signals."
        )

    for section, section_value in payload.items():
        if section == "debounce":
            if not isinstance(section_value, dict):
                raise HomeAssistantError(
                    "environment_requirements.debounce must be a dictionary if provided."
                )
            continue

        if section not in CANONICAL_REQUIREMENT_SIGNALS:
            raise HomeAssistantError(
                f"Unsupported environment requirement section '{section}'. "
                f"Allowed sections: {', '.join(CANONICAL_REQUIREMENT_SIGNALS.keys())}"
            )

        if not isinstance(section_value, dict):
            raise HomeAssistantError(
                f"environment_requirements.{section} must be a dictionary."
            )

        allowed_signals = CANONICAL_REQUIREMENT_SIGNALS[section]
        for signal in section_value.keys():
            if signal not in allowed_signals:
                raise HomeAssistantError(
                    f"Unsupported signal '{section}.{signal}'. "
                    f"Allowed signals for {section}: {', '.join(allowed_signals)}"
                )

    return payload

def _merge_environment_requirements(
    existing: Any,
    incoming: Any,
) -> dict[str, Any]:
    """Merge incoming canonical requirements into normalized existing requirements."""
    validated = _validate_environment_requirements_payload(incoming)
    merged = _normalize_existing_environment_requirements(existing)

    for section, section_value in validated.items():
        if section == "debounce":
            debounce = section_value if isinstance(section_value, dict) else {}
            merged["debounce"] = {
                "red_transition_seconds": _coerce_float_or_none(
                    debounce.get("red_transition_seconds")
                ),
                "recovery_seconds": _coerce_float_or_none(
                    debounce.get("recovery_seconds")
                ),
            }
            continue

        current_section = section_value if isinstance(section_value, dict) else {}
        for signal in CANONICAL_REQUIREMENT_SIGNALS[section]:
            if signal in current_section:
                merged[section][signal] = _normalize_requirement_range(
                    current_section.get(signal)
                )

    return merged

def _doc_summary_entry(doc: Dict[str, Any]) -> str:
    title = (
        doc.get("title")
        or doc.get("filename")
        or doc.get("document_id")
        or "document"
    )

    metadata = doc.get("metadata")
    doc_type = (
        doc.get("type")
        or metadata.get("document_type")
        if isinstance(metadata, dict)
        else None
    ) or "document"

    return f"{doc_type}: {title}"


def _rebuild_document_summary(asset: Dict[str, Any]) -> None:
    docs = asset.get("documents", []) or []
    docs = [d for d in docs if isinstance(d, dict)]

    asset["document_count"] = len(docs)
    asset["document_summary"] = [_doc_summary_entry(d) for d in docs]

    asset["last_document_id"] = docs[-1].get("document_id") if docs else None
    asset["last_document_title"] = (
        (docs[-1].get("title") or docs[-1].get("filename"))
        if docs
        else None
    )

    # Canonical model no longer uses URI-style document references
    asset["last_document_uri"] = None


def _find_document_record(
    asset: Dict[str, Any],
    *,
    document_id: str | None = None,
    provider_document_id: str | None = None,
) -> Dict[str, Any] | None:
    """Find a document record on an asset by document_id or provider_document_id."""
    docs = asset.get("documents", [])
    if not isinstance(docs, list):
        return None

    for doc in docs:
        if not isinstance(doc, dict):
            continue

        if document_id and doc.get("document_id") == document_id:
            return doc

        if provider_document_id and doc.get("provider_document_id") == provider_document_id:
            return doc

    return None

def _find_active_loan_out(loans: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Return active loan records for direction=out."""
    active: list[Dict[str, Any]] = []
    for loan in loans or []:
        if (
            isinstance(loan, dict)
            and loan.get("direction") == "out"
            and loan.get("state") == "active"
        ):
            active.append(loan)
    return active


def _history_fmt_ts(ts: Any) -> str:
    if not ts:
        return ""
    try:
        parsed = dt_util.parse_datetime(str(ts))
        if parsed is None:
            return str(ts)
        return dt_util.as_local(parsed).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _history_ts_ms(value: Any) -> int:
    if not value:
        return 0
    try:
        parsed = dt_util.parse_datetime(str(value))
        if parsed is None:
            return 0
        return int(parsed.timestamp() * 1000)
    except Exception:
        return 0


def _history_color_for_entry(kind: Any, categories: Any = None) -> str:
    kind_text = str(kind or "").lower()
    category_values = categories if isinstance(categories, list) else []
    category_set = {str(value).lower() for value in category_values}

    if kind_text == "risk" or "risk" in category_set:
        return "red"
    if kind_text == "documents" or "documents" in category_set:
        return "green"
    if kind_text in {"environment", "custody"}:
        return "amber"
    if "environment" in category_set or "custody" in category_set:
        return "amber"
    return "neutral"


def _history_action_categories(action: Any) -> list[str]:
    action_text = str(action or "").lower()
    categories: list[str] = []

    categories.append("audit")

    if any(token in action_text for token in [
        "upload_document",
        "attach_document",
        "update_document_metadata",
        "delete_document",
        "add_physical_document_location",
    ]):
        categories.append("documents")

    if "set_environment_requirements" in action_text:
        categories.append("environment")

    if any(token in action_text for token in [
        "set_custody_status",
        "record_loan_out",
        "record_loan_in",
    ]):
        categories.append("custody")

    return categories


def _history_kind_from_audit_action(action: Any) -> str:
    action_text = str(action or "").lower()

    if any(token in action_text for token in [
        "upload_document",
        "attach_document",
        "update_document_metadata",
        "delete_document",
        "add_physical_document_location",
    ]):
        return "documents"

    if "set_environment_requirements" in action_text:
        return "environment"

    if any(token in action_text for token in [
        "set_custody_status",
        "record_loan_out",
        "record_loan_in",
    ]):
        return "custody"

    return "audit"


def _build_asset_history_payload(asset: Dict[str, Any], max_entries: int = 80) -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []

    audit_log = asset.get("audit_log") if isinstance(asset.get("audit_log"), list) else []
    for evt in audit_log:
        if not isinstance(evt, dict):
            continue

        ts = evt.get("timestamp") or evt.get("occurred_at")
        action = str(evt.get("action") or evt.get("message") or "").strip()
        actor = str(evt.get("actor") or evt.get("user") or "").strip()
        categories = _history_action_categories(action)
        kind = _history_kind_from_audit_action(action)

        entries.append(
            {
                "kind": kind,
                "source": "audit",
                "categories": categories,
                "color": _history_color_for_entry(kind, categories),
                "title": f"{action.replace('_', ' ').title()} by {actor}" if actor and action else (action.replace("_", " ").title() if action else "Audit event"),
                "meta": _history_fmt_ts(ts),
                "copy": action,
                "details": evt.get("details") if isinstance(evt.get("details"), dict) else {},
                "_ts": _history_ts_ms(ts),
            }
        )

    environment_events = asset.get("environment_events") if isinstance(asset.get("environment_events"), list) else []
    for evt in environment_events:
        if not isinstance(evt, dict):
            continue
        ts = evt.get("occurred_at") or evt.get("timestamp") or evt.get("effective_at")
        evt_type = str(evt.get("type") or "").lower()
        kind = "risk" if evt_type == "environment_risk_state_changed" else "environment"
        state_value = evt.get("new_state") or evt.get("risk_state") or evt.get("state")

        entries.append(
            {
                "kind": kind,
                "source": "environment_event",
                "categories": [kind],
                "color": _history_color_for_entry(kind, [kind]),
                "title": evt.get("title") or ("Risk state changed" if kind == "risk" else "Environment event"),
                "meta": _history_fmt_ts(ts),
                "copy": evt.get("message") or evt.get("summary") or evt.get("reason") or "Environment update",
                "details": evt,
                "_ts": _history_ts_ms(ts),
            }
        )

    custody_events = asset.get("custody_events") if isinstance(asset.get("custody_events"), list) else []
    for evt in custody_events:
        if not isinstance(evt, dict):
            continue
        ts = evt.get("occurred_at") or evt.get("timestamp") or evt.get("effective_at")
        entries.append(
            {
                "kind": "custody",
                "source": "custody_event",
                "categories": ["custody"],
                "color": _history_color_for_entry("custody", ["custody"]),
                "title": evt.get("title") or evt.get("status") or "Custody event",
                "meta": _history_fmt_ts(ts),
                "copy": evt.get("notes") or evt.get("message") or evt.get("holder") or "Custody updated",
                "details": evt,
                "_ts": _history_ts_ms(ts),
            }
        )

    loans = asset.get("loans") if isinstance(asset.get("loans"), list) else []
    for loan in loans:
        if not isinstance(loan, dict):
            continue
        direction = str(loan.get("direction") or "").lower()
        state = str(loan.get("state") or "").lower()
        if direction != "out":
            continue

        if state == "active":
            ts = loan.get("start_date") or loan.get("recorded_at")
            entries.append(
                {
                    "kind": "custody",
                    "source": "loan",
                    "categories": ["custody"],
                    "color": _history_color_for_entry("custody", ["custody"]),
                    "title": "Loan out recorded",
                    "meta": _history_fmt_ts(ts),
                    "copy": f"Loaned to {loan.get('counterparty')}" if loan.get("counterparty") else "Asset loaned out",
                    "details": loan,
                    "_ts": _history_ts_ms(ts),
                }
            )
        elif state == "returned":
            ts = loan.get("actual_return_date") or loan.get("closed_at") or loan.get("recorded_at")
            entries.append(
                {
                    "kind": "custody",
                    "source": "loan",
                    "categories": ["custody"],
                    "color": _history_color_for_entry("custody", ["custody"]),
                    "title": "Loan in recorded",
                    "meta": _history_fmt_ts(ts),
                    "copy": f"Returned from {loan.get('counterparty')}" if loan.get("counterparty") else "Asset returned",
                    "details": loan,
                    "_ts": _history_ts_ms(ts),
                }
            )

    sorted_entries = sorted(entries, key=lambda item: int(item.get("_ts") or 0), reverse=True)[:max_entries]

    def _filter_for(name: str) -> list[Dict[str, Any]]:
        if name == "all":
            return sorted_entries
        if name == "audit":
            return [entry for entry in sorted_entries if str(entry.get("kind") or "") == "audit"]
        if name == "environment":
            return [
                entry
                for entry in sorted_entries
                if str(entry.get("kind") or "") == "environment"
                or "environment" in (entry.get("categories") or [])
            ]
        if name == "risk":
            return [entry for entry in sorted_entries if str(entry.get("kind") or "") == "risk"]
        if name == "documents":
            return [entry for entry in sorted_entries if "documents" in (entry.get("categories") or [])]
        if name == "custody":
            return [entry for entry in sorted_entries if "custody" in (entry.get("categories") or []) or str(entry.get("kind") or "") == "custody"]
        if name == "measurements":
            return [entry for entry in sorted_entries if str(entry.get("kind") or "") == "measurements"]
        return []

    return {
        "all": sorted_entries,
        "by_filter": {
            "all": _filter_for("all"),
            "audit": _filter_for("audit"),
            "environment": _filter_for("environment"),
            "risk": _filter_for("risk"),
            "documents": _filter_for("documents"),
            "custody": _filter_for("custody"),
            "measurements": _filter_for("measurements"),
        },
    }


def _empty_asset_history_payload(asset_id: str) -> Dict[str, Any]:
    return {
        "asset_id": asset_id,
        "found": False,
        "all": [],
        "by_filter": {
            "all": [],
            "audit": [],
            "environment": [],
            "risk": [],
            "documents": [],
            "custody": [],
            "measurements": [],
        },
    }


class AssetIntelligenceDocumentView(HomeAssistantView):
    """Serve stored document bytes for authenticated panel rendering."""

    url = "/api/asset_intelligence/document/{asset_id}/{document_id}"
    name = "api:asset_intelligence:document"
    requires_auth = True

    async def get(self, request, asset_id: str, document_id: str):
        hass: HomeAssistant = request.app["hass"]

        store = _get_store(hass)
        document_storage = _get_document_storage(hass)

        asset = store.get(asset_id)
        if not asset:
            raise web.HTTPNotFound(text="Asset not found")

        document_record = _find_document_record(asset, document_id=document_id)
        if not document_record:
            raise web.HTTPNotFound(text="Document not found")

        provider_document_id = document_record.get("provider_document_id")
        if not provider_document_id:
            raise web.HTTPNotFound(text="Document storage reference missing")

        try:
            content = await hass.async_add_executor_job(
                lambda: document_storage.read_document_bytes(
                    provider_document_id=provider_document_id,
                )
            )
        except FileNotFoundError as ex:
            raise web.HTTPNotFound(text="Stored document file not found") from ex
        except Exception as ex:
            raise web.HTTPInternalServerError(text="Failed to read stored document") from ex

        mime_type = str(document_record.get("mime_type") or "application/octet-stream")
        return web.Response(body=content, content_type=mime_type)


def _ensure_document_view_registered(hass: HomeAssistant) -> None:
    """Register document API view once per runtime."""
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get(DATA_DOCUMENT_VIEW_REGISTERED):
        return

    try:
        hass.http.register_view(AssetIntelligenceDocumentView())
        hass.data[DOMAIN][DATA_DOCUMENT_VIEW_REGISTERED] = True
    except Exception:
        _LOGGER.exception("Asset Intelligence: failed to register document API view")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (runs at HA startup)."""
    hass.data.setdefault(DOMAIN, {})

    # -----------------------------
    # ADD ASSET
    # -----------------------------
    async def handle_add_asset(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        payload = dict(call.data)
        explicit_area_id = payload.pop("area_id", None)
        explicit_labels = _normalize_explicit_labels(
            payload.pop("labels", payload.pop("label_ids", None))
        )
        if explicit_labels is None:
            explicit_labels = set()

        now = _now_iso_local()
        payload.setdefault("created_at", now)
        payload["updated_at"] = now

        payload.setdefault("created_by", actor)
        payload["updated_by"] = actor

        _append_audit(
            payload,
            "create_asset",
            actor,
            {"asset_id": payload.get("asset_id"), "name": payload.get("name")},
        )
        _rebuild_document_summary(payload)

        try:
            validate_asset_payload(payload)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(payload)

        await _refresh_runtime(hass)
        await hass.async_block_till_done()
        registry_changed = _apply_explicit_registry_updates(
            hass,
            asset_id=str(payload["asset_id"]),
            area_id=explicit_area_id,
            labels=explicit_labels,
        )
        if registry_changed:
            await _refresh_runtime(hass)
            await hass.async_block_till_done()
        else:
            await hass.async_block_till_done()
        hass.bus.async_fire(
            f"{DOMAIN}_asset_added",
            {
                "asset_id": payload["asset_id"],
                "name": payload["name"],
                "area_id": explicit_area_id,
                "actor": actor,
            },
        )

    # -----------------------------
    # UPDATE ASSET
    # -----------------------------
    async def handle_update_asset(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        explicit_area_id = call.data.get("area_id") if "area_id" in call.data else None
        explicit_labels = _normalize_explicit_labels(
            call.data.get("labels") if "labels" in call.data else call.data.get("label_ids")
        )

        # -----------------------------
        # BASIC FIELD MERGE (exclude documents)
        # -----------------------------
        for key, value in call.data.items():
            if key in ("documents", "asset_id", "area_id", "labels", "label_ids"):
                continue
            updated[key] = value

        # -----------------------------
        # DOCUMENT HANDLING (canonical only)
        # -----------------------------
        if "documents" in call.data:
            input_docs = call.data.get("documents")

            if not isinstance(input_docs, list):
                raise HomeAssistantError("documents must be a list")

            clean_docs: list[dict[str, Any]] = []

            for d in input_docs:
                if not isinstance(d, dict):
                    continue

                filename = d.get("filename")
                provider_document_id = d.get("provider_document_id")

                if not filename or not provider_document_id:
                    raise HomeAssistantError(
                        "Each document must include filename and provider_document_id"
                    )

                document_record = {
                    "document_id": d.get("document_id"),
                    "type": d.get("type"),
                    "title": d.get("title"),
                    "filename": filename,
                    "provider": d.get("provider"),
                    "provider_document_id": provider_document_id,
                    "mime_type": d.get("mime_type"),
                    "size_bytes": d.get("size_bytes"),
                    "tags": d.get("tags", []) if isinstance(d.get("tags"), list) else [],
                    "metadata": d.get("metadata", {}) if isinstance(d.get("metadata"), dict) else {},
                }

                clean_docs.append(document_record)

            updated["documents"] = clean_docs

        updated["created_at"] = existing.get("created_at")
        updated["created_by"] = existing.get("created_by")
        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor

        changed_keys = [
            k for k in call.data.keys()
            if k not in ("asset_id", "actor", "updated_by", "created_by")
        ]

        field_changes: Dict[str, Dict[str, Any]] = {}
        for field in changed_keys:
            if field in ("area_id", "labels", "label_ids"):
                # Registry-owned metadata is tracked separately outside store payload.
                continue

            before_value = existing.get(field)
            after_value = updated.get(field)

            compact_change = _build_compact_field_change(field, before_value, after_value)
            if compact_change is None:
                continue

            field_changes[field] = compact_change

        if explicit_area_id is not None:
            field_changes["area_id"] = {
                "before": None,
                "after": _audit_safe_value(explicit_area_id),
                "source": "ha_registry",
            }

        if explicit_labels is not None:
            field_changes["labels"] = {
                "before": None,
                "after": sorted(str(label) for label in explicit_labels),
                "source": "ha_registry",
            }

        _append_audit(
            updated,
            "update_asset",
            actor,
            {
                "changed_fields": list(field_changes.keys()),
                "field_changes": field_changes,
            },
        )

        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)
        await _refresh_runtime(hass)
        await hass.async_block_till_done()
        registry_changed = _apply_explicit_registry_updates(
            hass,
            asset_id=str(asset_id),
            area_id=explicit_area_id,
            labels=explicit_labels,
        )
        if registry_changed:
            await _refresh_runtime(hass)
            await hass.async_block_till_done()
        else:
            await hass.async_block_till_done()

        hass.bus.async_fire(
            f"{DOMAIN}_asset_updated",
            {
                "asset_id": asset_id,
                "name": updated.get("name"),
                "area_id": explicit_area_id,
                "actor": actor,
            },
        )

    # -----------------------------
    # DELETE ASSET
    # -----------------------------
    async def handle_delete_asset(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        asset_key = str(asset_id)

        existing = store.get(asset_key)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_key}' not found")

        documents = existing.get("documents")
        if not isinstance(documents, list):
            documents = []

        physical_documents = existing.get("physical_documents")
        if not isinstance(physical_documents, list):
            physical_documents = []

        # Cascade through the existing document delete service so document
        # metadata and storage cleanup stay consistent in one code path.
        delete_refs: list[dict[str, str]] = []
        seen_refs: set[tuple[str, str]] = set()
        for doc in [*documents, *physical_documents]:
            if not isinstance(doc, dict):
                continue

            doc_id = doc.get("document_id")
            provider_document_id = doc.get("provider_document_id")

            if isinstance(doc_id, str) and doc_id.strip():
                dedupe_key = ("document_id", doc_id.strip())
                if dedupe_key not in seen_refs:
                    seen_refs.add(dedupe_key)
                    delete_refs.append({"document_id": doc_id.strip()})
                continue

            if isinstance(provider_document_id, str) and provider_document_id.strip():
                dedupe_key = ("provider_document_id", provider_document_id.strip())
                if dedupe_key not in seen_refs:
                    seen_refs.add(dedupe_key)
                    delete_refs.append(
                        {"provider_document_id": provider_document_id.strip()}
                    )

        for ref in delete_refs:
            payload: dict[str, Any] = {
                "asset_id": asset_key,
                "actor": actor,
                "delete_storage": True,
            }
            payload.update(ref)
            await hass.services.async_call(
                DOMAIN,
                "delete_document",
                payload,
                blocking=True,
            )

        # Re-check after cascade cleanup and fail safe if unresolved refs remain.
        existing = store.get(asset_key)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_key}' not found")

        remaining_documents = existing.get("documents")
        if not isinstance(remaining_documents, list):
            remaining_documents = []

        remaining_physical_documents = existing.get("physical_documents")
        if not isinstance(remaining_physical_documents, list):
            remaining_physical_documents = []

        if remaining_documents or remaining_physical_documents:
            raise HomeAssistantError(
                "Unable to delete all attached documents before deleting asset"
            )

        # ---------------------------------------------------------
        # Remove integration entities/device from Home Assistant registry
        # ---------------------------------------------------------
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)

        # Remove known entity registry entries first so device removal can succeed.
        known_unique_ids = [
            f"{DOMAIN}_{asset_key}",
            f"{DOMAIN}_{asset_key}_at_risk",
        ]
        for platform, unique_id in (
            ("sensor", known_unique_ids[0]),
            ("binary_sensor", known_unique_ids[1]),
        ):
            entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)
            if entity_id:
                try:
                    entity_registry.async_remove(entity_id)
                except Exception:
                    _LOGGER.exception(
                        "Asset Intelligence: failed to remove entity registry entry '%s' for asset_id=%s",
                        entity_id,
                        asset_key,
                    )

        device = device_registry.async_get_device({(DOMAIN, asset_key)})
        if device:
            for entry in er.async_entries_for_device(entity_registry, device.id):
                if entry.platform == DOMAIN:
                    try:
                        entity_registry.async_remove(entry.entity_id)
                    except Exception:
                        _LOGGER.exception(
                            "Asset Intelligence: failed to remove device-linked entity '%s' for asset_id=%s",
                            entry.entity_id,
                            asset_key,
                        )

            _LOGGER.warning(
                "Asset Intelligence: removing device for asset_id=%s (device_id=%s)",
                asset_key,
                device.id,
            )
            removed = device_registry.async_remove_device(device.id)
            if not removed:
                # If device cannot be removed, clear registry-owned placement metadata.
                try:
                    device_registry.async_update_device(device.id, area_id=None, labels=set())
                except Exception:
                    _LOGGER.exception(
                        "Asset Intelligence: failed to clear lingering registry metadata for asset_id=%s",
                        asset_key,
                    )

        if asset_key in store.assets:
            del store.assets[asset_key]
        await store.async_save()

        await _refresh_runtime(hass)
        await hass.async_block_till_done()
        hass.bus.async_fire(
            f"{DOMAIN}_asset_deleted",
            {"asset_id": asset_key, "name": existing.get("name"), "actor": actor},
        )

    # -----------------------------
    # LINK TO DEVICE
    # -----------------------------
    async def handle_link_to_device(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        device_id = call.data.get("device_id")
        entity_ids = call.data.get("entity_ids")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        if not device_id and not entity_ids:
            raise HomeAssistantError("Provide at least one of: device_id, entity_ids")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        resolved_device_id = device_id

        normalized_entity_ids: list[str] = []
        if entity_ids is not None:
            if not isinstance(entity_ids, list):
                raise HomeAssistantError("entity_ids must be a list of entity_id strings")
            for eid in entity_ids:
                if not isinstance(eid, str) or not eid.strip():
                    raise HomeAssistantError("entity_ids must be a list of entity_id strings")
                entry = ent_reg.async_get(eid)
                if entry is None:
                    raise HomeAssistantError(f"entity_id '{eid}' not found in entity registry")
                normalized_entity_ids.append(eid)
                if resolved_device_id is None and entry.device_id:
                    resolved_device_id = entry.device_id

        device = None
        if resolved_device_id is not None:
            device = dev_reg.async_get(resolved_device_id)
            if device is None:
                raise HomeAssistantError(
                    f"device_id '{resolved_device_id}' not found in device registry"
                )

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        links = updated.get("links")
        if not isinstance(links, dict):
            links = {}

        if resolved_device_id is not None:
            links["device_id"] = resolved_device_id

        if normalized_entity_ids:
            current = links.get("entity_ids", [])
            if not isinstance(current, list):
                current = []
            for eid in normalized_entity_ids:
                if eid not in current:
                    current.append(eid)
            links["entity_ids"] = current

        updated["links"] = links

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "link_to_device",
            actor,
            {"device_id": resolved_device_id, "entity_ids": normalized_entity_ids},
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_asset_linked",
            {
                "asset_id": asset_id,
                "device_id": resolved_device_id,
                "entity_ids": normalized_entity_ids,
                "actor": actor,
            },
        )

    # -----------------------------
    # UNLINK FROM DEVICE
    # -----------------------------
    async def handle_unlink_from_device(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        device_id = call.data.get("device_id")
        entity_ids = call.data.get("entity_ids")
        remove_all = call.data.get("remove_all", False)

        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        if not remove_all and not device_id and not entity_ids:
            raise HomeAssistantError("Provide device_id and/or entity_ids, or set remove_all: true")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        links = updated.get("links")
        if not isinstance(links, dict):
            links = {}

        removed_entities: list[str] = []

        if remove_all:
            links = {}
        else:
            if device_id is not None and links.get("device_id") == device_id:
                links.pop("device_id", None)

            if entity_ids is not None:
                if not isinstance(entity_ids, list):
                    raise HomeAssistantError("entity_ids must be a list of entity_id strings")
                current = links.get("entity_ids", [])
                if not isinstance(current, list):
                    current = []
                for eid in entity_ids:
                    if eid in current:
                        current.remove(eid)
                        removed_entities.append(eid)
                if current:
                    links["entity_ids"] = current
                else:
                    links.pop("entity_ids", None)

        updated["links"] = links
        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "unlink_from_device",
            actor,
            {
                "device_id": device_id,
                "entity_ids_removed": removed_entities,
                "remove_all": bool(remove_all),
            },
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_asset_unlinked",
            {
                "asset_id": asset_id,
                "device_id": device_id,
                "entity_ids_removed": removed_entities,
                "actor": actor,
            },
        )

    # -----------------------------
    # CONFIGURE DOCUMENT STORAGE
    # -----------------------------
    async def handle_configure_document_storage(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        provider = (call.data.get("provider") or "filesystem").strip()
        root_path = call.data.get("root_path")
        documents_enabled = bool(call.data.get("documents_enabled", True))
        requires_network_storage = bool(
            call.data.get("requires_network_storage", True)
        )

        if documents_enabled and not root_path:
            raise HomeAssistantError(
                "root_path is required when documents_enabled is true"
            )

        config = {
            "provider": provider,
            "root_path": root_path,
            "documents_enabled": documents_enabled,
            "requires_network_storage": requires_network_storage,
        }

        await store.set_document_storage_config(config)

        # Update runtime DocumentStorage instance and evaluate availability
        runtime = _get_runtime(hass)
        doc_storage = DocumentStorage(hass, store.get_document_storage_config())
        runtime["document_storage"] = doc_storage

        available = False
        readable = False
        try:
            available = bool(doc_storage.is_available())
        except Exception:
            available = False

        try:
            readable = bool(doc_storage.is_readable())
        except Exception:
            readable = False

        runtime["document_storage_available"] = available

        # Notify listeners and front-end about availability change
        try:
            async_dispatcher_send(hass, SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED, available)
        except Exception:
            pass

        hass.bus.async_fire(
            f"{DOMAIN}_document_storage_configured",
            {
                "provider": provider,
                "documents_enabled": documents_enabled,
                "actor": actor,
            },
        )

        # Also fire a specific availability event so UI can react
        hass.bus.async_fire(
            f"{DOMAIN}_document_storage_availability_changed",
            {"available": available, "readable": readable, "actor": actor},
        )

        # Trigger coordinator refresh so other entities see updated storage config
        await _refresh_runtime(hass)

    # -----------------------------
    # CHECK DOCUMENT AVAILABILITY
    # -----------------------------
    async def handle_check_document_availability(call: ServiceCall) -> dict:
        """Return availability/readability status for configured document storage."""
        try:
            document_storage = _get_document_storage(hass)
        except HomeAssistantError:
            # Integration not configured yet
            return {
                "available": False,
                "readable": False,
                "provider": None,
                "documents_enabled": False,
                "requires_network_storage": True,
            }

        available = False
        readable = False
        try:
            available = bool(document_storage.is_available())
        except Exception:
            available = False

        try:
            readable = bool(document_storage.is_readable())
        except Exception:
            readable = False

        return {
            "available": available,
            "readable": readable,
            "provider": getattr(document_storage, "provider", None),
            "documents_enabled": getattr(document_storage, "documents_enabled", False),
            "requires_network_storage": getattr(document_storage, "requires_network_storage", True),
        }

    hass.services.async_register(
        DOMAIN,
        "check_document_availability",
        handle_check_document_availability,
        supports_response=True,
    )

    # -----------------------------
    # UPLOAD DOCUMENT
    # -----------------------------
    async def handle_upload_document(call: ServiceCall) -> None:
        store = _get_store(hass)
        document_storage = _get_document_storage(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        doc_type = call.data.get("type")
        source_path = call.data.get("source_path")
        content_base64 = call.data.get("content_base64")
        provided_filename = call.data.get("filename")
        uploaded_filename = call.data.get("uploaded_filename")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        if not doc_type:
            raise HomeAssistantError("type is required")

        if not source_path and not content_base64:
            raise HomeAssistantError("Provide source_path or content_base64")

        if source_path:
            if not _is_allowed_source_path(source_path):
                raise HomeAssistantError(
                    "source_path must be under /config/, /share/, or /media/"
                )

            if not os.path.exists(source_path):
                raise HomeAssistantError(f"Source file not found: {source_path}")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        if not bool(getattr(document_storage, "documents_enabled", False)):
            raise HomeAssistantError(
                "Document management is disabled. Configure a valid document storage path first."
            )

        if not document_storage.is_available():
            raise HomeAssistantError(
                "Document storage is not available or not writable."
            )

        filename = provided_filename or uploaded_filename or (os.path.basename(source_path) if source_path else None)
        if not filename:
            raise HomeAssistantError("Could not determine filename")

        preview_source_path = call.data.get("preview_source_path")
        preview_content_base64 = call.data.get("preview_content_base64")
        if preview_source_path:
            if not _is_allowed_source_path(preview_source_path):
                raise HomeAssistantError(
                    "preview_source_path must be under /config/, /share/, or /media/"
                )
            if not os.path.exists(preview_source_path):
                raise HomeAssistantError(
                    f"Preview source file not found: {preview_source_path}"
                )

        def _read_bytes(path: str) -> bytes:
            with open(path, "rb") as f:
                return f.read()

        content: bytes
        if content_base64:
            content = _decode_inline_base64(content_base64, "content_base64")
        else:
            content = await hass.async_add_executor_job(_read_bytes, source_path)

        preview_content = None
        if preview_content_base64:
            preview_content = _decode_inline_base64(
                preview_content_base64,
                "preview_content_base64",
            )
        elif preview_source_path:
            preview_content = await hass.async_add_executor_job(
                _read_bytes, preview_source_path
            )

        tags = call.data.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        metadata = {
            "type": doc_type,
            "title": call.data.get("title"),
            "notes": call.data.get("notes"),
            "date": call.data.get("date"),
            "tags": tags,
            "mime_type": call.data.get("mime_type"),
            "preview_mime_type": call.data.get("preview_mime_type"),
            "size_bytes": call.data.get("size_bytes"),
        }

        document_record = await hass.async_add_executor_job(
            lambda: document_storage.store_document(
                asset_id=asset_id,
                file_name=filename,
                content=content,
                metadata=metadata,
                preview_content=preview_content,
                created_by=actor,
            )
        )

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        documents = updated.get("documents", [])
        if not isinstance(documents, list):
            documents = []

        updated["documents"] = list(documents)
        updated["documents"].append(document_record)

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "upload_document",
            actor,
            {
                "document_id": document_record.get("document_id"),
                "type": document_record.get("type"),
                "title": document_record.get("title"),
                "date": document_record.get("date"),
                "notes": document_record.get("notes"),
                "filename": document_record.get("filename"),
                "provider_document_id": document_record.get("provider_document_id"),
            },
        )

        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)
        await _refresh_runtime(hass)

        hass.bus.async_fire(
            f"{DOMAIN}_document_uploaded",
            {
                "asset_id": asset_id,
                "document_id": document_record.get("document_id"),
                "type": document_record.get("type"),
                "title": document_record.get("title"),
                "actor": actor,
            },
        )

    # -----------------------------
    # ATTACH DOCUMENT (metadata-only)
    # -----------------------------
    async def handle_attach_document(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        tags = call.data.get("tags", [])
        if tags is None:
            tags = []
        if not isinstance(tags, list):
            raise HomeAssistantError("tags must be a list if provided")

        incoming_metadata = call.data.get("metadata")
        metadata = dict(incoming_metadata) if isinstance(incoming_metadata, dict) else {}

        if call.data.get("notes") is not None and "notes" not in metadata:
            metadata["notes"] = call.data.get("notes")

        if call.data.get("date") is not None and "date" not in metadata:
            metadata["date"] = call.data.get("date")

        if call.data.get("version") is not None and "version" not in metadata:
            metadata["version"] = call.data.get("version")

        document_id = call.data.get("document_id")
        if document_id is None or not str(document_id).strip():
            document_id = str(uuid.uuid4())

        doc_type = call.data.get("type")
        if not doc_type:
            raise HomeAssistantError("type is required for attach_document")

        provider_document_id = call.data.get("provider_document_id")
        if not provider_document_id:
            raise HomeAssistantError("provider_document_id is required for attach_document")

        filename = call.data.get("filename")
        if not filename:
            filename = os.path.basename(str(provider_document_id))
        if not filename:
            raise HomeAssistantError("filename is required for attach_document")

        provider = call.data.get("provider") or "external"
        location = call.data.get("location")
        checksum = call.data.get("checksum")
        created_at = call.data.get("created_at")
        modified_at = call.data.get("modified_at")

        document_record = {
            "document_id": str(document_id),
            "type": doc_type,
            "title": call.data.get("title"),
            "filename": filename,
            "provider": provider,
            "provider_document_id": provider_document_id,
            "location": location,
            "mime_type": call.data.get("mime_type"),
            "size_bytes": call.data.get("size_bytes"),
            "tags": list(tags),
            "metadata": {
                **metadata,
                "checksum": checksum,
                "created_at": created_at,
                "modified_at": modified_at,
            },
        }

        existing_docs = updated.get("documents", [])
        if not isinstance(existing_docs, list):
            existing_docs = []

        clean_docs = [d for d in existing_docs if isinstance(d, dict)]
        clean_docs.append(document_record)
        updated["documents"] = clean_docs

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "attach_document",
            actor,
            {
                "document_id": document_record.get("document_id"),
                "type": document_record.get("type"),
                "title": document_record.get("title"),
                "date": metadata.get("date"),
                "notes": metadata.get("notes"),
                "filename": document_record.get("filename"),
                "provider_document_id": document_record.get("provider_document_id"),
            },
        )

        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)
        await _refresh_runtime(hass)

        hass.bus.async_fire(
            f"{DOMAIN}_document_attached",
            {
                "asset_id": asset_id,
                "document_id": document_record.get("document_id"),
                "title": document_record.get("title"),
                "actor": actor,
            },
        )

    # -----------------------------
    # UPDATE DOCUMENT METADATA
    # -----------------------------
    async def handle_update_document_metadata(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        document_id = call.data.get("document_id")
        provider_document_id = call.data.get("provider_document_id")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        if not document_id and not provider_document_id:
            raise HomeAssistantError("Provide document_id or provider_document_id")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        target_document = _find_document_record(
            existing,
            document_id=document_id,
            provider_document_id=provider_document_id,
        )
        if not target_document:
            raise HomeAssistantError("Document not found on asset")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        docs = updated.get("documents", [])
        if not isinstance(docs, list):
            docs = []

        tags_value = call.data.get("tags")
        tags: list[str] | None = None
        if tags_value is not None:
            if not isinstance(tags_value, list):
                raise HomeAssistantError("tags must be a list if provided")
            tags = [str(tag).strip() for tag in tags_value if str(tag).strip()]

        updated_docs: list[Dict[str, Any]] = []
        updated_target_document: Dict[str, Any] | None = None
        replaced = False
        for item in docs:
            if not isinstance(item, dict):
                continue

            is_target = False
            if document_id and item.get("document_id") == document_id:
                is_target = True
            elif provider_document_id and item.get("provider_document_id") == provider_document_id:
                is_target = True

            if is_target and not replaced:
                next_doc = dict(item)

                if "type" in call.data and call.data.get("type"):
                    next_doc["type"] = call.data.get("type")

                if "title" in call.data:
                    next_doc["title"] = call.data.get("title")

                if "date" in call.data:
                    next_doc["date"] = call.data.get("date")

                if "notes" in call.data:
                    next_doc["notes"] = call.data.get("notes")

                if tags is not None:
                    next_doc["tags"] = tags

                metadata = next_doc.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}

                if "date" in call.data:
                    metadata["date"] = call.data.get("date")

                if "notes" in call.data:
                    metadata["notes"] = call.data.get("notes")

                next_doc["metadata"] = metadata
                updated_target_document = next_doc
                updated_docs.append(next_doc)
                replaced = True
            else:
                updated_docs.append(item)

        if not replaced:
            raise HomeAssistantError("Document not found on asset")

        updated["documents"] = updated_docs

        physical_docs = updated.get("physical_documents", [])
        if not isinstance(physical_docs, list):
            physical_docs = []

        synced_physical_docs: list[Dict[str, Any]] = []
        for entry in physical_docs:
            if not isinstance(entry, dict):
                continue

            same_document = False
            if document_id and entry.get("document_id") == document_id:
                same_document = True
            elif provider_document_id and entry.get("provider_document_id") == provider_document_id:
                same_document = True

            if same_document and "title" in call.data:
                synced_physical_docs.append({**entry, "title": call.data.get("title")})
            else:
                synced_physical_docs.append(entry)

        updated["physical_documents"] = synced_physical_docs

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        target_metadata = (
            target_document.get("metadata")
            if isinstance(target_document.get("metadata"), dict)
            else {}
        )
        updated_target_metadata = (
            updated_target_document.get("metadata")
            if isinstance(updated_target_document, dict)
            and isinstance(updated_target_document.get("metadata"), dict)
            else {}
        )

        before_metadata = {
            "type": target_document.get("type"),
            "title": target_document.get("title"),
            "date": target_document.get("date") or target_metadata.get("date"),
            "notes": target_document.get("notes") or target_metadata.get("notes"),
            "tags": target_document.get("tags", []),
        }
        after_metadata = {
            "type": (updated_target_document or {}).get("type"),
            "title": (updated_target_document or {}).get("title"),
            "date": (updated_target_document or {}).get("date") or updated_target_metadata.get("date"),
            "notes": (updated_target_document or {}).get("notes") or updated_target_metadata.get("notes"),
            "tags": (updated_target_document or {}).get("tags", []),
        }

        metadata_field_changes = _build_field_changes(before_metadata, after_metadata)

        # Only include changed fields in the audit details
        filtered_field_changes = {
            field: changes
            for field, changes in metadata_field_changes.items()
            if _audit_safe_value(changes.get("before")) != _audit_safe_value(changes.get("after"))
        }

        _append_audit(
            updated,
            "update_document_metadata",
            actor,
            {
                "document_id": target_document.get("document_id"),
                "provider_document_id": target_document.get("provider_document_id"),
                "changed_fields": list(filtered_field_changes.keys()),
                "field_changes": filtered_field_changes,
                "change_count": len(filtered_field_changes),
            },
        )

        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)
        await _refresh_runtime(hass)

        hass.bus.async_fire(
            f"{DOMAIN}_document_metadata_updated",
            {
                "asset_id": asset_id,
                "document_id": target_document.get("document_id"),
                "actor": actor,
            },
        )

    # -----------------------------
    # DELETE DOCUMENT
    # -----------------------------
    async def handle_delete_document(call: ServiceCall) -> None:
        store = _get_store(hass)
        document_storage = _get_document_storage(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        document_id = call.data.get("document_id")
        provider_document_id = call.data.get("provider_document_id")
        delete_storage = bool(call.data.get("delete_storage", True))

        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        if not document_id and not provider_document_id:
            raise HomeAssistantError("Provide document_id or provider_document_id")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        target_document = _find_document_record(
            existing,
            document_id=document_id,
            provider_document_id=provider_document_id,
        )
        if not target_document:
            raise HomeAssistantError("Document not found on asset")

        removed_document_id = target_document.get("document_id")
        removed_provider_document_id = target_document.get("provider_document_id")
        removed_type = target_document.get("type")
        removed_title = target_document.get("title") or target_document.get("filename")

        deleted_storage_document = False
        deleted_storage_preview = False

        if delete_storage:
            metadata = target_document.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            deleted_storage_document = await hass.async_add_executor_job(
                lambda: document_storage.delete_document(
                    provider_document_id=removed_provider_document_id,
                )
            )
            deleted_storage_preview = await hass.async_add_executor_job(
                lambda: document_storage.delete_preview(
                    preview_provider_document_id=metadata.get("preview_provider_document_id"),
                )
            )

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        docs = updated.get("documents", [])
        if not isinstance(docs, list):
            docs = []

        updated["documents"] = [
            doc for doc in docs
            if isinstance(doc, dict)
            and doc.get("document_id") != removed_document_id
            and doc.get("provider_document_id") != removed_provider_document_id
        ]

        physical_docs = updated.get("physical_documents", [])
        if not isinstance(physical_docs, list):
            physical_docs = []

        updated["physical_documents"] = [
            entry for entry in physical_docs
            if isinstance(entry, dict)
            and entry.get("document_id") != removed_document_id
            and entry.get("provider_document_id") != removed_provider_document_id
        ]

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "delete_document",
            actor,
            {
                "document_id": removed_document_id,
                "provider_document_id": removed_provider_document_id,
                "type": removed_type,
                "title": removed_title,
                "delete_storage": delete_storage,
                "deleted_storage_document": deleted_storage_document,
                "deleted_storage_preview": deleted_storage_preview,
            },
        )

        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)
        await _refresh_runtime(hass)

        hass.bus.async_fire(
            f"{DOMAIN}_document_deleted",
            {
                "asset_id": asset_id,
                "document_id": removed_document_id,
                "provider_document_id": removed_provider_document_id,
                "actor": actor,
            },
        )
        
    # -----------------------------
    # GET DOCUMENT INFO
    # -----------------------------
    async def handle_get_document_info(call: ServiceCall) -> Dict[str, Any]:
        store = _get_store(hass)
        document_storage = _get_document_storage(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        document_id = call.data.get("document_id")
        provider_document_id = call.data.get("provider_document_id")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        if not document_id and not provider_document_id:
            raise HomeAssistantError(
                "Provide document_id or provider_document_id"
            )

        asset = store.get(asset_id)
        if not asset:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        document_record = _find_document_record(
            asset,
            document_id=document_id,
            provider_document_id=provider_document_id,
        )
        if not document_record:
            raise HomeAssistantError("Document not found on asset")

        access_info = await hass.async_add_executor_job(
            lambda: document_storage.get_document_record_access_info(document_record)
        )

        response = {
            "asset_id": asset_id,
            "document_id": document_record.get("document_id"),
            "type": document_record.get("type"),
            "title": document_record.get("title"),
            "provider": access_info.get("provider"),
            "provider_document_id": access_info.get("provider_document_id"),
            "filename": access_info.get("filename"),
            "mime_type": access_info.get("mime_type"),
            "size_bytes": access_info.get("size_bytes"),
            "exists": access_info.get("exists"),
            "available": access_info.get("available"),
            "checksum": access_info.get("checksum"),
            "checksum_type": access_info.get("checksum_type"),
            "preview": access_info.get("preview"),
        }

        hass.bus.async_fire(
            f"{DOMAIN}_document_info_requested",
            {
                "asset_id": asset_id,
                "document_id": document_record.get("document_id"),
                "actor": actor,
            },
        )

        return response

    # -----------------------------
    # CHECK DOCUMENT AVAILABILITY
    # -----------------------------
    async def handle_check_document_availability(call: ServiceCall) -> Dict[str, Any]:
        store = _get_store(hass)
        document_storage = _get_document_storage(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        document_id = call.data.get("document_id")
        provider_document_id = call.data.get("provider_document_id")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        if not document_id and not provider_document_id:
            raise HomeAssistantError(
                "Provide document_id or provider_document_id"
            )

        asset = store.get(asset_id)
        if not asset:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        document_record = _find_document_record(
            asset,
            document_id=document_id,
            provider_document_id=provider_document_id,
        )
        if not document_record:
            raise HomeAssistantError("Document not found on asset")

        access_info = await hass.async_add_executor_job(
            lambda: document_storage.get_document_record_access_info(document_record)
        )

        response = {
            "asset_id": asset_id,
            "document_id": document_record.get("document_id"),
            "provider_document_id": access_info.get("provider_document_id"),
            "exists": access_info.get("exists"),
            "available": access_info.get("available"),
            "provider": access_info.get("provider"),
        }

        hass.bus.async_fire(
            f"{DOMAIN}_document_availability_checked",
            {
                "asset_id": asset_id,
                "document_id": document_record.get("document_id"),
                "available": access_info.get("available"),
                "actor": actor,
            },
        )

        return response

    # -----------------------------
    # ADD PHYSICAL DOCUMENT LOCATION
    # -----------------------------
    async def handle_add_physical_document_location(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        doc_type = call.data.get("type")
        location = call.data.get("location")
        notes = call.data.get("notes")
        document_id = call.data.get("document_id")
        provider_document_id = call.data.get("provider_document_id")
        title = call.data.get("title")

        if not location:
            raise HomeAssistantError("location is required (e.g., safe, binder, deposit_box)")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        now = _now_iso_local()

        # Resolve the target document record when provided; otherwise auto-create
        # a placeholder metadata document so physical originals always attach to a
        # canonical document entry.
        target_document = _find_document_record(
            updated,
            document_id=document_id,
            provider_document_id=provider_document_id,
        )

        documents = updated.get("documents", [])
        if not isinstance(documents, list):
            documents = []

        placeholder_created = False

        if target_document is None:
            if not doc_type:
                raise HomeAssistantError(
                    "type is required when creating a physical-only document record"
                )

            resolved_document_id = str(document_id).strip() if document_id else str(uuid.uuid4())
            resolved_provider_document_id = (
                str(provider_document_id).strip()
                if provider_document_id
                else f"physical_only/{asset_id}/{resolved_document_id}"
            )
            resolved_title = (
                str(title).strip()
                if isinstance(title, str) and title.strip()
                else f"{str(doc_type).replace('_', ' ').title()} (Physical Original)"
            )

            target_document = {
                "document_id": resolved_document_id,
                "type": doc_type,
                "title": resolved_title,
                "filename": f"{resolved_document_id}.physical",
                "provider": "physical_only",
                "provider_document_id": resolved_provider_document_id,
                "mime_type": None,
                "size_bytes": None,
                "tags": [],
                "metadata": {
                    "created_at": now,
                    "created_by": actor,
                    "physical_only": True,
                },
            }
            documents.append(target_document)
            placeholder_created = True
        else:
            # If type/title omitted, inherit from the existing document.
            if not doc_type:
                doc_type = target_document.get("type") or "other"
            if not title:
                title = target_document.get("title")

        target_document["type"] = doc_type or target_document.get("type") or "other"
        if title and not target_document.get("title"):
            target_document["title"] = title

        resolved_document_id = target_document.get("document_id")
        resolved_provider_document_id = target_document.get("provider_document_id")

        metadata = target_document.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        metadata["physical_exists"] = True
        metadata["physical_location"] = location
        metadata["physical_notes"] = notes or ""
        metadata["physical_recorded_at"] = now
        metadata["physical_recorded_by"] = actor
        target_document["metadata"] = metadata

        # Persist target document updates back into the documents list.
        updated_documents: list[Dict[str, Any]] = []
        target_replaced = False
        for item in documents:
            if not isinstance(item, dict):
                continue

            is_target = False
            if resolved_document_id and item.get("document_id") == resolved_document_id:
                is_target = True
            elif resolved_provider_document_id and item.get("provider_document_id") == resolved_provider_document_id:
                is_target = True

            if is_target and not target_replaced:
                updated_documents.append(target_document)
                target_replaced = True
            else:
                updated_documents.append(item)

        if not target_replaced:
            updated_documents.append(target_document)

        updated["documents"] = updated_documents

        physical_entry = {
            "type": doc_type,
            "location": location,
            "notes": notes or "",
            "description": notes or "",
            "document_id": resolved_document_id,
            "provider_document_id": resolved_provider_document_id,
            "title": title or target_document.get("title"),
            "recorded_at": now,
            "recorded_by": actor,
        }

        updated.setdefault("physical_documents", [])
        existing_entries = updated.get("physical_documents", [])
        if not isinstance(existing_entries, list):
            existing_entries = []

        merged_entries: list[Dict[str, Any]] = []
        replaced = False
        for entry in existing_entries:
            if not isinstance(entry, dict):
                continue

            same_document = False
            if document_id and entry.get("document_id") == document_id:
                same_document = True
            elif provider_document_id and entry.get("provider_document_id") == provider_document_id:
                same_document = True

            if same_document:
                merged_entries.append({**entry, **physical_entry})
                replaced = True
            else:
                merged_entries.append(entry)

        if not replaced:
            merged_entries.append(physical_entry)

        updated["physical_documents"] = merged_entries

        updated["updated_at"] = now
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "add_physical_document_location",
            actor,
            {
                **physical_entry,
                "placeholder_document_created": placeholder_created,
            },
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_physical_document_added",
            {
                "asset_id": asset_id,
                "type": doc_type,
                "location": location,
                "document_id": resolved_document_id,
                "provider_document_id": resolved_provider_document_id,
                "actor": actor,
            },
        )

    # -----------------------------
    # SET ENVIRONMENT REQUIREMENTS
    # -----------------------------
    async def handle_set_environment_requirements(call: ServiceCall) -> None:
        """Set canonical environment requirements for an asset."""
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        incoming_requirements = call.data.get("environment_requirements")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        if incoming_requirements is None:
            raise HomeAssistantError("environment_requirements is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        existing_requirements = updated.get("environment_requirements")
        merged_requirements = _merge_environment_requirements(
            existing=existing_requirements,
            incoming=incoming_requirements,
        )

        environment_field_changes = _build_field_changes(
            existing_requirements or {},
            merged_requirements,
        )

        updated["environment_requirements"] = merged_requirements

        # Remove legacy field if it still exists from earlier schema revisions.
        if "environment" in updated:
            updated.pop("environment", None)

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "set_environment_requirements",
            actor,
            {
                "changed_fields": list(environment_field_changes.keys()),
                "field_changes": environment_field_changes,
                "change_count": len(environment_field_changes),
            },
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        await hass.async_block_till_done()
        hass.bus.async_fire(
            f"{DOMAIN}_environment_requirements_set",
            {
                "asset_id": asset_id,
                "actor": actor,
            },
        )

    # -----------------------------
    # SET ROOM ENVIRONMENT CONFIG
    # -----------------------------
    async def handle_set_room_environment(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        area_id = call.data.get("area_id")
        config = call.data.get("environment_config")
        windows = call.data.get("windows")   # ✅ NEW

        if not area_id:
            raise HomeAssistantError("area_id is required")

        if config is None:
            raise HomeAssistantError("environment_config is required")

        try:
            validate_room_environment_config(config)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Room environment validation failed: {ex}") from ex

        # ✅ existing behavior (correct)
        await store.set_room_environment(area_id, config)

        # ✅ NEW: persist windows correctly using proper API
        if isinstance(windows, list):
            await store.set_room_windows(area_id, windows)

        await _refresh_runtime(hass)

        hass.bus.async_fire(
            f"{DOMAIN}_room_environment_set",
            {
                "area_id": area_id,
                "actor": actor,
            },
        )

    # -----------------------------
    # SET CUSTODY STATUS
    # -----------------------------
    async def handle_set_custody_status(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        status = call.data.get("status")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        if not status:
            raise HomeAssistantError("status is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        prior_custody = updated.get("custody") or {}
        prior_status = prior_custody.get("status") if isinstance(prior_custody, dict) else None

        now = _now_iso_local()

        custody = dict(prior_custody) if isinstance(prior_custody, dict) else {}
        custody["status"] = status

        notes = call.data.get("notes")
        holder = call.data.get("holder")
        location_detail = call.data.get("location_detail")
        effective_at = call.data.get("effective_at")

        if notes is not None:
            custody["notes"] = notes
        if holder is not None:
            custody["holder"] = holder
        if location_detail is not None:
            custody["location_detail"] = location_detail

        custody["effective_at"] = effective_at or now

        updated["custody"] = custody
        updated["updated_at"] = now
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        custody_field_changes = _build_field_changes(prior_custody or {}, custody)

        _append_audit(
            updated,
            "set_custody_status",
            actor,
            {
                "from_status": prior_status,
                "to_status": status,
                "changed_fields": list(custody_field_changes.keys()),
                "field_changes": custody_field_changes,
                "change_count": len(custody_field_changes),
            },
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_custody_status_set",
            {
                "asset_id": asset_id,
                "status": status,
                "from_status": prior_status,
                "actor": actor,
            },
        )

    # -----------------------------
    # RECORD LOAN OUT
    # -----------------------------
    async def handle_record_loan_out(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        counterparty = call.data.get("counterparty")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        if not counterparty:
            raise HomeAssistantError("counterparty is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        loans = updated.get("loans", [])
        if loans is None:
            loans = []
        if not isinstance(loans, list):
            raise HomeAssistantError("Asset loans field is not a list; cannot record loan")

        now = _now_iso_local()
        start_date = call.data.get("start_date") or now
        expected_return_date = call.data.get("expected_return_date")

        loan_id = f"loan_{uuid.uuid4().hex[:10]}"

        loan = {
            "loan_id": loan_id,
            "direction": "out",
            "state": "active",
            "counterparty": counterparty,
            "start_date": start_date,
            "expected_return_date": expected_return_date,
            "actual_return_date": None,
            "purpose": call.data.get("purpose"),
            "location_detail": call.data.get("location_detail"),
            "agreement_uri": call.data.get("agreement_uri"),
            "insurance_responsibility": call.data.get("insurance_responsibility"),
            "notes": call.data.get("notes"),
            "recorded_at": now,
            "recorded_by": actor,
        }

        updated["loans"] = list(loans)
        updated["loans"].append(loan)

        custody = dict(updated.get("custody") or {})
        custody["status"] = "on_loan_out"
        custody["holder"] = counterparty
        if call.data.get("location_detail") is not None:
            custody["location_detail"] = call.data.get("location_detail")
        if call.data.get("notes") is not None:
            custody["notes"] = call.data.get("notes")
        custody["effective_at"] = start_date

        updated["custody"] = custody
        updated["updated_at"] = now
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "record_loan_out",
            actor,
            {"loan_id": loan_id, "counterparty": counterparty},
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_loan_recorded_out",
            {
                "asset_id": asset_id,
                "loan_id": loan_id,
                "counterparty": counterparty,
                "actor": actor,
            },
        )

    # -----------------------------
    # RECORD LOAN IN
    # -----------------------------
    async def handle_record_loan_in(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        loans = updated.get("loans", [])
        if loans is None:
            loans = []
        if not isinstance(loans, list):
            raise HomeAssistantError("Asset loans field is not a list; cannot record loan return")

        loan_id = call.data.get("loan_id")
        now = _now_iso_local()
        actual_return_date = call.data.get("actual_return_date") or now

        active_out = _find_active_loan_out(loans)

        if loan_id:
            if not any(l.get("loan_id") == loan_id for l in active_out):
                raise HomeAssistantError(f"No active loan_out found with loan_id '{loan_id}'")
        else:
            if len(active_out) == 1:
                loan_id = active_out[0].get("loan_id")
            elif len(active_out) == 0:
                raise HomeAssistantError("No active loan_out found to close for this asset")
            else:
                raise HomeAssistantError("Multiple active loan_out records found; provide loan_id")

        new_loans = []
        for loan in loans:
            if isinstance(loan, dict) and loan.get("loan_id") == loan_id:
                closed = dict(loan)
                closed["state"] = "returned"
                closed["actual_return_date"] = actual_return_date
                if call.data.get("notes") is not None:
                    closed["return_notes"] = call.data.get("notes")
                if call.data.get("return_location_detail") is not None:
                    closed["return_location_detail"] = call.data.get("return_location_detail")
                closed["closed_at"] = now
                closed["closed_by"] = actor
                new_loans.append(closed)
            else:
                new_loans.append(loan)

        updated["loans"] = new_loans

        return_status = call.data.get("return_status") or "owned_on_site"
        custody = dict(updated.get("custody") or {})
        custody["status"] = return_status
        custody["holder"] = None
        if call.data.get("return_location_detail") is not None:
            custody["location_detail"] = call.data.get("return_location_detail")
        if call.data.get("notes") is not None:
            custody["notes"] = call.data.get("notes")
        custody["effective_at"] = actual_return_date

        updated["custody"] = custody
        updated["updated_at"] = now
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(
            updated,
            "record_loan_in",
            actor,
            {"loan_id": loan_id, "actual_return_date": actual_return_date},
        )
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_loan_recorded_in",
            {"asset_id": asset_id, "loan_id": loan_id, "actor": actor},
        )

    # -----------------------------
    # ADD TRACKER (entity_id-based)
    # -----------------------------
    async def handle_add_tracker(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        entity_id = call.data.get("entity_id")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        if not entity_id:
            raise HomeAssistantError("entity_id is required")

        state = hass.states.get(entity_id)
        if state is None:
            raise HomeAssistantError(f"entity_id '{entity_id}' not found")

        if not isinstance(entity_id, str) or not entity_id.startswith("device_tracker."):
            raise HomeAssistantError("entity_id must be a device_tracker entity")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        tracker_entry = {
            "entity_id": entity_id,
            "name": call.data.get("name"),
            "notes": call.data.get("notes"),
            "attached_at": _now_iso_local(),
        }

        updated["trackers"] = [tracker_entry]

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(updated, "add_tracker", actor, {"entity_id": entity_id})
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_tracker_added",
            {"asset_id": asset_id, "entity_id": entity_id, "actor": actor},
        )

    # -----------------------------
    # REMOVE TRACKER (entity_id-based)
    # -----------------------------
    async def handle_remove_tracker(call: ServiceCall) -> None:
        store = _get_store(hass)
        actor = await _resolve_actor(hass, call)

        asset_id = call.data.get("asset_id")
        entity_id = call.data.get("entity_id")

        if not asset_id:
            raise HomeAssistantError("asset_id is required")
        if not entity_id:
            raise HomeAssistantError("entity_id is required")

        existing = store.get(asset_id)
        if not existing:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        updated = dict(existing)
        _ensure_system_of_record_fields(updated)

        trackers = updated.get("trackers", [])
        if not isinstance(trackers, list):
            trackers = []

        new_trackers = []
        found = False
        for tracker in trackers:
            if isinstance(tracker, dict) and tracker.get("entity_id") == entity_id:
                found = True
                continue
            new_trackers.append(tracker)

        if not found:
            raise HomeAssistantError(f"Tracker '{entity_id}' not found on asset")

        updated["trackers"] = new_trackers

        updated["updated_at"] = _now_iso_local()
        updated["updated_by"] = actor
        updated.setdefault("created_by", existing.get("created_by"))

        _append_audit(updated, "remove_tracker", actor, {"entity_id": entity_id})
        _rebuild_document_summary(updated)

        try:
            validate_asset_payload(updated)
        except AssetValidationError as ex:
            raise HomeAssistantError(f"Asset validation failed: {ex}") from ex

        await store.add_or_replace(updated)

        await _refresh_runtime(hass)
        hass.bus.async_fire(
            f"{DOMAIN}_tracker_removed",
            {"asset_id": asset_id, "entity_id": entity_id, "actor": actor},
        )

    # -----------------------------
    # TRACKER STATE CHANGE LISTENER
    # -----------------------------
    async def handle_tracker_state_change(event: Event) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        if not entity_id or not new_state:
            return

        if not isinstance(entity_id, str) or not entity_id.startswith("device_tracker."):
            return

        try:
            store = _get_store(hass)
        except HomeAssistantError:
            return

        for asset_id, asset in store.assets.items():
            trackers = asset.get("trackers", [])
            if not isinstance(trackers, list):
                continue

            for tracker in trackers:
                if not isinstance(tracker, dict):
                    continue

                if tracker.get("entity_id") == entity_id:
                    updated = dict(asset)
                    _ensure_system_of_record_fields(updated)

                    updated["last_seen_tracker_state"] = new_state.state
                    updated["updated_at"] = _now_iso_local()
                    updated["updated_by"] = "system"

                    _append_audit(
                        updated,
                        "tracker_state_update",
                        "system",
                        {"entity_id": entity_id, "new_state": new_state.state},
                    )

                    _rebuild_document_summary(updated)

                    await store.add_or_replace(updated)
                    await _refresh_runtime(hass)

                    hass.bus.async_fire(
                        f"{DOMAIN}_tracker_state_updated",
                        {
                            "asset_id": asset_id,
                            "entity_id": entity_id,
                            "state": new_state.state,
                        },
                    )
                    return

    async def handle_get_asset_history(call: ServiceCall) -> Dict[str, Any]:
        store = _get_store(hass)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        max_entries_raw = call.data.get("max_entries", 80)
        try:
            max_entries = max(1, min(int(max_entries_raw), 200))
        except Exception:
            max_entries = 80

        asset = store.get(asset_id)
        if not asset:
            return _empty_asset_history_payload(str(asset_id))

        payload = _build_asset_history_payload(asset, max_entries=max_entries)
        payload["asset_id"] = str(asset_id)
        payload["found"] = True
        return payload

    # -----------------------------
    # EXPORT INVENTORY (Insurance Addendum)
    # -----------------------------
    async def handle_export_inventory(call: ServiceCall) -> None:
        store = _get_store(hass)
        _actor = await _resolve_actor(hass, call)

        fmt = (call.data.get("format") or "csv").strip().lower()
        if fmt not in ("csv", "json"):
            raise HomeAssistantError("format must be 'csv' or 'json'")

        export_dir = "/tmp/asset_intelligence"
        ts = dt_util.now().strftime("%Y%m%d_%H%M%S")
        filename = call.data.get("filename") or f"insurance_addendum_{ts}.{fmt}"

        if not filename.lower().endswith(f".{fmt}"):
            filename = f"{filename}.{fmt}"

        out_path = os.path.join(export_dir, filename)

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        def registry_metadata(asset_id_value: str) -> tuple[str | None, str]:
            area_id: str | None = None
            labels: set[str] = set()

            device = device_registry.async_get_device({(DOMAIN, str(asset_id_value))})
            if device:
                area_id = device.area_id
                labels.update(str(label) for label in (getattr(device, "labels", None) or []) if label)

            tracked_entities = (
                ("sensor", f"{DOMAIN}_{asset_id_value}"),
                ("binary_sensor", f"{DOMAIN}_{asset_id_value}_at_risk"),
            )
            for platform, unique_id in tracked_entities:
                entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)
                if not entity_id:
                    continue
                entry = entity_registry.async_get(entity_id)
                if entry:
                    labels.update(str(label) for label in (getattr(entry, "labels", None) or []) if label)

            return area_id, ",".join(sorted(labels))

        rows = []

        for asset_id, asset in store.assets.items():
            if not isinstance(asset, dict):
                continue

            resolved_area_id, resolved_labels = registry_metadata(asset.get("asset_id") or asset_id)

            insurance = asset.get("insurance") or {}
            policy = insurance.get("policy")
            insured = bool(policy and str(policy).strip())

            rows.append(
                {
                    "asset_id": asset.get("asset_id") or asset_id,
                    "name": asset.get("name"),
                    "location": resolved_area_id,
                    "asset_type": asset.get("asset_type"),
                    "labels": resolved_labels,
                    "created_at": asset.get("created_at"),
                    "updated_at": asset.get("updated_at"),
                    "policy": policy,
                    "insured": insured,
                    "last_seen_tracker_state": asset.get("last_seen_tracker_state"),
                }
            )

        def _write_export() -> None:
            os.makedirs(export_dir, exist_ok=True)
            if fmt == "json":
                with open(out_path, "w", encoding="utf-8") as file_handle:
                    json.dump(rows, file_handle, indent=2)
            else:
                fieldnames = list(rows[0].keys()) if rows else []
                with open(out_path, "w", newline="", encoding="utf-8") as file_handle:
                    writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)

        await hass.async_add_executor_job(_write_export)

        download_url = f"/tmp/asset_intelligence/{filename}"

        hass.bus.async_fire(
            f"{DOMAIN}_inventory_exported",
            {
                "download_url": download_url,
                "filename": filename,
                "count": len(rows),
            },
        )

        async def cleanup() -> None:
            await asyncio.sleep(60)
            if os.path.exists(out_path):
                await hass.async_add_executor_job(os.remove, out_path)

        hass.async_create_task(cleanup())

    # -----------------------------
    # Start and Stop Measurements
    # -----------------------------
    async def handle_start_measurement(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        asset = coordinator.get_asset_record(asset_id)
        if not asset:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        measurement = asset.get("active_measurement")
        if not isinstance(measurement, dict):
            measurement = {}

        now_iso = coordinator._utcnow_iso()

        measurement["started_at"] = now_iso
        measurement["completed"] = False
        measurement["completed_at"] = None
        measurement["stop_requested"] = False
        measurement["stop_requested_at"] = None
        measurement["observations"] = []
        measurement["last_observation_at"] = None

        # Optional sensor override support placeholder
        sensors = call.data.get("sensors")
        measurement["sensors"] = sensors if isinstance(sensors, list) else []

        asset["active_measurement"] = measurement

        await coordinator.store.async_save()
        await coordinator.async_request_refresh()

    async def handle_stop_measurement(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)

        asset_id = call.data.get("asset_id")
        if not asset_id:
            raise HomeAssistantError("asset_id is required")

        asset = coordinator.get_asset_record(asset_id)
        if not asset:
            raise HomeAssistantError(f"Asset '{asset_id}' not found")

        measurement = asset.get("active_measurement")
        if not isinstance(measurement, dict):
            raise HomeAssistantError("No active measurement session")

        now_iso = coordinator._utcnow_iso()

        measurement["stop_requested"] = True
        measurement["stop_requested_at"] = now_iso

        asset["active_measurement"] = measurement

        await coordinator.store.async_save()
        await coordinator.async_request_refresh()



    # Register tracker listener ONCE
    unsub = hass.bus.async_listen("state_changed", handle_tracker_state_change)
    hass.data[DOMAIN][DATA_TRACKER_LISTENER_UNSUB] = unsub

    # Register document render API ONCE
    _ensure_document_view_registered(hass)

    # Register services ONCE
    hass.services.async_register(DOMAIN, "add_asset", handle_add_asset)
    hass.services.async_register(DOMAIN, "update_asset", handle_update_asset)
    hass.services.async_register(DOMAIN, "delete_asset", handle_delete_asset)

    hass.services.async_register(DOMAIN, "link_to_device", handle_link_to_device)
    hass.services.async_register(DOMAIN, "unlink_from_device", handle_unlink_from_device)

    hass.services.async_register(DOMAIN, "add_tracker", handle_add_tracker)
    hass.services.async_register(DOMAIN, "remove_tracker", handle_remove_tracker)

    hass.services.async_register(
        DOMAIN,
        "configure_document_storage",
        handle_configure_document_storage,
    )
    hass.services.async_register(DOMAIN, "upload_document", handle_upload_document)
    
    hass.services.async_register(
            DOMAIN,
            "attach_document",
            handle_attach_document,
        )
    hass.services.async_register(
        DOMAIN,
        "update_document_metadata",
        handle_update_document_metadata,
    )
    hass.services.async_register(DOMAIN, "delete_document", handle_delete_document)

    hass.services.async_register(
        DOMAIN,
        "get_document_info",
        handle_get_document_info,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "check_document_availability",
        handle_check_document_availability,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_asset_history",
        handle_get_asset_history,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        "add_physical_document_location",
        handle_add_physical_document_location,
    )
    hass.services.async_register(
        DOMAIN,
        "set_environment_requirements",
        handle_set_environment_requirements,
    )
    hass.services.async_register(DOMAIN, "set_room_environment", handle_set_room_environment)
    hass.services.async_register(DOMAIN, "set_custody_status", handle_set_custody_status)
    hass.services.async_register(DOMAIN, "record_loan_out", handle_record_loan_out)
    hass.services.async_register(DOMAIN, "record_loan_in", handle_record_loan_in)
    hass.services.async_register(DOMAIN, "export_inventory", handle_export_inventory)
    hass.services.async_register(DOMAIN, "start_measurement", handle_start_measurement)
    hass.services.async_register(DOMAIN, "stop_measurement", handle_stop_measurement)

    hass.data[DOMAIN][DATA_SERVICES_REGISTERED] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from config entry."""
    options = entry.options or {}

    # ==============================
    # STORAGE INITIALIZATION
    # ==============================
    if options.get("initialize_storage", True) and callable(async_ensure_storage):
        await async_ensure_storage(hass, options)
    elif options.get("initialize_storage", True):
        _LOGGER.debug("Asset Intelligence: async_ensure_storage not available; skipping filesystem initialization")

    try:
        store = AssetStore(hass)

        await store.async_load()

        options = entry.options or {}

        # Preserve any previously persisted document storage config and only
        # override fields when the config entry explicitly provides them.
        existing_doc_config = store.get_document_storage_config()

        # Start with existing config (may be empty/defaults) and apply
        # overrides from the config entry only when present.
        config = dict(existing_doc_config or {})
        # Ensure provider has a sensible default
        config["provider"] = config.get("provider") or "filesystem"

        if "document_storage_path" in options and options.get("document_storage_path") is not None:
            config["root_path"] = _normalize_storage_path(
                options.get("document_storage_path")
            )

        if "documents_enabled" in options:
            config["documents_enabled"] = bool(options.get("documents_enabled"))

        if "require_network_storage" in options:
            config["requires_network_storage"] = bool(
                options.get("require_network_storage")
            )

        system_defaults = dict(getattr(store, "system_defaults", {}) or {})
        system_defaults["default_label_ids"] = list(
            options.get("default_label_ids") or []
        )
        store.system_defaults = system_defaults

        root_path = _normalize_storage_path(config.get("root_path"))
        config["root_path"] = root_path

        # documents_enabled reflects the user's configured intent (from options).
        # It is NOT overridden by a live filesystem check here — that would cause
        # the flag to flip off whenever the NAS/share isn't reachable at boot.
        # Runtime availability is evaluated separately below via is_available().
        if "documents_enabled" not in config:
            config["documents_enabled"] = bool(root_path)

        # Only persist if the computed config differs from what we already have.
        if config != existing_doc_config:
            await store.set_document_storage_config(config)
        else:
            _LOGGER.debug("Asset Intelligence: existing document storage config retained")

        coordinator = AssetIntelligenceCoordinator(hass, store)

        await coordinator.async_config_entry_first_refresh()

        hass.data.setdefault(DOMAIN, {})
        _ensure_document_view_registered(hass)
        # Initialize document storage runtime now so we can check availability
        document_storage = DocumentStorage(hass, store.get_document_storage_config())
        runtime_obj = {
            "store": store,
            "coordinator": coordinator,
            "document_storage": document_storage,
            "document_storage_available": bool(False),
        }

        # Evaluate availability at startup and store result for quick access
        try:
            runtime_obj["document_storage_available"] = bool(document_storage.is_available())
        except Exception:
            runtime_obj["document_storage_available"] = False

        # Notify listeners about initial availability state
        try:
            async_dispatcher_send(hass, SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED, runtime_obj["document_storage_available"])
        except Exception:
            pass

        try:
            hass.bus.async_fire(
                f"{DOMAIN}_document_storage_availability_changed",
                {"available": runtime_obj["document_storage_available"]},
            )
        except Exception:
            pass

        entry.runtime_data = runtime_obj

        # ---------------------------------------------------------
        # Phase 6.7 — Document Retrieval Services
        # ---------------------------------------------------------

        async def async_handle_get_asset_documents(call):
            """Handle service call: get all documents for an asset."""
            asset_id = call.data.get("asset_id")

            runtime = getattr(entry, "runtime_data", None)
            if not isinstance(runtime, dict):
                raise HomeAssistantError("Asset Intelligence runtime is not available.")

            coordinator = runtime["coordinator"]

            result = await coordinator.async_get_asset_documents(asset_id)

            return {
                "asset_id": asset_id,
                "resolved_count": result.resolved_count,
                "unresolved_count": result.unresolved_count,
                "total_count": result.total_count,
                "documents": [doc.as_dict() for doc in result.resolved],
            }

        async def async_handle_get_document_by_id(call):
            """Handle service call: get a single document."""
            asset_id = call.data.get("asset_id")
            document_id = call.data.get("document_id")

            runtime = getattr(entry, "runtime_data", None)
            if not isinstance(runtime, dict):
                raise HomeAssistantError("Asset Intelligence runtime is not available.")

            coordinator = runtime["coordinator"]

            result = await coordinator.async_get_asset_document(
                asset_id,
                document_id,
            )

            return result.as_dict()

        hass.services.async_register(
            DOMAIN,
            "get_asset_documents",
            async_handle_get_asset_documents,
            supports_response=True,
        )

        hass.services.async_register(
            DOMAIN,
            "get_document_by_id",
            async_handle_get_document_by_id,
            supports_response=True,
        )



        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        async_dispatcher_send(hass, SIGNAL_ASSETS_UPDATED)

        await async_setup_panel(hass)

        # ------------------------------------------------------------------
        # OPTIONS UPDATE LISTENER
        # Rebuild the runtime DocumentStorage object whenever the user saves
        # new settings via the integration gear, then notify listeners so the
        # binary sensor and frontend update immediately without a restart.
        # ------------------------------------------------------------------
        async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
            """Handle options update."""
            try:
                runtime = getattr(entry, "runtime_data", None)
                if not runtime:
                    return

                updated_options = entry.options or {}
                store = runtime.get("store")
                if not isinstance(store, AssetStore):
                    return

                # Re-apply option overrides into the stored document config.
                existing = store.get_document_storage_config()
                config = dict(existing or {})
                config["provider"] = config.get("provider") or "filesystem"

                if "document_storage_path" in updated_options:
                    config["root_path"] = _normalize_storage_path(
                        updated_options.get("document_storage_path") or ""
                    )

                if "documents_enabled" in updated_options:
                    config["documents_enabled"] = bool(updated_options["documents_enabled"])

                system_defaults = dict(getattr(store, "system_defaults", {}) or {})
                system_defaults["default_label_ids"] = list(
                    updated_options.get("default_label_ids") or []
                )
                store.system_defaults = system_defaults

                # If path was cleared force disable regardless of switch.
                if not config.get("root_path"):
                    config["documents_enabled"] = False

                await store.set_document_storage_config(config)

                # Rebuild the runtime DocumentStorage instance with fresh config.
                new_doc_storage = DocumentStorage(hass, store.get_document_storage_config())
                runtime["document_storage"] = new_doc_storage

                try:
                    available = bool(new_doc_storage.is_available())
                except Exception:
                    available = False

                runtime["document_storage_available"] = available

                # Notify binary sensor and frontend.
                async_dispatcher_send(
                    hass,
                    SIGNAL_DOCUMENT_STORAGE_AVAILABILITY_CHANGED,
                    available,
                )
                hass.bus.async_fire(
                    f"{DOMAIN}_document_storage_availability_changed",
                    {"available": available},
                )
                async_dispatcher_send(hass, SIGNAL_ASSETS_UPDATED)

                _LOGGER.debug(
                    "Asset Intelligence: document storage config updated via options: enabled=%s available=%s",
                    config.get("documents_enabled"),
                    available,
                )
            except Exception:
                _LOGGER.exception("Asset Intelligence: options update handler failed")

        entry.add_update_listener(_async_options_updated)

        return True

    except Exception:
        _LOGGER.exception("Asset Intelligence: async_setup_entry failed")
        raise

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload integration entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry.runtime_data = None
        runtimes = _iter_runtimes(hass)
        if not runtimes:
            unsub = hass.data.get(DOMAIN, {}).pop(DATA_TRACKER_LISTENER_UNSUB, None)
            if callable(unsub):
                unsub()

            if hass.data.get(DOMAIN, {}).get(DATA_SERVICES_REGISTERED):
                for service_name in REGISTERED_SERVICES:
                    if hass.services.has_service(DOMAIN, service_name):
                        hass.services.async_remove(DOMAIN, service_name)

                hass.data.get(DOMAIN, {}).pop(DATA_SERVICES_REGISTERED, None)

    return unload_ok