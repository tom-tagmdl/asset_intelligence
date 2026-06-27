from __future__ import annotations

from custom_components.asset_intelligence.binary_sensor import (
    AssetAtRiskBinarySensor,
    DocumentStorageAvailableSensor,
)
from custom_components.asset_intelligence.sensor import AssetCountSensor, AssetListSensor, RoomEnvironmentEntity


def test_static_sensors_use_translation_keys_and_diagnostic_category():
    assert hasattr(AssetCountSensor, "_attr_translation_key")
    assert getattr(AssetCountSensor, "_attr_translation_key", None) is not None
    assert getattr(AssetCountSensor, "_attr_entity_category", None) is not None

    assert hasattr(AssetListSensor, "_attr_translation_key")
    assert getattr(AssetListSensor, "_attr_translation_key", None) is not None
    assert getattr(AssetListSensor, "_attr_entity_category", None) is not None

    assert getattr(RoomEnvironmentEntity, "_attr_entity_category", None) is not None

    assert getattr(AssetAtRiskBinarySensor, "_attr_has_entity_name", None) is not None
    assert getattr(AssetAtRiskBinarySensor, "_attr_translation_key", None) is not None
    assert getattr(AssetAtRiskBinarySensor, "_attr_entity_category", None) is not None

    assert getattr(DocumentStorageAvailableSensor, "_attr_has_entity_name", None) is not None
    assert getattr(DocumentStorageAvailableSensor, "_attr_translation_key", None) is not None
    assert getattr(DocumentStorageAvailableSensor, "_attr_entity_category", None) is not None
