"""Document Retrieval Service for Asset Intelligence."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..storage import AssetStore
from ..helpers.document_resolver import resolve_documents, resolve_document
from ..document_models import (
    DocumentResolutionSet,
    DocumentResolutionResult,
)


class DocumentRetrievalService:
    """Service for retrieving document metadata."""

    def __init__(self, hass: HomeAssistant, store: AssetStore) -> None:
        self._hass = hass
        self._store = store

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    async def async_get_documents_for_asset(
        self, asset_id: str
    ) -> DocumentResolutionSet:
        raw_documents = self._get_raw_documents_for_asset(asset_id)
        return resolve_documents(asset_id, raw_documents)

    async def async_get_document_for_asset(
        self, asset_id: str, document_id: str
    ) -> DocumentResolutionResult:

        raw_documents = self._get_raw_documents_for_asset(asset_id)

        if not raw_documents:
            return resolve_document(asset_id, None)

        # ✅ CASE: dict keyed by document_id
        if isinstance(raw_documents, dict):
            raw_document = raw_documents.get(document_id)
            if not isinstance(raw_document, dict):
                return resolve_document(asset_id, None)

            return resolve_document(asset_id, raw_document)

        # ✅ CASE: list of documents
        if isinstance(raw_documents, list):
            for doc in raw_documents:
                if not isinstance(doc, dict):
                    continue

                if doc.get("document_id") == document_id:
                    return resolve_document(asset_id, doc)

        # ✅ Not found → return unresolved cleanly
        return resolve_document(asset_id, None)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _get_raw_documents_for_asset(self, asset_id: str) -> Any:

        if not self._store:
            return []

        try:
            asset = self._store.get(asset_id)
        except Exception:
            return []

        if not isinstance(asset, dict):
            return []

        docs = asset.get("documents")

        if isinstance(docs, list) or isinstance(docs, dict):
            return docs

        return []
