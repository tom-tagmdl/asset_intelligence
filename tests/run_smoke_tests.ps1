$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot\.."
try {
    .\.venv\Scripts\python.exe -m pytest -q tests\test_services.py -k "smoke or upload_document_service_updates_asset_and_audit_log or attach_document_service_adds_document_and_audit_entry or delete_document_service_removes_document_and_calls_storage_delete"
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
