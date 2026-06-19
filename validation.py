from __future__ import annotations
from datetime import date, datetime
from typing import Any
from .const import (
    ENVIRONMENT_SECTIONS,
    NUMERIC_SIGNALS,
    BINARY_SIGNALS,
    VALID_AGGREGATIONS,
)

# ===========================================================
# ERROR
# ===========================================================
class AssetValidationError(Exception):
    """Raised when validation fails."""
    pass

# ===========================================================
# CONSTANTS
# ===========================================================
_ALLOWED_DOC_TYPES = {
    "photo",
    "receipt",
    "invoice",
    "warranty",
    "manual",
    "appraisal",
    "insurance_policy",
    "certificate_of_authenticity",
    "provenance_record",
    "condition_report",
    "restoration_record",
    "loan_agreement",
    "shipping_document",
    "installation_instructions",
    "maintenance_record",
    "other",
}
_ALLOWED_PHYSICAL_DOC_LOCATIONS = {
    "safe",
    "safe_deposit_box",
    "binder",
    "offsite_archive",
    "with_agent",
    "bank",
    "other",
}
_ALLOWED_TRACKER_TYPES = {"BLE", "RFID", "NFC", "UWB", "other"}
_ALLOWED_CUSTODY_STATUS = {
    "owned_on_site",
    "owned_off_site",
    "on_loan_out",
    "on_loan_in",
    "in_storage",
    "in_transit",
    "sold",
    "donated",
    "unknown",
}
_ALLOWED_ASSET_TYPES = {
    None,
    "artwork",
    "rare_book",
    "collectable",
    "electronics",
    "infrastructure",
    "furniture",
    "instrument",
}
_ALLOWED_LOAN_DIRECTIONS = {"out"}
_ALLOWED_LOAN_STATES = {"active", "returned"}

# ===========================================================
# BASIC VALIDATORS
# ===========================================================
def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    text = value.strip()
    if not text:
        return False

    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        pass

    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False

def _validate_numeric(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)):
        raise AssetValidationError(f"{field} must be a number")

def _validate_bool(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, bool):
        raise AssetValidationError(f"{field} must be a boolean")

def _validate_list_of_strings(value: Any, field: str) -> None:
    if not isinstance(value, list):
        raise AssetValidationError(f"{field} must be a list")
    if any(not isinstance(v, str) for v in value):
        raise AssetValidationError(f"{field} must contain strings")

# ===========================================================
# ENTITY VALIDATION
# ===========================================================
def _validate_entity_list(entity_ids: Any, field: str) -> None:
    if not isinstance(entity_ids, list):
        raise AssetValidationError(f"{field} must be a list")
    for e in entity_ids:
        if not isinstance(e, str):
            raise AssetValidationError(f"{field} must contain strings")

def _validate_entity_domain(entity_ids: List[str], expected: str, field: str) -> None:
    for entity_id in entity_ids:
        if not entity_id.startswith(f"{expected}."):
            raise AssetValidationError(f"{field} must contain only {expected} entities")

def _validate_aggregation(signal: str, cfg: Dict[str, Any]) -> None:
    agg = cfg.get("aggregation")
    if agg is None:
        return
    if signal in BINARY_SIGNALS:
        return
    if agg not in VALID_AGGREGATIONS:
        raise AssetValidationError(
            f"{signal}.aggregation must be one of {VALID_AGGREGATIONS}"
        )

