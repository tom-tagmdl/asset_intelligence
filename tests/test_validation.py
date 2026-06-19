from __future__ import annotations

import pytest

from custom_components.asset_intelligence.validation import (
    AssetValidationError,
    validate_asset_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_asset(**overrides) -> dict:
    """Return the smallest valid asset payload."""
    base = {
        "asset_id": "asset_1",
        "name": "Test Asset",
        "asset_type": "electronics",
    }
    base.update(overrides)
    return base


def _valid_document(**overrides) -> dict:
    base = {
        "document_id": "doc_1",
        "type": "manual",
        "filename": "manual.pdf",
        "provider_document_id": "asset_1/doc_1_manual.pdf",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_minimal_valid_asset_passes():
    validate_asset_payload(_minimal_asset())


def test_asset_with_all_allowed_types_passes():
    allowed = [None, "artwork", "rare_book", "collectable", "electronics",
               "infrastructure", "furniture", "instrument"]
    for asset_type in allowed:
        validate_asset_payload(_minimal_asset(asset_type=asset_type))


def test_asset_with_valid_document_passes():
    asset = _minimal_asset(documents=[_valid_document()])
    validate_asset_payload(asset)


def test_asset_with_multiple_unique_documents_passes():
    asset = _minimal_asset(documents=[
        _valid_document(document_id="doc_1"),
        _valid_document(document_id="doc_2", filename="receipt.pdf",
                        provider_document_id="asset_1/doc_2_receipt.pdf"),
    ])
    validate_asset_payload(asset)


def test_asset_with_valid_purchase_passes():
    asset = _minimal_asset(purchase={"purchase_price": 100.0, "purchase_date": "2024-01-15"})
    validate_asset_payload(asset)


def test_asset_with_zero_price_passes():
    asset = _minimal_asset(purchase={"purchase_price": 0})
    validate_asset_payload(asset)


# ---------------------------------------------------------------------------
# Mandatory-field errors
# ---------------------------------------------------------------------------

def test_missing_asset_id_raises():
    with pytest.raises(AssetValidationError, match="asset_id"):
        validate_asset_payload({"name": "No ID", "asset_type": "electronics"})


def test_missing_name_raises():
    with pytest.raises(AssetValidationError, match="name"):
        validate_asset_payload({"asset_id": "a1", "asset_type": "electronics"})


def test_invalid_asset_type_raises():
    with pytest.raises(AssetValidationError, match="asset_type"):
        validate_asset_payload(_minimal_asset(asset_type="spaceship"))


def test_labels_must_be_list_of_strings():
    with pytest.raises(AssetValidationError, match="labels"):
        validate_asset_payload(_minimal_asset(labels=["ok", 123]))


def test_quantity_must_be_positive_integer():
    with pytest.raises(AssetValidationError, match="quantity"):
        validate_asset_payload(_minimal_asset(quantity=0))


# ---------------------------------------------------------------------------
# Document field errors
# ---------------------------------------------------------------------------

def test_document_missing_document_id_raises():
    doc = _valid_document()
    del doc["document_id"]
    with pytest.raises(AssetValidationError, match="document_id"):
        validate_asset_payload(_minimal_asset(documents=[doc]))


def test_document_missing_type_raises():
    doc = _valid_document()
    del doc["type"]
    with pytest.raises(AssetValidationError, match="type"):
        validate_asset_payload(_minimal_asset(documents=[doc]))


def test_document_invalid_type_raises():
    with pytest.raises(AssetValidationError, match="invalid document type"):
        validate_asset_payload(_minimal_asset(documents=[_valid_document(type="unknown_type")]))


def test_document_missing_filename_raises():
    doc = _valid_document()
    del doc["filename"]
    with pytest.raises(AssetValidationError, match="filename"):
        validate_asset_payload(_minimal_asset(documents=[doc]))


def test_document_missing_provider_document_id_raises():
    doc = _valid_document()
    del doc["provider_document_id"]
    with pytest.raises(AssetValidationError, match="provider_document_id"):
        validate_asset_payload(_minimal_asset(documents=[doc]))


def test_duplicate_document_id_raises():
    docs = [_valid_document(), _valid_document()]  # same document_id twice
    with pytest.raises(AssetValidationError, match="duplicate document_id"):
        validate_asset_payload(_minimal_asset(documents=docs))


def test_document_tags_must_be_list_of_strings():
    with pytest.raises(AssetValidationError, match="documents.tags"):
        validate_asset_payload(
            _minimal_asset(documents=[_valid_document(tags=["ok", 1])])
        )


def test_document_metadata_must_be_object_when_present():
    with pytest.raises(AssetValidationError, match="documents.metadata"):
        validate_asset_payload(
            _minimal_asset(documents=[_valid_document(metadata="not-a-dict")])
        )


# ---------------------------------------------------------------------------
# Purchase / valuation errors
# ---------------------------------------------------------------------------

def test_negative_purchase_price_raises():
    with pytest.raises(AssetValidationError, match="purchase_price"):
        validate_asset_payload(_minimal_asset(purchase={"purchase_price": -1}))


def test_invalid_purchase_date_format_raises():
    with pytest.raises(AssetValidationError, match="purchase_date"):
        validate_asset_payload(_minimal_asset(purchase={"purchase_date": "not-a-date"}))


def test_negative_replacement_value_raises():
    with pytest.raises(AssetValidationError, match="replacement_value"):
        validate_asset_payload(_minimal_asset(valuation={"replacement_value": -500}))
