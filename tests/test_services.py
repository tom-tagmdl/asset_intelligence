from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.asset_intelligence.__init__ import async_setup
from custom_components.asset_intelligence.const import DOMAIN


class FakeStore:
    def __init__(self, hass):
        self.hass = hass
        self.assets: dict[str, dict] = {}
        self.system_defaults = {}

    async def async_load(self):
        return None

    def get_document_storage_config(self):
        return {}

    async def set_document_storage_config(self, config):
        self.document_storage_config = config

    def get(self, asset_id):
        return self.assets.get(asset_id)

    async def add_or_replace(self, asset_dict):
        self.assets[asset_dict["asset_id"]] = asset_dict

    async def async_save(self):
        return None


class FakeCoordinator:
    def __init__(self, hass, store):
        self.hass = hass
        self.store = store
        self.async_config_entry_first_refresh = AsyncMock()
        self.async_request_refresh = AsyncMock()

    def get_asset_record(self, asset_id):
        return self.store.get(asset_id)

    def _utcnow_iso(self):
        return "2026-06-23T00:00:00+00:00"


class FakeDocumentStorage:
    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self.documents_enabled = True
        self.received_store_arguments = None
        self.received_delete_document_arguments = None
        self.received_delete_preview_arguments = None
        self.received_delete_asset_folder_arguments = None
        self.delete_document_calls = []
        self.delete_preview_calls = []
        self.delete_asset_folder_calls = []

    def is_available(self):
        return True

    def delete_document(self, *, provider_document_id=None):
        self.received_delete_document_arguments = {
            "provider_document_id": provider_document_id,
        }
        self.delete_document_calls.append(self.received_delete_document_arguments)
        return True

    def delete_preview(self, *, preview_provider_document_id=None):
        self.received_delete_preview_arguments = {
            "preview_provider_document_id": preview_provider_document_id,
        }
        self.delete_preview_calls.append(self.received_delete_preview_arguments)
        return True

    def delete_asset_folder(self, *, asset_id=None):
        self.received_delete_asset_folder_arguments = {
            "asset_id": asset_id,
        }
        self.delete_asset_folder_calls.append(self.received_delete_asset_folder_arguments)
        return True

    def store_document(
        self,
        *,
        asset_id,
        file_name,
        content,
        metadata=None,
        preview_content=None,
        created_by=None,
    ):
        self.received_store_arguments = {
            "asset_id": asset_id,
            "file_name": file_name,
            "content": content,
            "metadata": metadata,
            "preview_content": preview_content,
            "created_by": created_by,
        }

        return {
            "document_id": "doc-1",
            "type": metadata.get("type") if metadata else None,
            "title": metadata.get("title") if metadata else None,
            "filename": file_name,
            "provider": "filesystem",
            "provider_document_id": f"{asset_id}/doc-1_{file_name}",
            "mime_type": "application/pdf",
            "size_bytes": len(content),
            "tags": list((metadata or {}).get("tags", [])),
            "metadata": {
                "notes": (metadata or {}).get("notes"),
                "date": (metadata or {}).get("date"),
                "checksum": "checksum-1",
                "checksum_type": "sha256",
                "version": 1,
                "created_at": "2026-06-18T10:00:00+00:00",
                "created_by": created_by,
                "available": True,
                "file_ext": "pdf",
                "preview_provider_document_id": None,
                "preview_filename": None,
            },
        }


