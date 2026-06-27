"""Document models for Asset Intelligence.

This module defines the normalized internal structures used by the
Document Retrieval Layer.

Design goals:
- Keep store payloads raw and unopinionated
- Normalize document metadata into stable internal models
- Represent invalid/missing documents without raising runtime errors
- Prepare for future provider-backed retrieval without introducing I/O
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentIssueCode(str, Enum):
    """Known document resolution issue codes."""

    MISSING_DOCUMENT_ID = "missing_document_id"
    INVALID_DOCUMENT_TYPE = "invalid_document_type"
    INVALID_METADATA_TYPE = "invalid_metadata_type"
    INVALID_TAGS_TYPE = "invalid_tags_type"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    MISSING_PROVIDER_REFERENCE = "missing_provider_reference"


class DocumentStatus(str, Enum):
    """Resolution status for a document record."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(slots=True, frozen=True)
class DocumentIssue:
    """Represents a non-fatal issue discovered during document resolution."""

    code: DocumentIssueCode
    message: str


@dataclass(slots=True, frozen=True)
class DocumentMetadata:
    """Normalized metadata for a document associated with an asset.

    This is metadata only. It does not imply that file contents are locally
    available or that a preview/download operation has been performed.
    """

    document_id: str
    asset_id: str
    title: str | None = None
    filename: str | None = None
    provider: str | None = None
    provider_document_id: str | None = None
    location: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Return the best available human-friendly name for the document."""
        if self.title:
            return self.title
        if self.filename:
            return self.filename
        return self.document_id

    @property
    def has_provider_reference(self) -> bool:
        """Return True if the document has enough provider identity to evolve later."""
        return bool(self.provider and self.provider_document_id)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of this document metadata."""
        return {
            "document_id": self.document_id,
            "asset_id": self.asset_id,
            "title": self.title,
            "filename": self.filename,
            "provider": self.provider,
            "provider_document_id": self.provider_document_id,
            "location": self.location,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class DocumentResolutionResult:
    """Represents the result of resolving one raw document record."""

    status: DocumentStatus
    asset_id: str
    document_id: str | None
    document: DocumentMetadata | None = None
    issues: tuple[DocumentIssue, ...] = field(default_factory=tuple)

    @property
    def is_resolved(self) -> bool:
        """Return True if the document was resolved successfully."""
        return self.status == DocumentStatus.RESOLVED and self.document is not None

    @property
    def is_unresolved(self) -> bool:
        """Return True if the document could not be resolved."""
        return self.status == DocumentStatus.UNRESOLVED

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the resolution result."""
        return {
            "status": self.status.value,
            "asset_id": self.asset_id,
            "document_id": self.document_id,
            "document": self.document.as_dict() if self.document else None,
            "issues": [
                {
                    "code": issue.code.value,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


@dataclass(slots=True, frozen=True)
class DocumentResolutionSet:
    """Represents the resolution results for all documents of an asset."""

    asset_id: str
    results: tuple[DocumentResolutionResult, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> tuple[DocumentMetadata, ...]:
        """Return all successfully resolved document metadata objects."""
        return tuple(
            result.document
            for result in self.results
            if result.document is not None and result.is_resolved
        )

    @property
    def unresolved(self) -> tuple[DocumentResolutionResult, ...]:
        """Return all unresolved document results."""
        return tuple(result for result in self.results if result.is_unresolved)

    @property
    def resolved_count(self) -> int:
        """Return the number of successfully resolved documents."""
        return len(self.resolved)

    @property
    def unresolved_count(self) -> int:
        """Return the number of unresolved documents."""
        return len(self.unresolved)

    @property
    def total_count(self) -> int:
        """Return the total number of resolution results."""
        return len(self.results)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the resolution set."""
        return {
            "asset_id": self.asset_id,
            "resolved_count": self.resolved_count,
            "unresolved_count": self.unresolved_count,
            "total_count": self.total_count,
            "results": [result.as_dict() for result in self.results],
        }