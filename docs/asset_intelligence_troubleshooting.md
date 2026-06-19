# Asset Intelligence Troubleshooting

## Document storage is unavailable

If document uploads fail, verify that the configured document storage path exists and is readable by Home Assistant.

Common checks:

- Confirm the path points to `/config/`, `/share/`, or `/media/`
- Confirm the folder exists on disk
- Confirm document management is enabled in the integration options
- Confirm the storage is mounted and available at startup

## Documents do not appear in the UI

If a document exists but does not show up as expected:

- Open the asset record and confirm the document is attached
- Check that the document has a valid `document_id`
- Confirm the file is still present in storage
- Confirm the browser session is authenticated when viewing protected document URLs

## Activity history looks incomplete

If the activity list does not show the expected entries:

- Refresh the asset detail view
- Confirm the integration was reloaded after a code change
- Verify the relevant service call was recorded in the asset audit log
- Check that the asset has the expected document, custody, or environment data in storage

## Reconfigure settings do not apply

If document path or defaults do not seem to update:

- Open the integration entry from **Settings > Devices & services**
- Use the reconfigure flow to update the settings
- Reload the integration if prompted

## Where to check logs

Home Assistant logs are the best place to confirm integration startup and service failures.
Look for messages from the `asset_intelligence` integration if something unexpected happens.
