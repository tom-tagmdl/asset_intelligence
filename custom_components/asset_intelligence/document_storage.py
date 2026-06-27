from __future__ import annotations

from typing import Any
import hashlib
import mimetypes
import os
import shutil
import uuid

from homeassistant.core import HomeAssistant


class DocumentStorage:
    """Abstraction layer for document storage.

    Responsibilities:
    - Validate storage availability
    - Persist files to configured external storage
    - Generate CANONICAL document metadata records
    - Retrieve safe access metadata for stored documents
    - Provide controlled byte access for future service-layer retrieval

    This class does NOT:
    - Persist asset metadata (handled elsewhere)
    - Mutate asset records directly
    - Perform business logic
    - Depend on Home Assistant media-source assumptions
    """

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self.hass = hass
        self.config = config or {}

        self.provider: str = self.config.get("provider", "filesystem")
        self.root_path: str | None = self.config.get("root_path")
        self.documents_enabled: bool = self.config.get("documents_enabled", False)
        self.requires_network_storage: bool = self.config.get(
            "requires_network_storage", True
        )

    # ---------------------------------------------------------
    # CAPABILITY CHECK
    # ---------------------------------------------------------
    def is_available(self) -> bool:
        """Return True if document storage is configured and the path is accessible.

        Uses a read-only check (isdir + os.access) so network mounts that do not
        allow arbitrary file creation (common for SMB/NFS shares in /media) are
        still reported as available.  Actual write failures are surfaced at
        operation time with a clear error rather than silently marking the whole
        store unavailable.
        """
        if not self.documents_enabled:
            return False

        if not self.root_path or not isinstance(self.root_path, str):
            return False

        try:
            return os.path.isdir(self.root_path) and os.access(self.root_path, os.R_OK)
        except Exception:
            return False

    def is_readable(self) -> bool:
        """Return True if the configured storage root can be read."""
        if not self.documents_enabled:
            return False

        if not self.root_path or not isinstance(self.root_path, str):
            return False

        try:
            return os.path.isdir(self.root_path) and os.access(self.root_path, os.R_OK)
        except Exception:
            return False

    # ---------------------------------------------------------
    # STORE DOCUMENT (CANONICAL OUTPUT)
    # ---------------------------------------------------------
    def store_document(
        self,
        *,
        asset_id: str,
        file_name: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
        preview_content: bytes | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Store a document and return a CANONICAL metadata record.

        Canonical output shape:
        {
            "document_id": ...,
            "type": ...,
            "title": ...,
            "filename": ...,
            "provider": ...,
            "provider_document_id": ...,
            "mime_type": ...,
            "size_bytes": ...,
            "tags": [...],
            "metadata": {...}
        }
        """
        if not self.is_available():
            raise RuntimeError("Document storage is not available")

        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("Document content must be bytes")

        if not asset_id or not isinstance(asset_id, str):
            raise ValueError("asset_id is required")

        metadata = metadata or {}

        document_id = str(uuid.uuid4())

        safe_file_name = self._sanitize_filename(file_name)
        file_ext = self._get_file_extension(safe_file_name)
        mime_type = self._guess_mime_type(safe_file_name)
        checksum = self._compute_checksum(content)

        asset_folder = os.path.join(self.root_path, asset_id)
        os.makedirs(asset_folder, exist_ok=True)

        provider_document_id = f"{asset_id}/{document_id}_{safe_file_name}"
        file_path = self._resolve_provider_document_id_to_path(provider_document_id)
        if not file_path:
            raise RuntimeError("Could not resolve storage path for document")

        with open(file_path, "wb") as handle:
            handle.write(content)

        size_bytes = len(content)

        preview_provider_document_id = None
        preview_filename = None

        if preview_content is not None:
            preview_suffix = f".{file_ext}" if file_ext else ""
            preview_filename = f"{document_id}_preview{preview_suffix}"
            preview_provider_document_id = f"{asset_id}/{preview_filename}"

            preview_path = self._resolve_provider_document_id_to_path(
                preview_provider_document_id
            )
            if not preview_path:
                raise RuntimeError("Could not resolve storage path for preview")

            with open(preview_path, "wb") as handle:
                handle.write(preview_content)

        document_record = {
            "document_id": document_id,
            "type": metadata.get("type"),
            "title": metadata.get("title"),
            "filename": safe_file_name,
            "provider": self.provider,
            "provider_document_id": provider_document_id,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "tags": metadata.get("tags", []),
            "metadata": {
                "notes": metadata.get("notes"),
                "date": metadata.get("date"),
                "checksum": checksum,
                "checksum_type": "sha256",
                "version": 1,
                "created_at": self._now_iso(),
                "created_by": created_by,
                "available": True,
                "file_ext": file_ext,
                "preview_provider_document_id": preview_provider_document_id,
                "preview_filename": preview_filename,
            },
        }

        return document_record

    # ---------------------------------------------------------
    # DOCUMENT ACCESS LAYER
    # ---------------------------------------------------------
    def document_exists(
        self,
        provider_document_id: str | None = None,
    ) -> bool:
        """Return True if the referenced document exists."""
        ref = provider_document_id
        path = self._resolve_provider_document_id_to_path(ref)
        return bool(path and os.path.isfile(path))

    def get_document_access_info(
        self,
        *,
        provider_document_id: str | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Return safe access metadata for a stored document.

        This method intentionally does NOT expose raw filesystem paths.
        """
        ref = provider_document_id
        resolved_name = filename or self._file_name_from_provider_document_id(ref)
        resolved_mime = mime_type or self._guess_mime_type(resolved_name or "")
        exists = self.document_exists(provider_document_id=ref)

        return {
            "provider": self.provider,
            "provider_document_id": ref,
            "filename": resolved_name,
            "mime_type": resolved_mime,
            "exists": exists,
            "available": bool(self.is_readable() and exists),
        }

    def get_preview_access_info(
        self,
        *,
        preview_provider_document_id: str | None = None,
        preview_filename: str | None = None,
    ) -> dict[str, Any] | None:
        """Return safe access metadata for a preview document, if present.
        """
        ref = preview_provider_document_id
        if not ref:
            return None

        exists = self.document_exists(provider_document_id=ref)
        resolved_name = preview_filename or self._file_name_from_provider_document_id(ref)
        resolved_mime = self._guess_mime_type(resolved_name or "")

        return {
            "provider": self.provider,
            "provider_document_id": ref,
            "filename": resolved_name,
            "mime_type": resolved_mime,
            "exists": exists,
            "available": bool(self.is_readable() and exists),
        }

    def get_document_record_access_info(
        self,
        document_record: dict[str, Any],
    ) -> dict[str, Any]:
        """Return safe access metadata using a document record.
        """
        if not isinstance(document_record, dict):
            raise ValueError("document_record must be a dictionary")

        metadata = document_record.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        access_info = self.get_document_access_info(
            provider_document_id=document_record.get("provider_document_id"),
            filename=document_record.get("filename"),
            mime_type=document_record.get("mime_type"),
        )

        preview_info = self.get_preview_access_info(
            preview_provider_document_id=metadata.get("preview_provider_document_id"),
            preview_filename=metadata.get("preview_filename"),
        )

        result = dict(access_info)
        result.update(
            {
                "document_id": document_record.get("document_id"),
                "type": document_record.get("type"),
                "title": document_record.get("title"),
                "size_bytes": document_record.get("size_bytes"),
                "checksum": metadata.get("checksum") or document_record.get("checksum"),
                "checksum_type": metadata.get("checksum_type") or document_record.get("checksum_type"),
                "preview": preview_info,
            }
        )
        return result

    def read_document_bytes(
        self,
        provider_document_id: str | None = None,
    ) -> bytes:
        """Read stored document bytes for controlled service-layer retrieval."""
        if not self.is_readable():
            raise RuntimeError("Document storage is not readable")

        ref = provider_document_id
        path = self._resolve_provider_document_id_to_path(ref)
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Document not found: {ref}")

        with open(path, "rb") as handle:
            return handle.read()

    def read_preview_bytes(
        self,
        preview_provider_document_id: str | None = None,
    ) -> bytes:
        """Read stored preview bytes for controlled service-layer retrieval."""
        return self.read_document_bytes(
            provider_document_id=preview_provider_document_id,
        )

    def delete_document(
        self,
        *,
        provider_document_id: str | None = None,
    ) -> bool:
        """Delete a stored document file if it exists."""
        ref = provider_document_id
        path = self._resolve_provider_document_id_to_path(ref)
        if not path or not os.path.isfile(path):
            return False

        try:
            os.remove(path)
            return True
        except Exception:
            return False

    def delete_preview(
        self,
        *,
        preview_provider_document_id: str | None = None,
    ) -> bool:
        """Delete a stored preview file if it exists."""
        return self.delete_document(
            provider_document_id=preview_provider_document_id,
        )

    def delete_asset_folder(
        self,
        *,
        asset_id: str,
    ) -> bool:
        """Delete an asset's storage folder and any remaining files under it."""
        if not isinstance(asset_id, str):
            return False

        normalized_asset_id = asset_id.strip().replace("\\", "/").strip("/")
        if (
            not normalized_asset_id
            or "/" in normalized_asset_id
            or normalized_asset_id in {".", ".."}
        ):
            return False

        if not self.root_path or not isinstance(self.root_path, str):
            return False

        root_real = os.path.realpath(os.path.abspath(self.root_path))
        candidate = os.path.realpath(
            os.path.abspath(os.path.join(self.root_path, normalized_asset_id))
        )

        try:
            common = os.path.commonpath([root_real, candidate])
        except ValueError:
            return False

        if common != root_real:
            return False

        if not os.path.isdir(candidate):
            return False

        try:
            shutil.rmtree(candidate)
            return True
        except Exception:
            return False

    # ---------------------------------------------------------
    # INTERNAL PATH / REFERENCE HELPERS
    # ---------------------------------------------------------
    def _resolve_provider_document_id_to_path(
        self,
        provider_document_id: str | None,
    ) -> str | None:
        """Resolve a provider_document_id to a safe internal file path.

        Returns None if the identifier is invalid or unsafe.
        """
        if not provider_document_id or not isinstance(provider_document_id, str):
            return None

        if not self.root_path or not isinstance(self.root_path, str):
            return None

        normalized_identifier = provider_document_id.replace("\\", "/").strip().lstrip("/")
        if not normalized_identifier:
            return None

        parts = [part for part in normalized_identifier.split("/") if part not in ("", ".")]
        if any(part == ".." for part in parts):
            return None

        candidate = os.path.abspath(os.path.join(self.root_path, *parts))
        root = os.path.abspath(self.root_path)

        try:
            common = os.path.commonpath([root, candidate])
        except ValueError:
            return None

        if common != root:
            return None

        return candidate

    def _file_name_from_provider_document_id(
        self,
        provider_document_id: str | None,
    ) -> str | None:
        """Extract the file name portion from a provider_document_id."""
        if not provider_document_id or not isinstance(provider_document_id, str):
            return None

        normalized = provider_document_id.replace("\\", "/").rstrip("/")
        if not normalized:
            return None

        return normalized.split("/")[-1] or None

    # ---------------------------------------------------------
    # INTERNAL UTILITIES
    # ---------------------------------------------------------
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize incoming filename."""
        if not isinstance(name, str) or not name.strip():
            return "document"

        sanitized = os.path.basename(name).replace("..", "").strip()
        return sanitized or "document"

    def _get_file_extension(self, name: str) -> str | None:
        """Extract file extension without the dot."""
        if "." not in name:
            return None
        return name.rsplit(".", 1)[-1].lower()

    def _guess_mime_type(self, name: str) -> str | None:
        """Guess MIME type based on filename."""
        mime_type, _ = mimetypes.guess_type(name)
        return mime_type

    def _compute_checksum(self, content: bytes) -> str:
        """Return SHA256 checksum for content."""
        return hashlib.sha256(content).hexdigest()

    def _now_iso(self) -> str:
        from homeassistant.util import dt as dt_util

        return dt_util.now().isoformat()