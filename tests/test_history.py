from __future__ import annotations

from custom_components.asset_intelligence.__init__ import _build_asset_history_payload


def test_build_asset_history_payload_classifies_document_and_custody_items():
    asset = {
        "audit_log": [
            {"action": "update_asset", "timestamp": "2026-06-18T10:00:00+00:00", "actor": "system"},
            {"action": "upload_document", "timestamp": "2026-06-18T10:10:00+00:00", "actor": "system"},
            {"action": "record_loan_out", "timestamp": "2026-06-18T10:20:00+00:00", "actor": "system"},
            {"action": "set_environment_requirements", "timestamp": "2026-06-18T10:30:00+00:00", "actor": "system"},
        ],
        "environment_events": [],
        "custody_events": [],
        "loans": [],
    }

    payload = _build_asset_history_payload(asset, max_entries=20)

    assert [entry["kind"] for entry in payload["by_filter"]["audit"]] == ["audit"]
    assert [entry["kind"] for entry in payload["by_filter"]["documents"]] == ["documents"]
    assert [entry["kind"] for entry in payload["by_filter"]["custody"]] == ["custody"]
    assert [entry["kind"] for entry in payload["by_filter"]["environment"]] == ["environment"]


def test_build_asset_history_payload_includes_measurement_entries():
    asset = {
        "audit_log": [
            {"action": "start_measurement", "timestamp": "2026-06-18T10:00:00+00:00", "actor": "tester"},
            {"action": "stop_measurement", "timestamp": "2026-06-18T10:10:00+00:00", "actor": "tester"},
        ],
        "environment_events": [],
        "custody_events": [],
        "loans": [],
    }

    payload = _build_asset_history_payload(asset, max_entries=20)

    measurement_kinds = [entry["kind"] for entry in payload["by_filter"]["measurements"]]
    assert measurement_kinds == ["measurements", "measurements"]
