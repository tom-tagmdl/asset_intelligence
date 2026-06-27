# Asset Intelligence Examples

## Example 1: Record an asset and attach a document

1. Create the asset with `add_asset`.
2. Upload the document with `upload_document`.
3. Use the document card in the UI to add metadata, location, or delete it later.

Example service calls:

```yaml
service: asset_intelligence.add_asset
data:
  asset_id: art_001
  name: Blue Landscape
  area_id: living_room
```

```yaml
service: asset_intelligence.upload_document
data:
  asset_id: art_001
  type: appraisal
  source_path: /config/documents/blue_landscape_appraisal.pdf
  title: 2026 Appraisal
  notes: Insurance valuation
```

## Example 2: Set environmental requirements for an asset

Use `set_environment_requirements` to record the acceptable conditions for the asset.

```yaml
service: asset_intelligence.set_environment_requirements
data:
  asset_id: art_001
  actor: Tom
  environment_requirements:
    temperature:
      min: 18
      max: 24
      units: C
    humidity:
      min: 40
      max: 55
      units: percent
```

## Example 3: Record custody and loan activity

Use custody services to show when an asset is checked out and returned.

```yaml
service: asset_intelligence.record_loan_out
data:
  asset_id: art_001
  actor: Tom
  counterparty: Dallas Museum of Art
```

```yaml
service: asset_intelligence.record_loan_in
data:
  asset_id: art_001
  actor: Tom
  counterparty: Dallas Museum of Art
```

## Example 4: Query activity history

Use `get_asset_history` to retrieve the backend-generated history payload for the asset.

```yaml
service: asset_intelligence.get_asset_history
data:
  asset_id: art_001
  max_entries: 80
```
