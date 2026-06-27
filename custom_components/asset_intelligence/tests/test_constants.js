let WINDOW_DIRECTIONS, WINDOW_EXPOSURES, DOCUMENT_TYPES, PHYSICAL_DOCUMENT_LOCATIONS, MAX_BROWSER_DOCUMENT_UPLOAD_BYTES;

if (typeof window.AI_CONSTANTS_LOADED === 'undefined') {
  WINDOW_DIRECTIONS = [
    "north","northeast","east","southeast",
    "south","southwest","west","northwest"
  ];

  WINDOW_EXPOSURES = [
    "direct","indirect","shaded"
  ];

  DOCUMENT_TYPES = [
    "photo",
    "receipt",
    "invoice",
    "warranty",
    "manual",
    "appraisal",
    "insurance_policy",
    "certificate_of_authenticity",
    "provenance_record",
    "condition_report",
    "restoration_record",
    "loan_agreement",
    "shipping_document",
    "installation_instructions",
    "maintenance_record",
    "other",
  ];

  PHYSICAL_DOCUMENT_LOCATIONS = [
    "safe",
    "safe_deposit_box",
    "binder",
    "offsite_archive",
    "with_agent",
    "bank",
    "other",
  ];

  MAX_BROWSER_DOCUMENT_UPLOAD_BYTES = 15 * 1024 * 1024;
  window.AI_CONSTANTS_LOADED = true;
}
