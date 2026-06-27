# Asset Intelligence

Asset Intelligence is a Home Assistant custom integration for tracking high-value assets, the documents attached to them, custody and loan status, room environment requirements, and activity history.

It is intended for collections, equipment, archives, and other assets where provenance and operational history matter as much as the current asset record.

## What It Provides

- Asset records with metadata, placement, and room assignment
- Document storage and protected document viewing
- Document actions such as upload, attach, update metadata, and delete
- Custody and loan tracking
- Room environment state and environment requirements
- Activity history for audit, document, custody, environment, and risk events

## Installation

1. Copy the `asset_intelligence` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration**.
4. Select **Asset Intelligence**.
5. Finish the setup and configure document storage in the integration options if you want document management.

## Configuration

The integration is configured through the Home Assistant UI.

The main options are:

- Default labels for new assets
- Document storage path
- Whether document management is enabled
- Optional storage requirements for network-based document locations

Document storage must point to a path Home Assistant can read, such as `/config/`, `/share/`, or `/media/`.
If the path is invalid or unavailable, document management remains disabled.

## Supported Actions

The integration exposes the following service actions:

- `add_asset`
- `update_asset`
- `delete_asset`
- `link_to_device`
- `unlink_from_device`
- `add_tracker`
- `remove_tracker`
- `configure_document_storage`
- `upload_document`
- `attach_document`
- `update_document_metadata`
- `delete_document`
- `get_document_info`
- `check_document_availability`
- `get_asset_history`
- `add_physical_document_location`
- `set_environment_requirements`
- `set_room_environment`
- `set_custody_status`
- `record_loan_out`
- `record_loan_in`
- `export_inventory`

See the [examples guide](asset_intelligence_examples.md) for concrete service call patterns.

## Supported Entities

The integration provides Home Assistant entities that surface the current asset record and related state.
Depending on how the asset is configured, these entities can include:

- Asset summary and status
- At-risk indicator
- Document projections
- Room environment projection
- Custody and loan-related state
- Activity summaries

## How Data Updates

Asset Intelligence is driven by the integration runtime and the stored asset records.

- Asset and document actions write to the integration store and append activity records
- Room environment changes are derived from stored room configuration and coordinator updates
- Activity history is served on demand from the backend history service
- Protected document images are retrieved through the authenticated document view endpoint

Because the history is fetched from the backend service, the UI stays responsive and avoids relying on large entity attributes for the activity timeline.

## Known Limitations

- This is a custom integration, not a core Home Assistant integration.
- It currently supports a single config entry.
- Document storage must use a Home Assistant readable local path.
- Reauthentication is not applicable because the integration does not use external account credentials.
- Some features are intentionally tuned for stored assets and recorded actions rather than live device discovery.

## Use Cases

- Track artwork, collectibles, and archive materials with supporting documents
- Record museum or loan movement for assets with custody handoffs
- Keep a living inventory with room/environment context
- Attach appraisals, certificates, receipts, and images to each asset
- Review activity history for audit and provenance investigations

## Troubleshooting

If something is not working as expected, see the [troubleshooting guide](asset_intelligence_troubleshooting.md).

## Removal

1. Remove the integration from **Settings > Devices & services**.
2. Delete the `custom_components/asset_intelligence` folder.
3. Restart Home Assistant.

## Related Docs

- [Examples](asset_intelligence_examples.md)
- [Troubleshooting](asset_intelligence_troubleshooting.md)
