from __future__ import annotations

import asyncio
import base64
import importlib.util
from pathlib import Path


def load_test_module():
    module_path = Path(r"H:\tests\test_services.py")
    spec = importlib.util.spec_from_file_location("test_services", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def main() -> None:
    print("checkpoint: load module", flush=True)
    module = load_test_module()
    print("checkpoint: module loaded", flush=True)

    hass, entry, service_handlers, store, document_storage = module._build_hass()
    print("checkpoint: harness built", flush=True)
    await module._setup_integration(hass)
    print("checkpoint: setup complete", flush=True)
    print(f"checkpoint: services={sorted(service_handlers.keys())}", flush=True)

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "name": "Test asset",
        "asset_type": "electronics",
        "documents": [],
        "physical_documents": [],
        "trackers": [],
        "links": {},
        "loans": [],
        "custody": {},
        "audit_log": [],
        "created_by": None,
        "updated_by": None,
    }

    upload_handler = service_handlers["upload_document"]
    print("checkpoint: upload handler acquired", flush=True)
    upload_call = module.SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "type": "manual",
            "title": "Warranty sheet",
            "filename": "warranty.pdf",
            "content_base64": base64.b64encode(b"document-bytes").decode(),
            "actor": "tester",
        },
        context=module.SimpleNamespace(user_id=None),
    )
    print("checkpoint: invoking upload", flush=True)
    with (
        module.patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        module.patch("custom_components.asset_intelligence.__init__._get_document_storage", return_value=document_storage),
        module.patch("custom_components.asset_intelligence.__init__._refresh_runtime", module.AsyncMock()),
    ):
        await upload_handler(upload_call)
    print("checkpoint: upload complete", flush=True)

    updated_asset = store.assets["asset_1"]
    assert updated_asset["document_count"] == 1
    assert updated_asset["last_document_title"] == "Warranty sheet"
    assert updated_asset["audit_log"][-1]["action"] == "upload_document"
    assert document_storage.received_store_arguments["content"] == b"document-bytes"

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "name": "Test asset",
        "asset_type": "electronics",
        "documents": [
            {
                "document_id": "doc-1",
                "type": "manual",
                "title": "Original title",
                "filename": "warranty.pdf",
                "provider": "filesystem",
                "provider_document_id": "asset_1/doc-1_warranty.pdf",
                "metadata": {"notes": "Original notes", "date": "2026-06-18"},
                "tags": ["keep"],
            }
        ],
        "physical_documents": [],
        "trackers": [],
        "links": {},
        "loans": [],
        "custody": {},
        "audit_log": [],
        "created_by": None,
        "updated_by": None,
    }

    update_handler = service_handlers["update_document_metadata"]
    print("checkpoint: update handler acquired", flush=True)
    update_call = module.SimpleNamespace(
        data={"asset_id": "asset_1", "document_id": "doc-1", "title": "Updated title", "actor": "tester"},
        context=module.SimpleNamespace(user_id=None),
    )
    print("checkpoint: invoking update", flush=True)
    with (
        module.patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        module.patch("custom_components.asset_intelligence.__init__._refresh_runtime", module.AsyncMock()),
    ):
        await update_handler(update_call)
    print("checkpoint: update complete", flush=True)

    audit_entry = store.assets["asset_1"]["audit_log"][-1]
    assert audit_entry["details"]["changed_fields"] == ["title"]
    assert audit_entry["details"]["field_changes"]["title"] == {
        "before": "Original title",
        "after": "Updated title",
    }

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "audit_log": [
            {"action": "update_asset", "timestamp": "2026-06-18T10:00:00+00:00", "actor": "system"},
            {"action": "upload_document", "timestamp": "2026-06-18T10:10:00+00:00", "actor": "system"},
            {"action": "record_loan_out", "timestamp": "2026-06-18T10:20:00+00:00", "actor": "system"},
            {"action": "set_environment_requirements", "timestamp": "2026-06-18T10:30:00+00:00", "actor": "system"},
        ],
        "environment_events": [],
        "custody_events": [],
        "loans": [],
        "documents": [],
        "physical_documents": [],
        "trackers": [],
        "links": {},
        "custody": {},
    }

    history_handler = service_handlers["get_asset_history"]
    print("checkpoint: history handler acquired", flush=True)
    history_call = module.SimpleNamespace(
        data={"asset_id": "asset_1", "max_entries": 20},
        context=module.SimpleNamespace(user_id=None),
    )
    print("checkpoint: invoking history", flush=True)
    with module.patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        payload = await history_handler(history_call)
    print("checkpoint: history complete", flush=True)

    assert [entry["kind"] for entry in payload["by_filter"]["audit"]] == ["audit"]
    assert [entry["kind"] for entry in payload["by_filter"]["documents"]] == ["documents"]
    assert [entry["kind"] for entry in payload["by_filter"]["custody"]] == ["custody"]
    assert [entry["kind"] for entry in payload["by_filter"]["environment"]] == ["environment"]

    print("SERVICE_TESTS_OK")


if __name__ == "__main__":
    asyncio.run(main())