def _build_hass():
    service_handlers: dict[str, object] = {}

    def async_register(domain, service, handler, **kwargs):
        if domain == DOMAIN:
            service_handlers[service] = handler

    async def async_call(
        domain,
        service,
        service_data=None,
        blocking=False,
        return_response=False,
    ):
        if domain != DOMAIN:
            return None

        handler = service_handlers.get(service)
        if handler is None:
            return None

        call = SimpleNamespace(
            data=service_data or {},
            context=SimpleNamespace(user_id=None),
        )
        result = handler(call)
        if asyncio.iscoroutine(result):
            return await result
        return result

    store = FakeStore(None)
    coordinator = FakeCoordinator(None, store)
    document_storage = FakeDocumentStorage(None, {})

    runtime_entry = SimpleNamespace(
        entry_id="entry_1",
        runtime_data={
            "store": store,
            "coordinator": coordinator,
            "document_storage": document_storage,
            "document_storage_available": True,
        },
    )

    hass = SimpleNamespace()
    hass.data = {}
    hass.services = SimpleNamespace(
        async_register=MagicMock(side_effect=async_register),
        async_call=AsyncMock(side_effect=async_call),
        has_service=MagicMock(return_value=True),
        async_remove=MagicMock(),
    )
    hass.config_entries = SimpleNamespace(
        async_forward_entry_setups=AsyncMock(return_value=None),
        async_entries=MagicMock(return_value=[runtime_entry]),
        async_unload_platforms=AsyncMock(return_value=True),
    )
    hass.bus = SimpleNamespace(
        async_fire=MagicMock(),
        async_listen=MagicMock(return_value=lambda: None),
    )
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
    hass.async_block_till_done = AsyncMock(return_value=None)

    store.hass = hass
    coordinator.hass = hass
    document_storage.hass = hass

    return hass, runtime_entry, service_handlers, store, document_storage


async def _setup_integration(hass):
    with (
        patch("custom_components.asset_intelligence.__init__._ensure_document_view_registered"),
        patch("custom_components.asset_intelligence.__init__.async_setup_panel", AsyncMock()),
        patch("custom_components.asset_intelligence.__init__.async_dispatcher_send"),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
    ):
        result = await async_setup(hass, {})

    assert result is True
    return hass


@pytest.mark.asyncio
async def test_upload_document_service_updates_asset_and_audit_log():
    hass, entry, service_handlers, store, document_storage = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["upload_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "type": "manual",
            "title": "Warranty sheet",
            "filename": "warranty.pdf",
            "content_base64": base64.b64encode(b"document-bytes").decode(),
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._get_document_storage", return_value=document_storage),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
    ):
        await handler(call)

    updated_asset = store.assets["asset_1"]
    assert len(updated_asset["documents"]) == 1
    assert updated_asset["document_count"] == 1
    assert updated_asset["last_document_title"] == "Warranty sheet"
    assert updated_asset["audit_log"][-1]["action"] == "upload_document"
    assert updated_asset["audit_log"][-1]["details"]["document_id"] == "doc-1"
    assert document_storage.received_store_arguments["content"] == b"document-bytes"
    assert document_storage.received_store_arguments["created_by"] == "tester"


@pytest.mark.asyncio
async def test_update_document_metadata_service_records_field_diff():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

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
                "metadata": {
                    "notes": "Original notes",
                    "date": "2026-06-18",
                },
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

    handler = service_handlers["update_document_metadata"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "document_id": "doc-1",
            "title": "Updated title",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
    ):
        await handler(call)

    updated_document = store.assets["asset_1"]["documents"][0]
    audit_entry = store.assets["asset_1"]["audit_log"][-1]

    assert updated_document["title"] == "Updated title"
    assert audit_entry["action"] == "update_document_metadata"
    assert audit_entry["details"]["changed_fields"] == ["title"]
    assert audit_entry["details"]["field_changes"]["title"] == {
        "before": "Original title",
        "after": "Updated title",
    }


@pytest.mark.asyncio
async def test_get_asset_history_service_returns_classified_filters():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "name": "Test asset",
        "asset_type": "electronics",
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

    handler = service_handlers["get_asset_history"]
    call = SimpleNamespace(data={"asset_id": "asset_1", "max_entries": 20}, context=SimpleNamespace(user_id=None))

    with patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        payload = await handler(call)

    assert [entry["kind"] for entry in payload["by_filter"]["audit"]] == ["audit"]
    assert [entry["kind"] for entry in payload["by_filter"]["documents"]] == ["documents"]
    assert [entry["kind"] for entry in payload["by_filter"]["custody"]] == ["custody"]
    assert [entry["kind"] for entry in payload["by_filter"]["environment"]] == ["environment"]


@pytest.mark.asyncio
async def test_get_asset_history_service_returns_empty_payload_when_asset_missing():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

    handler = service_handlers["get_asset_history"]
    call = SimpleNamespace(data={"asset_id": "missing_asset", "max_entries": 20}, context=SimpleNamespace(user_id=None))

    with patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        payload = await handler(call)

    assert payload["asset_id"] == "missing_asset"
    assert payload["found"] is False
    assert payload["all"] == []
    assert payload["by_filter"]["all"] == []


