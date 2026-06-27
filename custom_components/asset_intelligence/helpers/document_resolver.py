"""Document resolver helpers for Asset Intelligence.

This module converts raw document payloads from the store into normalized
document models used by the Document Retrieval Layer.

Design goals:
- No I/O
- No Home Assistant dependencies
- Resilient to missing / invalid document records
- Deterministic normalization into typed document models
- Safe handling of legacy or shape-variable store payloads
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..document_models import (
    DocumentIssue,
    DocumentIssueCode,
    DocumentMetadata,
    DocumentResolutionResult,
    DocumentResolutionSet,
    DocumentStatus,
)

# ---------------------------------------------------------------------------
# Provider handling
# ---------------------------------------------------------------------------

# Keep this intentionally broad so storage providers can evolve later without
# ripping through the resolver. Unknown providers are not automatically fatal;
# they are normalized and carried forward unless clearly invalid.
KNOWN_DOCUMENT_PROVIDERS: set[str] = {
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_document(asset_id: str, raw_document: Any) -> DocumentResolutionResult:
    """Resolve one raw document payload for an asset.

    The resolver is intentionally tolerant:
    - invalid top-level types become unresolved results
    - partial metadata becomes a resolved result with issues where appropriate
    - missing document_id becomes unresolved (no synthetic IDs are created)
    """
    normalized_asset_id = _safe_str(asset_id)
    if not normalized_asset_id:
        normalized_asset_id = str(asset_id)

    if not isinstance(raw_document, Mapping):
        return DocumentResolutionResult(
            status=DocumentStatus.UNRESOLVED,
            asset_id=normalized_asset_id,
            document_id=None,
            document=None,
            issues=(
                DocumentIssue(
                    code=DocumentIssueCode.INVALID_DOCUMENT_TYPE,
                    message="Document record must be a dictionary-like object.",
                ),
            ),
        )

    issues: list[DocumentIssue] = []

    document_id = _normalize_document_id(raw_document)
    if not document_id:
        return DocumentResolutionResult(
            status=DocumentStatus.UNRESOLVED,
            asset_id=normalized_asset_id,
            document_id=None,
            document=None,
            issues=(
                DocumentIssue(
                    code=DocumentIssueCode.MISSING_DOCUMENT_ID,
                    message="Document record is missing a usable document_id.",
                ),
            ),
        )

    provider_value = _first_present_str(
        raw_document,
        ("provider", "storage_provider", "source_provider"),
    )
    provider = _normalize_provider(provider_value, issues)

    # ---------------------------------------------------------------------
    # Canonical-only normalization
    # ---------------------------------------------------------------------
    filename = _safe_str(raw_document.get("filename"))

    title = _first_present_str(raw_document, ("title",))

    provider_document_id = _safe_str(raw_document.get("provider_document_id"))

    # location is a distinct concept from provider_document_id. Keep it for
    # explicit paths/URIs only.
    location = _first_present_str(
        raw_document,
        ("location", "path", "relative_path", "source_path", "uri"),
    )

    mime_type = _first_present_str(raw_document, ("mime_type", "content_type"))
    checksum = _first_present_str(raw_document, ("checksum", "hash"))
    created_at = _first_present_str(raw_document, ("created_at", "date_created"))
    modified_at = _first_present_str(
        raw_document,
        ("modified_at", "updated_at", "last_modified"),
    )

    size_bytes = _normalize_optional_int(
        raw_document.get("size_bytes", raw_document.get("size")),
        issues=issues,
        field_name="size_bytes",
    )

    tags = _normalize_tags(raw_document.get("tags"), issues)
    metadata = _normalize_metadata(raw_document.get("metadata"), raw_document, issues)

    if provider and not provider_document_id and not location:
        issues.append(
            DocumentIssue(
                code=DocumentIssueCode.MISSING_PROVIDER_REFERENCE,
                message=(
                    "Document has a provider but no provider_document_id or location."
                ),
            )
        )

    document = DocumentMetadata(
        document_id=document_id,
        asset_id=normalized_asset_id,
        title=title,
        filename=filename,
        provider=provider,
        provider_document_id=provider_document_id,
        location=location,
        mime_type=mime_type,
        size_bytes=size_bytes,
        checksum=checksum,
        created_at=created_at,
        modified_at=modified_at,
        tags=tags,
        metadata=metadata,
    )

    return DocumentResolutionResult(
        status=DocumentStatus.RESOLVED,
        asset_id=normalized_asset_id,
        document_id=document_id,
        document=document,
        issues=tuple(issues),
    )


def resolve_documents(asset_id: str, raw_documents: Any) -> DocumentResolutionSet:
    """Resolve all raw document payloads for an asset.

    Accepted raw shapes:
    - list[dict]
    - tuple[dict, ...]
    - dict keyed by document id, with dict values

    Any unsupported top-level shape returns an empty result set rather than
    raising runtime errors.
    """
    normalized_asset_id = _safe_str(asset_id)
    if not normalized_asset_id:
        normalized_asset_id = str(asset_id)

    items = _coerce_document_items(raw_documents)

    results = tuple(
        resolve_document(normalized_asset_id, item)
        for item in items
    )

    return DocumentResolutionSet(
        asset_id=normalized_asset_id,
        results=results,
    )


# ---------------------------------------------------------------------------
# Internal normalization helpers
# ---------------------------------------------------------------------------

def _coerce_document_items(raw_documents: Any) -> list[Any]:
    """Coerce raw document collection into a list of raw document items."""
    if raw_documents is None:
        return []

    if isinstance(raw_documents, Mapping):
        items: list[Any] = []
        for key, value in raw_documents.items():
            if isinstance(value, Mapping):
                merged = dict(value)
                merged.setdefault("document_id", _safe_str(key))
                items.append(merged)
            else:
                items.append(value)
        return items

    if isinstance(raw_documents, Sequence) and not isinstance(
        raw_documents,
        (str, bytes, bytearray),
    ):
        return list(raw_documents)

    return []


def _normalize_document_id(raw_document: Mapping[str, Any]) -> str | None:
    """Return the normalized document ID, or None if it cannot be resolved."""
    value = _first_present_str(
        raw_document,
        ("document_id", "id"),
    )
    return value or None


def _normalize_provider(
    value: str | None,
    issues: list[DocumentIssue],
) -> str | None:
    """Normalize provider name and record issues if clearly invalid."""
    if value is None:
        return None

    provider = value.strip().lower()
    if not provider:
        return None

    # Unknown providers are preserved for forward compatibility. We only
    # emit an issue when the provider format is clearly suspect.
    if " " in provider:
        issues.append(
            DocumentIssue(
                code=DocumentIssueCode.UNSUPPORTED_PROVIDER,
                message=f"Provider '{value}' is not in normalized provider format.",
            )
        )

    return provider


def _normalize_optional_int(
    value: Any,
    *,
    issues: list[DocumentIssue],
    field_name: str,
) -> int | None:
    """Normalize an optional integer field."""
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        issues.append(
            DocumentIssue(
                code=DocumentIssueCode.INVALID_METADATA_TYPE,
                message=f"Field '{field_name}' must not be a boolean.",
            )
        )
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            issues.append(
                DocumentIssue(
                    code=DocumentIssueCode.INVALID_METADATA_TYPE,
                    message=f"Field '{field_name}' is not a valid integer.",
                )
            )
            return None

    issues.append(
        DocumentIssue(
            code=DocumentIssueCode.INVALID_METADATA_TYPE,
            message=f"Field '{field_name}' has an unsupported type.",
        )
    )
    return None


def _normalize_tags(
    value: Any,
    issues: list[DocumentIssue],
) -> tuple[str, ...]:
    """Normalize tags into an immutable tuple of strings."""
    if value is None:
        return ()

    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        normalized: list[str] = []
        for item in value:
            item_str = _safe_str(item)
            if item_str:
                normalized.append(item_str)
        return tuple(normalized)

    issues.append(
        DocumentIssue(
            code=DocumentIssueCode.INVALID_TAGS_TYPE,
            message="Field 'tags' must be a string or a list-like collection.",
        )
    )
    return ()


def _normalize_metadata(
    metadata_value: Any,
    raw_document: Mapping[str, Any],
    issues: list[DocumentIssue],
) -> dict[str, Any]:
    """Normalize the metadata payload.

    Rules:
    - metadata must be a dict-like object if provided
    - extra unmapped raw fields are preserved into metadata
    - mapped fields are not duplicated into metadata
    """
    metadata: dict[str, Any] = {}

    if metadata_value is None:
        metadata = {}
    elif isinstance(metadata_value, Mapping):
        metadata = dict(metadata_value)
    else:
        issues.append(
            DocumentIssue(
                code=DocumentIssueCode.INVALID_METADATA_TYPE,
                message="Field 'metadata' must be a dictionary-like object.",
            )
        )
        metadata = {}

    consumed_keys = {
        "document_id",
        "id",
        "title",
        "filename",
        "file_name",
        "name",
        "provider",
        "storage_provider",
        "source_provider",
        "provider_document_id",
        "external_id",
        "storage_key",
        "provider_id",
        "location",
        "path",
        "relative_path",
        "source_path",
        "uri",
        "mime_type",
        "content_type",
        "size_bytes",
        "size",
        "checksum",
        "hash",
        "created_at",
        "date_created",
        "modified_at",
        "updated_at",
        "last_modified",
        "tags",
        "metadata",
    }

    for key, value in raw_document.items():
        if key in consumed_keys:
            continue
        if key not in metadata:
            metadata[key] = value

    return metadata


def _first_present_str(
    raw_document: Mapping[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    """Return the first usable string value found among the provided keys."""
    for key in keys:
        if key not in raw_document:
            continue
        value = _safe_str(raw_document.get(key))
        if value:
            return value
    return None


def _safe_str(value: Any) -> str | None:
    """Safely normalize a scalar value to a stripped string."""
    if value is None:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None

    if isinstance(value, (int, float)):
        return str(value)

    return None