# ===========================================================
# CANONICAL ROOM ENVIRONMENT VALIDATION
# ===========================================================
def validate_room_environment_config(config: Dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise AssetValidationError("environment_config must be an object")
    for section, signals in config.items():
        if section not in ENVIRONMENT_SECTIONS:
            raise AssetValidationError(f"Invalid section: {section}")
        if not isinstance(signals, dict):
            raise AssetValidationError(f"{section} must be an object")
        for signal, cfg in signals.items():
            if signal not in ENVIRONMENT_SECTIONS[section]:
                raise AssetValidationError(f"Invalid signal: {section}.{signal}")
            if not isinstance(cfg, dict):
                raise AssetValidationError(f"{section}.{signal} must be an object")
            entities = cfg.get("source_entities", [])
            _validate_entity_list(entities, f"{section}.{signal}.source_entities")
            if signal in BINARY_SIGNALS:
                _validate_entity_domain(
                    entities,
                    "binary_sensor",
                    f"{section}.{signal}.source_entities",
                )
            else:
                _validate_entity_domain(
                    entities,
                    "sensor",
                    f"{section}.{signal}.source_entities",
                )
            _validate_aggregation(signal, cfg)

# ===========================================================
# ASSET VALIDATION
# ===========================================================
def validate_asset_payload(data: Dict[str, Any]) -> None:
    # -------------------------------
    # CORE
    # -------------------------------
    if not data.get("asset_id"):
        raise AssetValidationError("asset_id is required")
    if not data.get("name"):
        raise AssetValidationError("name is required")
    labels = data.get("labels", [])
    if labels is not None:
        _validate_list_of_strings(labels, "labels")
    qty = data.get("quantity", 1)
    if not isinstance(qty, int) or qty < 1:
        raise AssetValidationError("quantity must be >= 1")
    asset_type = data.get("asset_type")
    if asset_type not in _ALLOWED_ASSET_TYPES:
        raise AssetValidationError(f"invalid asset_type: {asset_type}")
    # -------------------------------
    # PURCHASE
    # -------------------------------
    purchase = data.get("purchase")
    if isinstance(purchase, dict):
        price = purchase.get("purchase_price")
        if price is not None and price < 0:
            raise AssetValidationError("purchase.purchase_price cannot be negative")
        purchase_date = purchase.get("purchase_date")
        if purchase_date and not _is_iso_date(purchase_date):
            raise AssetValidationError(
                "purchase.purchase_date must look like ISO date"
            )
    # -------------------------------
    # VALUATION
    # -------------------------------
    valuation = data.get("valuation")
    if isinstance(valuation, dict):
        value = valuation.get("replacement_value")
        if value is not None and value < 0:
            raise AssetValidationError(
                "valuation.replacement_value cannot be negative"
            )
    # ===========================================================
    # ✅ DIGITAL DOCUMENTS (CANONICAL ONLY)
    # ===========================================================
    raw_docs = data.get("documents")
    docs = raw_docs if isinstance(raw_docs, list) else []
    seen_ids = set()
    for d in docs:
        if not isinstance(d, dict):
            raise AssetValidationError("each document must be an object")
        document_id = d.get("document_id")
        if not document_id:
            raise AssetValidationError("document_id is required for each document")
        if document_id in seen_ids:
            raise AssetValidationError("duplicate document_id detected")
        seen_ids.add(document_id)
        doc_type = d.get("type")
        if not doc_type:
            raise AssetValidationError("type is required for each document")
        if doc_type not in _ALLOWED_DOC_TYPES:
            raise AssetValidationError(f"invalid document type: {doc_type}")
        filename = d.get("filename")
        if not filename or not isinstance(filename, str):
            raise AssetValidationError("filename is required and must be a string")
        provider_doc_id = d.get("provider_document_id")
        if not provider_doc_id or not isinstance(provider_doc_id, str):
            raise AssetValidationError(
                "provider_document_id is required and must be a string"
            )
        if "size_bytes" in d:
            _validate_numeric(d.get("size_bytes"), "documents.size_bytes")
        if "tags" in d:
            _validate_list_of_strings(d.get("tags"), "documents.tags")
        metadata = d.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise AssetValidationError("documents.metadata must be an object")
    # ===========================================================
    # PHYSICAL DOCUMENTS
    # ===========================================================
    pdocs = data.get("physical_documents", [])
    if pdocs is not None:
        if not isinstance(pdocs, list):
            raise AssetValidationError("physical_documents must be a list")
        for d in pdocs:
            if not isinstance(d, dict):
                raise AssetValidationError(
                    "each physical document must be an object"
                )
            if not d.get("type"):
                raise AssetValidationError(
                    "physical document must include type"
                )
            if not d.get("location"):
                raise AssetValidationError(
                    "physical document must include location"
                )
            if d["type"] not in _ALLOWED_DOC_TYPES:
                raise AssetValidationError(
                    f"invalid physical document type: {d['type']}"
                )
            if d["location"] not in _ALLOWED_PHYSICAL_DOC_LOCATIONS:
                raise AssetValidationError(
                    f"invalid physical document location: {d['location']}"
                )
    # ===========================================================
    # ENVIRONMENT REQUIREMENTS
    # ===========================================================
    env = data.get("environment")
    if env is not None:
        if not isinstance(env, dict):
            raise AssetValidationError("environment must be an object")
        for section, signals in env.items():
            if section not in ENVIRONMENT_SECTIONS:
                raise AssetValidationError(
                    f"Invalid environment section: {section}"
                )
            if not isinstance(signals, dict):
                raise AssetValidationError(f"{section} must be an object")
            for signal, limits in signals.items():
                if signal not in ENVIRONMENT_SECTIONS[section]:
                    raise AssetValidationError(
                        f"Invalid signal: {section}.{signal}"
                    )
                if not isinstance(limits, dict):
                    raise AssetValidationError(
                        f"{section}.{signal} must be an object"
                    )
                _validate_numeric(limits.get("min"), f"{section}.{signal}.min")
                _validate_numeric(limits.get("max"), f"{section}.{signal}.max")