@pytest.mark.asyncio
async def test_attach_document_service_adds_document_and_audit_entry():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["attach_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "type": "manual",
            "title": "Attached document",
            "provider_document_id": "external/manual-1.pdf",
            "filename": "manual-1.pdf",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
    ):
        await handler(call)

    updated_asset = store.assets["asset_1"]
    attached_doc = updated_asset["documents"][0]
    assert len(updated_asset["documents"]) == 1
    assert attached_doc["provider_document_id"] == "external/manual-1.pdf"
    assert attached_doc["filename"] == "manual-1.pdf"
    assert updated_asset["audit_log"][-1]["action"] == "attach_document"


@pytest.mark.asyncio
async def test_delete_document_service_removes_document_and_calls_storage_delete():
    hass, entry, service_handlers, store, document_storage = _build_hass()
    await _setup_integration(hass)

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
                "metadata": {
                    "preview_provider_document_id": "asset_1/doc-1_preview.pdf",
                },
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

    handler = service_handlers["delete_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "document_id": "doc-1",
            "delete_storage": True,
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._get_document_storage", return_value=document_storage),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
    ):
        await handler(call)

    updated_asset = store.assets["asset_1"]
    assert updated_asset["documents"] == []
    assert document_storage.received_delete_document_arguments == {
        "provider_document_id": "asset_1/doc-1_warranty.pdf",
    }
    assert document_storage.received_delete_preview_arguments == {
        "preview_provider_document_id": "asset_1/doc-1_preview.pdf",
    }
    assert updated_asset["audit_log"][-1]["action"] == "delete_document"


@pytest.mark.asyncio
async def test_upload_document_service_raises_when_asset_missing():
    hass, entry, service_handlers, store, document_storage = _build_hass()
    await _setup_integration(hass)

    handler = service_handlers["upload_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "missing_asset",
            "type": "manual",
            "title": "Warranty sheet",
            "filename": "warranty.pdf",
            "content_base64": base64.b64encode(b"document-bytes").decode(),
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._get_document_storage", return_value=document_storage),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
    ):
        with pytest.raises(HomeAssistantError, match="Asset 'missing_asset' not found"):
            await handler(call)


