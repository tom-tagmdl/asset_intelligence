from __future__ import annotations

from custom_components.asset_intelligence.__init__ import _find_document_record, _rebuild_document_summary


def test_find_document_record_by_document_id():
    asset = {
        "documents": [
            {"document_id": "doc_1", "title": "First document"},
            {"document_id": "doc_2", "provider_document_id": "provider-2", "title": "Second document"},
        ]
    }

    record = _find_document_record(asset, document_id="doc_2")

    assert record is not None
    assert record["title"] == "Second document"


def test_rebuild_document_summary_updates_count_and_last_document_fields():
    asset = {
        "documents": [
            {"document_id": "doc_1", "title": "First document", "type": "manual"},
            {"document_id": "doc_2", "title": "Second document", "type": "warranty"},
        ]
    }

    _rebuild_document_summary(asset)

    assert asset["document_count"] == 2
    assert asset["last_document_id"] == "doc_2"
    assert asset["last_document_title"] == "Second document"
    assert asset["last_document_uri"] is None
    assert len(asset["document_summary"]) == 2