@pytest.mark.asyncio
async def test_attach_document_service_raises_when_tags_is_not_list():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["attach_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "type": "manual",
            "provider_document_id": "external/manual-1.pdf",
            "filename": "manual-1.pdf",
            "tags": "not-a-list",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        with pytest.raises(HomeAssistantError, match="tags must be a list"):
            await handler(call)


@pytest.mark.asyncio
async def test_attach_document_service_raises_when_provider_id_missing():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["attach_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "type": "manual",
            "filename": "manual-1.pdf",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        with pytest.raises(HomeAssistantError, match="provider_document_id is required"):
            await handler(call)


@pytest.mark.asyncio
async def test_update_document_metadata_service_raises_when_document_not_found():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["update_document_metadata"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "document_id": "missing-doc",
            "title": "Updated title",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        with pytest.raises(HomeAssistantError, match="Document not found on asset"):
            await handler(call)


@pytest.mark.asyncio
async def test_delete_document_service_raises_when_identifier_missing():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["delete_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with patch("custom_components.asset_intelligence.__init__._get_store", return_value=store):
        with pytest.raises(HomeAssistantError, match="Provide document_id or provider_document_id"):
            await handler(call)


@pytest.mark.asyncio
async def test_delete_document_service_raises_when_document_not_found():
    hass, entry, service_handlers, store, document_storage = _build_hass()
    await _setup_integration(hass)

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

    handler = service_handlers["delete_document"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "document_id": "missing-doc",
            "delete_storage": True,
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._get_document_storage", return_value=document_storage),
    ):
        with pytest.raises(HomeAssistantError, match="Document not found on asset"):
            await handler(call)


@pytest.mark.asyncio
async def test_delete_asset_service_deletes_attached_documents_then_asset():
    hass, entry, service_handlers, store, document_storage = _build_hass()
    await _setup_integration(hass)

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "name": "Test asset",
        "asset_type": "electronics",
        "documents": [
            {
                "document_id": "doc-1",
                "type": "warranty",
                "filename": "warranty.pdf",
                "provider_document_id": "asset_1/doc-1_warranty.pdf",
                "metadata": {"preview_provider_document_id": "asset_1/doc-1_preview.pdf"},
            },
            {
                "document_id": "doc-2",
                "type": "manual",
                "filename": "manual.pdf",
                "provider_document_id": "asset_1/doc-2_manual.pdf",
                "metadata": {"preview_provider_document_id": "asset_1/doc-2_preview.pdf"},
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

    handler = service_handlers["delete_asset"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    fake_entity_registry = SimpleNamespace(
        async_get_entity_id=MagicMock(return_value=None),
        async_remove=MagicMock(),
    )
    fake_device_registry = SimpleNamespace(
        async_get_device=MagicMock(return_value=None),
        async_remove_device=MagicMock(return_value=True),
        async_update_device=MagicMock(),
    )

    with (
        patch("custom_components.asset_intelligence.__init__._get_store", return_value=store),
        patch("custom_components.asset_intelligence.__init__._refresh_runtime", AsyncMock()),
        patch("custom_components.asset_intelligence.__init__.er.async_get", return_value=fake_entity_registry),
        patch("custom_components.asset_intelligence.__init__.dr.async_get", return_value=fake_device_registry),
    ):
        await handler(call)

    assert "asset_1" not in store.assets
    assert len(document_storage.delete_document_calls) == 2
    assert document_storage.delete_document_calls == [
        {"provider_document_id": "asset_1/doc-1_warranty.pdf"},
        {"provider_document_id": "asset_1/doc-2_manual.pdf"},
    ]
    assert document_storage.delete_asset_folder_calls == [{"asset_id": "asset_1"}]


@pytest.mark.asyncio
async def test_smoke_core_services_are_registered():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

    # Smoke test: critical document and history service handlers are present.
    assert "upload_document" in service_handlers
    assert "attach_document" in service_handlers
    assert "update_document_metadata" in service_handlers
    assert "delete_document" in service_handlers
    assert "get_asset_history" in service_handlers


@pytest.mark.asyncio
async def test_start_measurement_service_sets_active_measurement_and_audit_entry():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "name": "Test asset",
        "asset_type": "electronics",
        "room_environment": {
            "climate": {"temperature": 71.2, "humidity": 44.5},
            "light": {"lux": 120},
        },
        "audit_log": [],
    }

    handler = service_handlers["start_measurement"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    await handler(call)

    active = store.assets["asset_1"]["active_measurement"]
    assert active["started_at"] == "2026-06-23T00:00:00+00:00"
    assert active["started_by"] == "tester"
    assert active["update_count"] == 0
    assert active["stop_requested"] is False
    assert isinstance(active["initial_room_environment"], dict)
    assert store.assets["asset_1"]["audit_log"][-1]["action"] == "start_measurement"
    assert store.assets["asset_1"]["audit_log"][-1]["details"]["started_at"] == "2026-06-23T00:00:00+00:00"


@pytest.mark.asyncio
async def test_stop_measurement_service_marks_stop_request():
    hass, entry, service_handlers, store, _ = _build_hass()
    await _setup_integration(hass)

    store.assets["asset_1"] = {
        "asset_id": "asset_1",
        "name": "Test asset",
        "asset_type": "electronics",
        "audit_log": [],
        "active_measurement": {
            "started_at": "2026-06-23T00:00:00+00:00",
            "started_by": "tester",
            "observations": [],
            "update_count": 0,
            "stop_requested": False,
        },
    }

    handler = service_handlers["stop_measurement"]
    call = SimpleNamespace(
        data={
            "asset_id": "asset_1",
            "actor": "tester",
        },
        context=SimpleNamespace(user_id=None),
    )

    await handler(call)

    active = store.assets["asset_1"]["active_measurement"]
    assert active["stop_requested"] is True
    assert active["stop_requested_at"] == "2026-06-23T00:00:00+00:00"
    assert active["stop_requested_by"] == "tester"