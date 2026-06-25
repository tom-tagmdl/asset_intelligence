var WINDOW_DIRECTIONS = globalThis.__AI_WINDOW_DIRECTIONS || [
  "north","northeast","east","southeast",
  "south","southwest","west","northwest"
];
globalThis.__AI_WINDOW_DIRECTIONS = WINDOW_DIRECTIONS;

var WINDOW_EXPOSURES = globalThis.__AI_WINDOW_EXPOSURES || [
  "direct","indirect","shaded"
];
globalThis.__AI_WINDOW_EXPOSURES = WINDOW_EXPOSURES;

var DOCUMENT_TYPES = globalThis.__AI_DOCUMENT_TYPES || [
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
globalThis.__AI_DOCUMENT_TYPES = DOCUMENT_TYPES;

var PHYSICAL_DOCUMENT_LOCATIONS = globalThis.__AI_PHYSICAL_DOCUMENT_LOCATIONS || [
  "safe",
  "safe_deposit_box",
  "binder",
  "offsite_archive",
  "with_agent",
  "bank",
  "other",
];
globalThis.__AI_PHYSICAL_DOCUMENT_LOCATIONS = PHYSICAL_DOCUMENT_LOCATIONS;

// Max safe size for base64-encoded websocket uploads (4MB limit / 1.33 base64 expansion = ~3MB)
var MAX_BROWSER_DOCUMENT_UPLOAD_BYTES = globalThis.__AI_MAX_BROWSER_DOCUMENT_UPLOAD_BYTES || (3 * 1024 * 1024);
globalThis.__AI_MAX_BROWSER_DOCUMENT_UPLOAD_BYTES = MAX_BROWSER_DOCUMENT_UPLOAD_BYTES;

var AssetIntelligenceApp = globalThis.AssetIntelligenceApp || class AssetIntelligenceApp extends HTMLElement {
  constructor() {
    super();
    this._view = { type: "home" };
    this._hass = null;
    this._areas = [];
    this._floors = [];
    this._loaded = false;
    this._loadError = null;
    this._entityRegistry = [];
    this._roomConfig = {};
    this._systemDefaults = {};
    this._editingMetric = null;
    this._editingWindowIndex = null;
    this.deviceRegistry = [];
    this._draftMetrics = {};
    this._draftWindows = {};
    this._showAllSensorsByMetric = {};
    this._labelRegistry = [];
    // Γ£à Temporary unsaved values for Asset Detail form fields
    this._assetInfoDrafts = {};
    // Γ£à Temporary unsaved values for Asset Detail environment limits
    this._assetEnvironmentDrafts = {};
    this._assetHistoryFilter = "all";
    this._assetHistoryCache = {};
    this._assetHistoryLoading = {};
    this._roomHistoryFilterByRoom = {};
    this._roomHistoryAssetFilterByRoom = {};
    this._measurementTicker = null;
    this._assetDetailInteractionActive = false;
    this._assetDetailInteractionTimer = null;
    this._roomConfigInteractionActive = false;
    this._roomConfigInteractionTimer = null;
    // Γ£à Cache for authenticated protected image blob URLs
    this._protectedImageBlobCache = {};
    this._subscribedConnection = null;
    this._renderDebounceTimer = null;
    this._renderQueued = false;

    // MutationObserver to catch HA picker/selector elements that upgrade later
    this._ai_mutation_observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of Array.from(m.addedNodes)) {
          if (!(node instanceof HTMLElement)) continue;
          const tag = (node.tagName || "").toLowerCase();
          if (["ha-area-picker","ha-labels-picker","ha-selector","ha-icon-picker","ha-entity-picker"].includes(tag)) {
            try {
              if (this._hass) node.hass = this._hass;
            } catch (e) {}
            if (tag === "ha-selector" && (node.selector === undefined || node.selector === null)) {
              try { node.selector = {}; } catch (e) {}
            }
            if (tag === "ha-labels-picker" && (node.value === undefined || node.value === null)) {
              try { node.value = []; } catch (e) {}
            }
            if ((tag === "ha-area-picker" || tag === "ha-entity-picker") && (node.value === undefined || node.value === null)) {
              try { node.value = ""; } catch (e) {}
            }
            if (typeof node.requestUpdate === "function") {
              try { node.requestUpdate(); } catch (e) {}
            }
          }
        }
      }
    });
    this._docStorageEventUnsub = null;
    this._labelRegistryEventUnsub = null;
    this._documentStorageAvailable = null; // null = unknown, true/false = explicit
    this._boundShowDialogHandler = this._handleShowDialogEvent.bind(this);
    this._boundBeforeUnloadHandler = this._handleBeforeUnload.bind(this);
  }

  connectedCallback() {
    if (super.connectedCallback) super.connectedCallback();
    document.addEventListener("show-dialog", this._boundShowDialogHandler);
    window.addEventListener("beforeunload", this._boundBeforeUnloadHandler);
    this._bindRoomConfigDelegation();
  }

  _bindRoomConfigDelegation() {
    // Single delegated handler on the component root ΓÇö survives innerHTML replacement.
    // Handles all room-config action buttons (edit, save, cancel, remove metric).
    if (this._roomConfigDelegationBound) return;
    this._roomConfigDelegationBound = true;

    // Set interaction guard on pointerdown so a pending hass update
    // can't replace the DOM between pointerdown and click.
    this.addEventListener("pointerdown", (e) => {
      if (this._view?.type !== "room-config") return;
      const btn = e.target?.closest(
        "[data-edit-metric],[data-save-metric],[data-cancel-metric],[data-remove-metric]"
      );
      if (!btn) return;
      this._roomConfigInteractionActive = true;
      if (this._roomConfigInteractionTimer) clearTimeout(this._roomConfigInteractionTimer);
      this._roomConfigInteractionTimer = setTimeout(() => {
        this._roomConfigInteractionActive = false;
        this._roomConfigInteractionTimer = null;
      }, 800);
    }, true);

    this.addEventListener("click", (e) => {
      if (this._view?.type !== "room-config") return;

      const editBtn = e.target?.closest("[data-edit-metric]");
      if (editBtn) {
        e.stopPropagation();
        const fieldPath = editBtn.getAttribute("data-edit-metric");
        if (!fieldPath) return;
        this._roomConfigInteractionActive = false;
        this._editingMetric = fieldPath;
        this._render();
        requestAnimationFrame(() => {
          Promise.resolve().then(() => {
            const picker = this.querySelector(`ha-entity-picker[data-metric="${fieldPath}"]`);
            if (!picker) return;
            try { picker.hass = this._hass; } catch (_) {}
            try {
              const roomId = this._view?.roomId;
              if (roomId) picker.entityFilter = this._createMetricEntityFilter(roomId, fieldPath);
            } catch (_) {}
            try { if (typeof picker.requestUpdate === "function") picker.requestUpdate(); } catch (_) {}
          });
        });
        return;
      }

      const cancelBtn = e.target?.closest("[data-cancel-metric]");
      if (cancelBtn) {
        e.stopPropagation();
        const fieldPath = cancelBtn.getAttribute("data-cancel-metric");
        if (fieldPath && this._draftMetrics[fieldPath]) delete this._draftMetrics[fieldPath];
        this._editingMetric = null;
        this._roomConfigInteractionActive = false;
        this._render();
        return;
      }

      const removeBtn = e.target?.closest("[data-remove-metric]");
      if (removeBtn) {
        e.stopPropagation();
        const fieldPath = removeBtn.getAttribute("data-remove-metric");
        if (fieldPath) this._draftMetrics[fieldPath] = { entity: "" };
        this._editingMetric = null;
        this._roomConfigInteractionActive = false;
        this._render();
        return;
      }

      const saveBtn = e.target?.closest("[data-save-metric]");
      if (saveBtn) {
        e.stopPropagation();
        const fieldPath = saveBtn.getAttribute("data-save-metric");
        if (!fieldPath) return;
        const picker = this.querySelector(`ha-entity-picker[data-metric="${fieldPath}"]`);
        const selected =
          this._draftMetrics[fieldPath]?.entity ??
          picker?.value ??
          picker?.entityId ??
          picker?.selected ??
          "";
        if (!this._draftMetrics[fieldPath]) this._draftMetrics[fieldPath] = {};
        this._draftMetrics[fieldPath].entity = selected;
        this._editingMetric = null;
        this._roomConfigInteractionActive = false;
        this._render();
        return;
      }
    }, true);
  }

  disconnectedCallback() {
    try { this._ai_mutation_observer?.disconnect(); } catch (e) {}
    if (super.disconnectedCallback) super.disconnectedCallback();
    try { if (this._docStorageEventUnsub) this._docStorageEventUnsub(); } catch (e) {}
    this._docStorageEventUnsub = null;
    try { if (this._labelRegistryEventUnsub) this._labelRegistryEventUnsub(); } catch (e) {}
    this._labelRegistryEventUnsub = null;
    this._subscribedConnection = null;
    try {
      if (this._renderDebounceTimer) {
        clearTimeout(this._renderDebounceTimer);
        this._renderDebounceTimer = null;
      }
    } catch (e) {}
    try {
      if (this._measurementTicker) {
        clearInterval(this._measurementTicker);
        this._measurementTicker = null;
      }
    } catch (e) {}
    try { document.removeEventListener("show-dialog", this._boundShowDialogHandler); } catch (e) {}
    try { window.removeEventListener("beforeunload", this._boundBeforeUnloadHandler); } catch (e) {}
    // Clean up blob URLs
    try {
      Object.values(this._protectedImageBlobCache || {}).forEach((blobUrl) => {
        try { URL.revokeObjectURL(blobUrl); } catch (e) {}
      });
      this._protectedImageBlobCache = {};
    } catch (e) {}
  }

  set hass(hass) {
    this._hass = hass;

    // Γ£à If the user is editing Asset Detail and has unsaved draft values,
    // do NOT repaint the screen from live backend updates.
    const currentAssetId = this._view?.type === "asset-detail"
      ? this._view?.assetId
      : null;

    const hasActiveAssetDraft =
      !!currentAssetId &&
      !!this._assetInfoDrafts?.[currentAssetId] &&
      Object.keys(this._assetInfoDrafts[currentAssetId]).length > 0;

    if (this._assetDetailInteractionActive && this._view?.type === "asset-detail") {
      return;
    }

    if (!this._loaded) {
      this._load();
      return;
    }

    // Subscribe once per active HA connection so we do not churn subscriptions
    // on every state update (which can happen very frequently in production).
    try {
      const connection = this._hass?.connection || null;
      if (
        connection
        && connection !== this._subscribedConnection
        && typeof connection.subscribeEvents === "function"
      ) {
        if (this._docStorageEventUnsub) {
          try { this._docStorageEventUnsub(); } catch (e) {}
          this._docStorageEventUnsub = null;
        }

        if (this._labelRegistryEventUnsub) {
          try { this._labelRegistryEventUnsub(); } catch (e) {}
          this._labelRegistryEventUnsub = null;
        }

        this._docStorageEventUnsub = connection.subscribeEvents((event) => {
          try {
            const avail = event?.data?.available;
            if (typeof avail === "boolean") {
              this._documentStorageAvailable = avail;
            }
            this._scheduleRender(0);
          } catch (e) {}
        }, "asset_intelligence_document_storage_availability_changed");

        this._labelRegistryEventUnsub = connection.subscribeEvents(() => {
          this._refreshLabelRegistry();
        }, "label_registry_updated");

        this._subscribedConnection = connection;
      }
    } catch (e) {}

    if (hasActiveAssetDraft || this._editingMetric) {
      return;
    }

    this._scheduleRender(120);

    if (this._labelRegistry.length) {
      this._applyLabelRegistryToPickers();
    } else {
      this._refreshLabelRegistry();
    }
  }

  get hass() {
    return this._hass;
  } 

  _getMetricDef(fieldPath) {
    if (!fieldPath || typeof fieldPath !== "string") return null;
    const [category, metric] = fieldPath.split(".");
    const categoryConfig = this._getCategoryConfig() || {};
    return categoryConfig[category]?.[metric] || null;
  }

  _createMetricEntityFilter(roomId, fieldPath) {
    const metricDef = this._getMetricDef(fieldPath);
    if (!metricDef || !roomId || !this._hass?.states) return () => false;

    const entityDomain = metricDef.entityDomain || "sensor";
    const requiredPrefix = `${entityDomain}.`;
    const requiredDeviceClass = metricDef.deviceClass || null;
    const showAll = !!this._showAllSensorsByMetric?.[fieldPath];
    const nameIncludes = Array.isArray(metricDef.nameIncludes)
      ? metricDef.nameIncludes.map((token) => String(token).toLowerCase())
      : [];
    const unitIncludes = Array.isArray(metricDef.unitIncludes)
      ? metricDef.unitIncludes.map((token) => String(token).toLowerCase())
      : [];

    return (entity) => {
      if (!entity || typeof entity !== "object" || !entity.entity_id) return false;
      if (!entity.entity_id.startsWith(requiredPrefix)) return false;

      const matchesMetricType = this._matchesMetricEntityType(entity, metricDef);
      if (showAll) {
        return matchesMetricType;
      }

      const entityAreaId = this._getAreaIdForEntity(entity.entity_id);
      if (entityAreaId !== roomId) return false;

      return matchesMetricType;
    };
  }

  _matchesMetricEntityType(entity, metricDef) {
    if (!entity || typeof entity !== "object" || !metricDef || typeof metricDef !== "object") {
      return false;
    }

    const attrs = entity.attributes || {};
    const deviceClass = String(attrs.device_class || "").toLowerCase();
    const unit = String(attrs.unit_of_measurement || "").toLowerCase();
    const normalized = `${entity.entity_id} ${attrs.friendly_name || ""}`.toLowerCase();

    const requiredDeviceClass = String(metricDef.deviceClass || "").toLowerCase();
    if (requiredDeviceClass && deviceClass === requiredDeviceClass) {
      return true;
    }

    const nameIncludes = Array.isArray(metricDef.nameIncludes)
      ? metricDef.nameIncludes.map((token) => String(token).toLowerCase())
      : [];
    const unitIncludes = Array.isArray(metricDef.unitIncludes)
      ? metricDef.unitIncludes.map((token) => String(token).toLowerCase())
      : [];

    const matchesName =
      nameIncludes.length > 0 &&
      nameIncludes.some((token) => normalized.includes(token));

    const matchesUnit =
      unitIncludes.length > 0 &&
      unitIncludes.some((token) => unit.includes(token));

    if (nameIncludes.length > 0 || unitIncludes.length > 0) {
      return matchesName || matchesUnit;
    }

    if (requiredDeviceClass) {
      return deviceClass === requiredDeviceClass;
    }

    return true;
  }

  _applyHassToHAElements() {
    if (!this._hass) return;

    const elements = this.querySelectorAll(
      "ha-area-picker, ha-labels-picker, ha-selector, ha-icon-picker, ha-entity-picker"
    );

    elements.forEach((el) => {
      if (!el) return;
      if (el.hass !== this._hass) {
        try { el.hass = this._hass; } catch (e) {}
      }

      const tag = (el.tagName || "").toLowerCase();
      if (tag === "ha-selector" && (el.selector === undefined || el.selector === null)) {
        try { el.selector = {}; } catch (e) {}
      }
      if (tag === "ha-labels-picker" && (el.value === undefined || el.value === null)) {
        try { el.value = []; } catch (e) {}
      }
      if ((tag === "ha-area-picker" || tag === "ha-entity-picker") && (el.value === undefined || el.value === null)) {
        try { el.value = ""; } catch (e) {}
      }

      if (tag === "ha-entity-picker" && el.dataset.metric && this._view?.type === "room-config") {
        const fieldPath = el.dataset.metric;
        const roomId = this._view.roomId;
        const currentValue =
          this._draftMetrics[fieldPath]?.entity ||
          this._getConfiguredSensorForMetric(
            this._getRoomEntities().find((r) => r.attributes?.area_id === roomId),
            fieldPath
          ) ||
          el.value ||
          "";

        try { el.entityFilter = this._createMetricEntityFilter(roomId, fieldPath); } catch (e) {}
        try { el.value = currentValue; } catch (e) {}
      }

      if (typeof el.requestUpdate === "function") {
        try { el.requestUpdate(); } catch (e) {}
      }
    });

    this._applyLabelRegistryToPickers();
  }

  async _refreshLabelRegistry() {
    if (!this._hass?.connection) return;

    try {
      const labels = await this._hass.callWS({
        type: "config/label_registry/list",
      });
      this._labelRegistry = Array.isArray(labels) ? labels : [];
      this._refreshAllLabelPickers();
    } catch (err) {
      console.warn("Failed to load label registry", err);
    }
  }

  _applyLabelRegistryToPickers(root = this) {
    const labels = Array.isArray(this._labelRegistry) ? this._labelRegistry : [];

    root.querySelectorAll("ha-label-picker, ha-labels-picker").forEach((picker) => {
      try { picker._labels = labels; } catch (e) {}
      try {
        if (typeof picker.requestUpdate === "function") {
          picker.requestUpdate();
        }
      } catch (e) {}

      if (picker.tagName && picker.tagName.toLowerCase() === "ha-labels-picker") {
        Promise.resolve(picker.updateComplete)
          .catch(() => undefined)
          .then(() => {
            const innerPicker = picker.labelPicker || picker.shadowRoot?.querySelector("ha-label-picker");
            if (!innerPicker) return;

            try { innerPicker._labels = labels; } catch (e) {}
            try {
              if (typeof innerPicker.requestUpdate === "function") {
                innerPicker.requestUpdate();
              }
            } catch (e) {}
          });
      }
    });
  }

  _refreshAllLabelPickers() {
    this._applyLabelRegistryToPickers();

    if (document.body && document.body !== this) {
      this._applyLabelRegistryToPickers(document.body);
    }
  }

  _getDefaultLabelIds() {
    const states = this._hass?.states || {};

    const normalize = (value) => {
      if (!Array.isArray(value)) return [];
      return value
        .map((labelId) => String(labelId || "").trim())
        .filter((labelId) => !!labelId);
    };

    const extractFromAttrs = (attrs) => {
      if (!attrs || typeof attrs !== "object") return [];

      const direct = normalize(attrs.default_label_ids);
      if (direct.length) return direct;

      const systemDefaults = attrs.system_defaults;
      if (systemDefaults && typeof systemDefaults === "object") {
        const nested = normalize(systemDefaults.default_label_ids);
        if (nested.length) return nested;
      }

      return [];
    };

    // Primary source: persisted system defaults loaded from integration storage.
    const persistedDefaults = normalize(this._systemDefaults?.default_label_ids);
    if (persistedDefaults.length) {
      return persistedDefaults;
    }

    // Preferred known summary sensor IDs (may vary by naming/translation).
    const preferredEntities = [
      "sensor.asset_intelligence_assets",
      "sensor.asset_intelligence_asset_list",
    ];

    for (const entityId of preferredEntities) {
      const labels = extractFromAttrs(states?.[entityId]?.attributes || {});
      if (labels.length) return labels;
    }

    // Fallback: scan all Asset Intelligence sensors for defaults.
    for (const state of Object.values(states)) {
      const entityId = String(state?.entity_id || "");
      if (!entityId.startsWith("sensor.asset_intelligence_")) continue;

      const labels = extractFromAttrs(state?.attributes || {});
      if (labels.length) return labels;
    }

    return [];
  }

  _handleShowDialogEvent(event) {
    const detail = event?.detail || {};
    if (detail.dialogTag !== "dialog-label-detail") {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    this._openLabelDetailDialog(
      detail.dialogParams || {},
      this._resolveLabelDialogSource(event)
    );
  }

  _resolveLabelDialogSource(event) {
    const path = typeof event?.composedPath === "function" ? event.composedPath() : [];

    for (const node of path) {
      if (!(node instanceof HTMLElement)) {
        continue;
      }

      const tag = String(node.tagName || "").toLowerCase();
      if (tag === "ha-label-picker") {
        return node;
      }

      if (tag === "ha-labels-picker") {
        return node.labelPicker || node.shadowRoot?.querySelector("ha-label-picker") || node;
      }
    }

    const fallback = event?.target instanceof HTMLElement ? event.target : null;
    if (!fallback) {
      return null;
    }

    const fallbackTag = String(fallback.tagName || "").toLowerCase();
    if (fallbackTag === "ha-labels-picker") {
      return fallback.labelPicker || fallback.shadowRoot?.querySelector("ha-label-picker") || fallback;
    }

    return fallback;
  }

  _openLabelDetailDialog(params = {}, sourcePicker = null) {
    const entry = params.entry || null;
    const isEdit = !!entry;
    const dialog = document.createElement("ha-dialog");
    dialog.open = true;

    const initialName = String(params.suggestedName || entry?.name || "");
    const initialIcon = String(entry?.icon || "");
    const initialColor = String(entry?.color || "");
    const initialDescription = String(entry?.description || "");

    dialog.innerHTML = `
      <style>
        .ai-label-dialog-shell {
          min-width: 420px;
          max-width: 560px;
        }

        .ai-label-dialog-title {
          font-size: 18px;
          font-weight: 700;
          padding: 20px 24px 8px 24px;
          color: var(--primary-text-color);
        }

        .ai-label-dialog-body {
          display: flex;
          flex-direction: column;
          gap: 14px;
          padding: 8px 24px 16px 24px;
        }

        .ai-label-dialog-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .ai-label-dialog-field label {
          font-size: 12px;
          font-weight: 600;
          color: var(--secondary-text-color);
        }

        .ai-label-dialog-field ha-icon-picker,
        .ai-label-dialog-field ha-color-picker {
          display: block;
          width: 100%;
        }

        .ai-label-dialog-input {
          width: 100%;
          min-height: 48px;
          box-sizing: border-box;
          padding: 12px 14px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 15px;
          outline: none;
        }

        .ai-label-dialog-actions {
          display: flex;
          justify-content: flex-end;
          align-items: center;
          gap: 12px;
          padding: 8px 24px 24px 24px;
        }

        .ai-label-dialog-secondary-btn {
          appearance: none;
          border: none;
          background: transparent;
          color: var(--primary-color);
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          padding: 10px 4px;
        }

        .ai-label-dialog-primary-btn {
          appearance: none;
          border: none;
          border-radius: 20px;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          padding: 10px 18px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.2));
        }

        .ai-label-dialog-primary-btn:disabled {
          opacity: 0.55;
          cursor: default;
        }

        .ai-label-dialog-error {
          color: var(--error-color, #db4437);
          font-size: 13px;
          padding: 0 24px;
        }
      </style>

      <div class="ai-label-dialog-shell">
        <div class="ai-label-dialog-title">${isEdit ? "Edit Label" : "Add Label"}</div>

        <div class="ai-label-dialog-body">
          <div class="ai-label-dialog-field">
            <label for="ai-label-name">Name</label>
            <input id="ai-label-name" class="ai-label-dialog-input" type="text" value="${this._escapeHtml(initialName)}" autocomplete="off" />
          </div>

          <div class="ai-label-dialog-field">
            <label for="ai-label-icon">Icon</label>
            <ha-icon-picker id="ai-label-icon-picker"></ha-icon-picker>
          </div>

          <div class="ai-label-dialog-field">
            <label for="ai-label-color">Color</label>
            <ha-color-picker id="ai-label-color-picker"></ha-color-picker>
          </div>

          <div class="ai-label-dialog-field">
            <label for="ai-label-description">Description</label>
            <input id="ai-label-description" class="ai-label-dialog-input" type="text" value="${this._escapeHtml(initialDescription)}" />
          </div>
        </div>

        <div class="ai-label-dialog-error" id="ai-label-error" hidden></div>

        <div class="ai-label-dialog-actions">
          <button type="button" class="ai-label-dialog-secondary-btn" id="ai-label-cancel">Cancel</button>
          <button type="button" class="ai-label-dialog-primary-btn" id="ai-label-save">${isEdit ? "Save" : "Create Label"}</button>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    const nameInput = dialog.querySelector("#ai-label-name");
    const iconPicker = dialog.querySelector("#ai-label-icon-picker");
    const colorPicker = dialog.querySelector("#ai-label-color-picker");
    const descriptionInput = dialog.querySelector("#ai-label-description");
    const cancelBtn = dialog.querySelector("#ai-label-cancel");
    const saveBtn = dialog.querySelector("#ai-label-save");
    const errorEl = dialog.querySelector("#ai-label-error");
    let selectedIcon = initialIcon || "";
    let selectedColor = initialColor || "";

    const readControlValue = (control, fallback = "") => {
      const rawValue = control?.value ?? control?._value ?? fallback;
      return typeof rawValue === "string" ? rawValue : String(rawValue || "");
    };

    const syncSelectedIcon = (value) => {
      selectedIcon = readControlValue({ value }, selectedIcon).trim();
    };

    const syncSelectedColor = (value) => {
      selectedColor = readControlValue({ value }, selectedColor).trim();
    };

    Promise.allSettled([
      window.customElements?.whenDefined?.("ha-icon-picker"),
      window.customElements?.whenDefined?.("ha-color-picker"),
    ]).then(() => {
      if (iconPicker) {
        try { iconPicker.hass = this._hass; } catch (e) {}
        try { iconPicker.value = initialIcon || ""; } catch (e) {}
        try { iconPicker.configValue = "icon"; } catch (e) {}
        syncSelectedIcon(initialIcon || "");
      }

      if (colorPicker) {
        try { colorPicker.value = initialColor || ""; } catch (e) {}
        try { colorPicker.defaultColor = initialColor || undefined; } catch (e) {}
        try { colorPicker.label = ""; } catch (e) {}
        syncSelectedColor(initialColor || "");
      }
    });

    iconPicker?.addEventListener("value-changed", (ev) => {
      syncSelectedIcon(ev.detail?.value);
    });

    iconPicker?.addEventListener("change", () => {
      syncSelectedIcon(readControlValue(iconPicker, selectedIcon));
    });

    colorPicker?.addEventListener("value-changed", (ev) => {
      syncSelectedColor(ev.detail?.value);
    });

    colorPicker?.addEventListener("change", () => {
      syncSelectedColor(readControlValue(colorPicker, selectedColor));
    });

    const updateSaveState = () => {
      const hasName = !!String(nameInput?.value || "").trim();
      if (saveBtn) {
        saveBtn.disabled = !hasName;
      }
    };

    const showError = (message) => {
      if (!errorEl) return;
      errorEl.textContent = message || "";
      errorEl.hidden = !message;
    };

    const closeDialog = () => dialog.remove();

    cancelBtn.onclick = () => closeDialog();
    dialog.addEventListener("closed", () => closeDialog());

    nameInput?.addEventListener("input", () => {
      showError("");
      updateSaveState();
    });

    saveBtn.onclick = async () => {
      const values = {
        name: String(nameInput?.value || "").trim(),
        icon: readControlValue(iconPicker, selectedIcon).trim() || null,
        color: readControlValue(colorPicker, selectedColor).trim() || null,
        description: String(descriptionInput?.value || "").trim() || null,
      };

      if (!values.name) {
        updateSaveState();
        return;
      }

      try {
        saveBtn.disabled = true;
        let result;

        if (isEdit && typeof params.updateEntry === "function") {
          result = await params.updateEntry(values);
        } else if (!isEdit) {
          result = await this._hass.callWS({
            type: "config/label_registry/create",
            ...values,
          });
        } else {
          result = await this._hass.callWS({
            type: isEdit ? "config/label_registry/update" : "config/label_registry/create",
            ...(isEdit ? { label_id: entry.label_id } : {}),
            ...values,
          });
        }

        const createdLabel = !isEdit && result && result.label_id ? result : null;
        if (createdLabel) {
          this._mergeLabelRegistryEntry(createdLabel);
          this._selectCreatedLabel(sourcePicker, createdLabel.label_id);
        }

        await this._refreshLabelRegistry();
        closeDialog();
      } catch (err) {
        showError(err?.message || "Failed to save label");
        saveBtn.disabled = false;
      }
    };

    updateSaveState();
    nameInput?.focus();
  }

  _mergeLabelRegistryEntry(label) {
    if (!label?.label_id) return;

    const next = Array.isArray(this._labelRegistry) ? [...this._labelRegistry] : [];
    const index = next.findIndex((entry) => entry?.label_id === label.label_id);

    if (index >= 0) {
      next[index] = label;
    } else {
      next.push(label);
    }

    this._labelRegistry = next;
    this._refreshAllLabelPickers();
  }

  _selectCreatedLabel(sourcePicker, labelId) {
    if (!sourcePicker || !labelId) return;

    if (String(sourcePicker.tagName || "").toLowerCase() === "ha-labels-picker") {
      sourcePicker = sourcePicker.labelPicker || sourcePicker.shadowRoot?.querySelector("ha-label-picker") || sourcePicker;
    }

    const isNativeLabelPicker = String(sourcePicker.tagName || "").toLowerCase() === "ha-label-picker";

    if (isNativeLabelPicker) {
      try {
        sourcePicker._labels = this._labelRegistry || [];
      } catch (e) {}

      const hasLabel = Array.isArray(sourcePicker._labels)
        ? sourcePicker._labels.some((label) => label?.label_id === labelId)
        : false;

      try {
        if (hasLabel && typeof sourcePicker._setValue === "function") {
          sourcePicker._setValue(labelId);
          return;
        }

        sourcePicker._pendingLabelId = labelId;
        if (typeof sourcePicker.requestUpdate === "function") {
          sourcePicker.requestUpdate();
        }
      } catch (e) {}
    }

    const hostPicker = sourcePicker.getRootNode?.()?.host;
    const multiPicker = hostPicker && String(hostPicker.tagName || "").toLowerCase() === "ha-labels-picker"
      ? hostPicker
      : null;

    if (multiPicker) {
      const currentValues = Array.isArray(multiPicker.value) ? multiPicker.value : [];
      const nextValues = currentValues.includes(labelId)
        ? currentValues
        : [...currentValues, labelId];

      this._assetDraft = {
        ...(this._assetDraft || {}),
        label_ids: [...nextValues],
      };

      try {
        if (typeof multiPicker._setValue === "function") {
          multiPicker._setValue(nextValues);
        }
      } catch (e) {}

      try {
        multiPicker.value = [...nextValues];
      } catch (e) {}

      try {
        if (typeof multiPicker.requestUpdate === "function") {
          multiPicker.requestUpdate();
        }
      } catch (e) {}

      try {
        multiPicker.dispatchEvent(new CustomEvent("value-changed", {
          detail: { value: nextValues },
          bubbles: true,
          composed: true,
        }));
        multiPicker.dispatchEvent(new Event("change", {
          bubbles: true,
          composed: true,
        }));
      } catch (e) {}

      try {
        if (multiPicker.labelPicker) {
          multiPicker.labelPicker.value = "";
          multiPicker.labelPicker._labels = this._labelRegistry || [];
          if (typeof multiPicker.labelPicker.requestUpdate === "function") {
            multiPicker.labelPicker.requestUpdate();
          }
        }
      } catch (e) {}

      return;
    }

    try {
      if (typeof sourcePicker._setValue === "function") {
        sourcePicker._setValue(labelId);
        return;
      }
    } catch (e) {}

    try {
      sourcePicker.value = labelId;
      sourcePicker.dispatchEvent(new CustomEvent("value-changed", {
        detail: { value: labelId },
        bubbles: true,
        composed: true,
      }));
      sourcePicker.dispatchEvent(new Event("change", {
        bubbles: true,
        composed: true,
      }));
    } catch (e) {}
  }

  _ensurePickerDefinitions() {
    if (!window.customElements) return;

    [
      "ha-area-picker",
      "ha-labels-picker",
      "ha-selector",
      "ha-icon-picker",
      "ha-entity-picker",
      "ha-color-picker",
    ].forEach((tag) => {
      try {
        window.customElements.whenDefined(tag).then(() => {
          if (typeof this._applyHassToHAElements === "function") {
            this._applyHassToHAElements();
          }
        });
      } catch (e) {
        // Ignore whenDefined failures on older or restricted environments.
      }
    });
  }

  async _load() {
    try {
      // --------------------------------------------------
      // Core registries (unchanged)
      // --------------------------------------------------
      this._areas = await this._hass.callWS({
        type: "config/area_registry/list",
      });

      this._floors = await this._hass.callWS({
        type: "config/floor_registry/list",
      });

      this._entityRegistry = await this._hass.callWS({
        type: "config/entity_registry/list",
      });

      this._deviceRegistry = await this._hass.callWS({
        type: "config/device_registry/list",
      });

      // --------------------------------------------------
      // âœ… TEMPORARY: Load persisted Room Configuration
      // (matches storage.py system-of-record)
      // --------------------------------------------------
      try {
        const storage = await this._hass.callWS({
          type: "homeassistant_storage/get",
          key: "asset_intelligence.storage",
        });

        this._roomConfig = storage?.data?.rooms || {};
        this._systemDefaults = storage?.data?.system_defaults || {};

        console.log("ROOM CONFIG LOADED", this._roomConfig);

      } catch (storageError) {
        console.warn("Room config storage load failed", storageError);
        this._roomConfig = {};
        this._systemDefaults = {};
      }

      // --------------------------------------------------
      // Loaded successfully
      // --------------------------------------------------
      this._loaded = true;
      this._loadError = null;
      this._assetHistoryCache = {};
      this._assetHistoryLoading = {};

      if (!this._labelRegistryEventUnsub && this._hass?.connection) {
        this._labelRegistryEventUnsub = this._hass.connection.subscribeEvents(() => {
          this._refreshLabelRegistry();
        }, "label_registry_updated");
      }

      this._refreshLabelRegistry();

    } catch (e) {
      console.error("Asset Intelligence registry load failed", e);
      this._loadError = e;
    }

    this._render();
  }

  _render() {
    if (!this._hass) return;

    // âœ… If the user is editing Asset null;  // âœ… If the user is editing Asset Detail and has unsaved draft values,

    const currentAssetId =
        this._view?.type === "asset-detail"
          ? this._view?.assetId
          : null;

      const hasActiveAssetDraft =
        !!currentAssetId &&
        !!this._assetInfoDrafts?.[currentAssetId] &&
        Object.keys(this._assetInfoDrafts[currentAssetId]).length > 0;

      if (this._assetDetailInteractionActive && this._view?.type === "asset-detail") {
      return;
    }

      if (hasActiveAssetDraft) {
      return;
    }

    if (this._roomConfigInteractionActive && this._view?.type === "room-config") {
      return;
    }

    const active = document.activeElement;
    if (
      active &&
      active.closest &&
      (active.closest(".ai-form-control") || active.closest(".ai-config-row"))
    ) {
      return;
    }

    try {
    const roomEntities = this._getRoomEntities();
    const assetEntities = this._getAssetEntities();
    // Determine document storage state from backend flags.
    // - enabled: integration setting (documents_enabled)
    // - available: runtime read/write availability
    let documentStorageAvailable = null;
    let documentManagementEnabled = null;
    if (typeof this._documentStorageAvailable === "boolean") {
      documentStorageAvailable = this._documentStorageAvailable;
    }

    try {
      const bin = this._hass?.states?.["binary_sensor.asset_intelligence_document_storage_available"];
      if (bin) {
        if (typeof bin.state === "string") {
          documentStorageAvailable = bin.state === "on";
        }

        const enabledAttr = bin.attributes?.documents_enabled;
        if (typeof enabledAttr === "boolean") {
          documentManagementEnabled = enabledAttr;
        }
      }
    } catch (e) {
      // Keep derived values as-is.
    }

    if (documentManagementEnabled === null) {
      documentManagementEnabled =
        Array.isArray(assetEntities)
        && assetEntities.some(
          (a) => a?.attributes?.documents_enabled === true
            || a?.attributes?.document_storage_configured === true
        );
    }

    if (documentManagementEnabled === null) {
      documentManagementEnabled = !!documentStorageAvailable;
    }

    const documentStorageState = {
      enabled: !!documentManagementEnabled,
      available: !!documentStorageAvailable,
    };

    const areaMap = {};
    this._areas.forEach((a) => {
      if (a && a.area_id) areaMap[a.area_id] = a;
    });

    const floorMap = {};
    this._floors.forEach((f) => {
      if (f && f.floor_id) floorMap[f.floor_id] = f;
    });

    let content = "";

    if (this._view.type === "room") {
      content = this._renderRoomDetail(
        this._view.roomId,
        roomEntities,
        assetEntities,
        areaMap,
        floorMap,
        documentStorageAvailable
      );

    } else if (this._view.type === "room-config") {
      content = this._renderRoomConfig(
        this._view.roomId,
        roomEntities,
        areaMap
      );

    } else if (this._view.type === "asset-detail") {
      content = this._renderAssetDetail(
        this._view.assetId,
        assetEntities,
        areaMap,
        documentStorageState
      );

    } else if (this._view.type === "floor") {
      content = this._renderFloorDetail(
        this._view.floorName,
        roomEntities,
        assetEntities,
        areaMap,
        floorMap
      );

    } else {
      content = this._renderHome(
        roomEntities,
        assetEntities,
        areaMap,
        floorMap,
        documentStorageState
      );
      
      this._initializeAssetDetailPickers();

    }

    this.innerHTML = `
      <style>
        .ai-container {
          padding: 16px;
          max-width: 1500px;
          margin: auto;
          font-family: sans-serif;
          color: var(--primary-text-color);
        }

        .ai-title-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 4px;
        }

        .ai-title {
          font-size: 2rem;
          font-weight: 700;
          margin: 0;
        }

        .ai-subtitle {
          color: var(--secondary-text-color, #666);
          margin-bottom: 20px;
        }

        .ai-back-button,
        .ai-gear-button {
          appearance: none;
          border: 1px solid #ddd;
          border-radius: 8px;
          background: var(--card-background-color);
          padding: 6px 10px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
        }

        .ai-back-button:hover,
        .ai-gear-button:hover {
          background: #f5f5f5;
        }

        .ai-icon-wrap {
          width: 72px;
          height: 72px;
          border-radius: 50%;
          background: rgba(255,255,255,0.05);
          box-shadow: inset 0 1px 2px rgba(255,255,255,0.4);
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
          z-index: 1;
        }

        .ai-assets-label {
          font-size: 16px;
          font-weight: 700;
          color: var(--primary-text-color);
        }

        .ai-assets-value {
          font-size: 16px;
          font-weight: 700;
          color: var(--primary-text-color);
        }

        .ai-floor {
          margin-bottom: 28px;
        }

        .ai-floor-title {
          margin-bottom: 10px;
          font-size: 1.1rem;
          font-weight: 700;
        }

        .ai-floor-button {
          appearance: none;
          border: none;
          background: transparent;
          padding: 0;
          margin: 0;
          font: inherit;
          color: inherit;
          cursor: pointer;
          font-weight: 700;
        }

        .ai-floor-button:hover {
          text-decoration: underline;
        }

        .ai-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 14px;
        }

        .ai-card {
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          background: var(--card-background-color);
          overflow: hidden;
          display: flex;
          flex-direction: column;
          box-shadow: 0 1px 4px rgba(0,0,0,0.08);
          min-height: 380px;
        }

        .ai-card-top {
          height: 160px;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
          border-bottom: 1px solid var(--divider-color);
          background-size: cover;
          background-position: center;
          background-repeat: no-repeat;
          border-radius: 14px 14px 0 0;
          overflow: hidden;
        }

        .ai-card-top.has-image {
          position: relative;
          background-size: 110%;
          background-color: var(--secondary-background-color);
        }

        /* Defensive precedence: when a card has an image, suppress any fallback icon. */
        .ai-card-top.has-image .ai-icon-wrap,
        .ai-card-top.has-image > ha-icon,
        .ai-asset-hero.has-image .ai-icon-wrap,
        .ai-asset-hero.has-image > ha-icon {
          display: none !important;
        }

        /* Room page hard guard: image cards should render background image only. */
        .ai-room-asset-card .ai-card-top.has-image > * {
          display: none !important;
        }

        .ai-card-top.has-image::after {
          content: "";
          position: absolute;
          inset: 0;

          background: linear-gradient(
            to bottom,
            rgba(0,0,0,0) 40%,
            rgba(0,0,0,0.35) 100%
          );
        }

        .ai-card-top:not(.has-image) {
          background: linear-gradient(
            180deg,
            var(--secondary-background-color),
            rgba(255,255,255,0.02)
          );
        }


        .ai-card-body {
          padding: 14px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          flex: 1;
        }

        .ai-room-click {
          min-height: 320px;
        }

        .ai-room-click .ai-card-top {
          height: 108px;
        }

        .ai-room-click .ai-card-body {
          padding: 12px;
          gap: 6px;
        }

        .ai-room-click .ai-room-name {
          font-size: 1.1rem;
          margin-bottom: 2px;
        }

        .ai-room-click .ai-room-summary {
          font-size: 12px;
        }

        .ai-room-name,
        .ai-asset-name {
          font-size: 1.3rem;
          font-weight: 700;
          margin-bottom: 6px;
        }

        .ai-data-grid {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 6px 12px;
          font-size: 13px;
        }

        .ai-data-label {
          font-weight: 600;
          color: var(--secondary-text-color);
        }

        .ai-data-value {
          color: var(--primary-text-color);
          text-align: right;
          white-space: nowrap;
        }

        .ai-room-metrics-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 6px 10px;
          font-size: 12px;
        }

        .ai-room-metric-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          min-width: 0;
        }

        .ai-room-metric-item .ai-data-label,
        .ai-room-metric-item .ai-data-value {
          font-size: 12px;
        }

        .ai-room-metric-item .ai-data-label {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ai-room-metric-item .ai-data-value {
          flex: 0 0 auto;
        }

        .ai-highlight {
          font-weight: 700;
          font-size: 1rem;
          color: #111;
        }

        .ai-divider {
          height: 1px;
          background: #eee;
          margin: 8px 0;
        }

        .ai-updated {
          margin-top: 4px;
          font-size: 12px;
          color: var(--secondary-text-color);
        }

        @media (max-width: 900px) {
          .ai-room-metrics-grid {
            grid-template-columns: 1fr;
          }
        }

        .ai-status-bar {
          display: flex;
          height: 36px;
          width: 100%;
          border-top: 1px solid #ddd;
        }

        .ai-status-half {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.02em;
          text-transform: uppercase;
        }

        .ai-room-summary {
          display: flex;
          justify-content: space-between;
          font-size: 13px;
          color: var(--secondary-text-color);
        }

        .ai-room-summary strong {
          color: var(--primary-text-color);
        }


        .ai-status-half:first-child {
          border-right: 1px solid rgba(255,255,255,0.3);
        }

        .ai-error {
          color: #b3261e;
          margin-bottom: 16px;
          font-size: 14px;
        }

        .ai-empty {
          color: var(--secondary-text-color);
          padding-top: 8px;
        }

        .ai-room-click,
        .ai-asset-click {
          cursor: pointer;
        }

        .ai-room-click:hover .ai-room-name,
        .ai-asset-click:hover .ai-asset-name {
          text-decoration: underline;
        }

        .ai-breadcrumb {
          font-size: 14px;
          margin-bottom: 12px;
          font-weight: 400;
          color: var(--secondary-text-color);
        }

        .ai-breadcrumb button {
          appearance: none;
          border: none;
          background: transparent;
          padding: 0;
          margin: 0;
          font: inherit;
          color: inherit;
          cursor: pointer;
          text-decoration: underline;
          color: var(--secondary-text-color);
        }

        .ai-breadcrumb .ai-breadcrumb-current {
          font-size: 14px;
          margin-bottom: 12px;
          font-weight: 600;
          color: var(--primary-text-color);
        }

        .ai-header-card {
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          background: var(--card-background-color);
          box-shadow:
            0 2px 6px rgba(0,0,0,0.08),
            inset 0 1px 0 rgba(255,255,255,0.6);
        }

        .ai-header-body {
          padding: 16px;
        }

        .ai-header-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 12px;
        }

        .ai-header-title {
          font-size: 1.65rem;
          font-weight: 700;
          letter-spacing: 0.01em;
        }


        .ai-header-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          row-gap: 14px;
          gap: 16px;
        }

        .ai-group-card {
          border: none;
          border-radius: 0;
          padding: 8px 10px;
          background: transparent;
        }

        .ai-header-grid > .ai-group-card {
          border-right: 1px solid rgba(0,0,0,0.04);
          padding-right: 14px;
        }

        .ai-header-grid > .ai-group-card:last-child {
          border-right: none;
        }

        .ai-group-title {
          font-size: 0.98rem;
          font-weight: 700;
          margin-bottom: 6px;
          letter-spacing: 0.02em;
        }

        .ai-group-row {
          display: flex;
          justify-content: space-between;
          font-size: 13px;
          margin-bottom: 4px;
        }

        .ai-group-row span:last-child {
          min-width: 72px;
          text-align: right;
          font-variant-numeric: tabular-nums;
          color: var(--primary-text-color);
        }

        .ai-muted {
          color: var(--secondary-text-color);
          margin-top: -2px;
        }

        .ai-metric-label {
          font-weight: 600;
        }

        .ai-asset-detail-grid {
          display: grid;
          grid-template-columns: 110px 1fr;
          gap: 6px 12px;
          font-size: 13px;
          align-items: start;
        }

        .ai-asset-detail-label {
          font-weight: 600;
          color: var(--secondary-text-color);
        }

        .ai-asset-detail-value {
          color: var(--primary-text-color);
          min-width: 0;
        }

        .ai-risk-reason-text {
          font-weight: 600;
          color: #333;
        }

        .ai-separator {
          margin: 0 6px;
          color: var(--secondary-text-color);
        }

        .ai-risk-badge {
          color: #ef5350;
          font-weight: 700;
        }

        .ai-value-high {
          color: #c62828;
          font-weight: 700;
        }

        .ai-value-moderate {
          color: #ef6c00;
          font-weight: 600;
        }

        /* Base risk cell */
        .ai-asset-status-cell.ai-risk-cell {
          color: #ffffff;
        }

        /* Ensure label and value both go white */
        .ai-asset-status-cell.ai-risk-cell .ai-asset-status-label,
        .ai-asset-status-cell.ai-risk-cell .ai-asset-status-value {
          color: #ffffff;
          opacity: 0.85;
        }

        /* GREEN */
        .ai-asset-status-cell.ai-risk-green {
          background-color: #2e7d32;
        }

        /* AMBER */
        .ai-asset-status-cell.ai-risk-amber {
          background-color: #ef6c00;
        }

        /* RED */
        .ai-asset-status-cell.ai-risk-red {
          background-color: #c62828;
        }


        .ai-truncate {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ai-room-asset-card {
          min-height: auto;
        }

        .ai-room-asset-card .ai-card-body {
          gap: 10px;
        }

        .ai-asset-summary {
          font-size: 13px;
          font-weight: 600;
          color: var(--secondary-text-color)
        }

        .ai-section-title {
          font-size: 1.1rem;
          font-weight: 700;
          letter-spacing: 0.04em;
          padding-bottom: 6px;
          margin-bottom: 10px;
          border-bottom: 1px solid var(--divider-color);
        }        
        

        .ai-section-label {
          margin: 16px 0 10px;
          padding: 6px 12px;
          font-size: 12.5px;
          font-weight: 700;
          letter-spacing: 0.03em;
          color: var(--primary-text-color);
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 8px;
        }

        .ai-truncate {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ai-config-section {
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          padding: 14px;
          margin-bottom: 16px;
          overflow: visible;
        }

        .ai-config-row {
          display: grid;
          grid-template-columns: 160px 1fr 120px 160px;
          align-items: center;
          gap: 12px;
          padding: 4px 0;
          overflow: visible;
        }

        ha-entity-picker.ai-config-dropdown {
          display: block;
          width: 100%;
          min-width: 320px;
        }

        select.ai-config-dropdown {
          display: block;
          width: 100%;
          min-width: 0;
          box-sizing: border-box;
          position: relative;
          z-index: 2;
        }

        .ai-config-row ha-entity-picker {
          display: block;
          width: 100%;
          min-width: 320px;
        }

        .ai-config-toggle {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 2px;
          font-size: 12px;
          line-height: 1.2;
          color: var(--secondary-text-color);
          user-select: none;
        }

        .ai-config-toggle input[type="checkbox"] {
          margin: 0;
          flex: 0 0 auto;
        }

        .ai-config-readonly {
          display: flex;
          align-items: center;

          width: 100%;
          min-height: 40px;

          padding: 0 12px;

          border-radius: 6px;
          border: 1px solid var(--divider-color);

          background: var(--card-background-color);

          font-size: 14px;
          color: var(--primary-text-color);

          box-sizing: border-box;
          transition: border-color 0.15s ease;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ai-link-btn {
          border: none;
          background: none;
          color: var(--primary-color);
          cursor: pointer;
        }

        .ai-danger {
          color: #ef5350;
        }        

        .ai-footer-actions {
          display: flex;
          justify-content: flex-end;
          margin-top: 20px;
        }

        .ai-primary-button {
          appearance: none;
          border: none;
          border-radius: 20px;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          padding: 10px 22px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.2));
        }

        .ai-primary-button:hover {
          filter: brightness(0.95);
        }

        .ai-primary-button:disabled {
          opacity: 0.6;
          cursor: default;
        }

        .ai-tag {
          background: var(--secondary-background-color);
          padding: 4px 8px;
          border-radius: 6px;
          font-size: 12px;
        }

        /* ==========================================================
        ASSET DETAIL LAYOUT
        ========================================================== */
        .ai-asset-shell {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .ai-asset-header-card {
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          background: var(--card-background-color);
          box-shadow:
            0 2px 6px rgba(0,0,0,0.08),
            inset 0 1px 0 rgba(255,255,255,0.6);
          overflow: hidden;
        }

        .ai-asset-header-main {
          display: grid;
          grid-template-columns: 96px 1fr auto;
          gap: 16px;
          align-items: center;
          padding: 18px;
        }

        .ai-asset-hero {
          width: 96px;
          height: 96px;
          border-radius: 16px;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
          border: 1px solid var(--divider-color);
          background-size: cover;
          background-position: center;
          background-repeat: no-repeat;
        }

        .ai-asset-hero ha-icon {
          width: 42px;
          height: 42px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          position: relative;
          z-index: 1;
        }

        .ai-asset-hero.has-image {
          background-color: var(--secondary-background-color);
        }

        .ai-asset-header-copy {
          min-width: 0;
        }

        .ai-asset-header-title-row {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          margin-bottom: 8px;
        }

        .ai-asset-header-title {
          font-size: 1.9rem;
          font-weight: 700;
          line-height: 1.1;
          margin: 0;
        }

        .ai-asset-chip-row {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 10px;
        }

        .ai-asset-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          border-radius: 999px;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          font-size: 12px;
          font-weight: 600;
        }

        .ai-asset-summary-line {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          color: var(--secondary-text-color);
          font-size: 13px;
        }

        .ai-asset-summary-line strong {
          color: var(--primary-text-color);
        }

        .ai-asset-header-actions {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 10px;
        }

        .ai-measurement-pill {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          background: var(--primary-color, #03a9f4);
          color: #fff;
          border-radius: 12px;
          padding: 8px 10px;
          min-height: 40px;
          box-shadow: 0 3px 10px rgba(3, 169, 244, 0.35);
        }

        .ai-measurement-elapsed {
          font-size: 13px;
          font-weight: 700;
          letter-spacing: 0.03em;
          white-space: nowrap;
        }

        .ai-measurement-count {
          font-size: 12px;
          font-weight: 600;
          opacity: 0.95;
          white-space: nowrap;
        }

        .ai-measurement-stop {
          appearance: none;
          border: 1px solid rgba(255, 255, 255, 0.45);
          border-radius: 999px;
          width: 30px;
          height: 30px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: rgba(255, 255, 255, 0.17);
          color: #fff;
          cursor: pointer;
        }

        .ai-measurement-stop:hover {
          background: rgba(255, 255, 255, 0.24);
        }

        .ai-measurement-stop ha-icon {
          width: 18px;
          height: 18px;
        }

        .ai-secondary-button {
          appearance: none;
          border: 1px solid var(--divider-color);
          border-radius: 20px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          padding: 9px 16px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
        }

        .ai-secondary-button:hover {
          background: var(--secondary-background-color);
        }

        .ai-overflow {
          position: relative;
        }

        .ai-overflow-button {
          appearance: none;
          border: 1px solid var(--divider-color);
          border-radius: 50%;
          background: var(--card-background-color);
          width: 40px;
          height: 40px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          font-size: 18px;
          line-height: 1;
        }

        .ai-overflow-menu {
          position: absolute;
          right: 0;
          top: calc(100% + 6px);
          min-width: 180px;
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          box-shadow: 0 8px 20px rgba(0,0,0,0.18);
          padding: 8px;
          z-index: 30;
          display: none;
        }

        .ai-overflow.open .ai-overflow-menu {
          display: block;
        }

        .ai-overflow-item {
          appearance: none;
          width: 100%;
          border: none;
          background: transparent;
          text-align: left;
          padding: 10px 12px;
          border-radius: 8px;
          cursor: pointer;
          font-size: 14px;
          color: var(--primary-text-color);
        }

        .ai-overflow-item:hover {
          background: var(--secondary-background-color);
        }

        .ai-overflow-item.ai-danger {
          color: #c62828;
          font-weight: 600;
        }

        .ai-asset-status-strip {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 0;
          border-top: 1px solid var(--divider-color);
        }

        .ai-asset-status-cell {
          padding: 12px 14px;
          border-right: 1px solid var(--divider-color);
        }

        .ai-asset-status-cell:last-child {
          border-right: none;
        }

        .ai-asset-status-label {
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
          font-weight: 700;
        }

        .ai-asset-status-value {
          font-size: 14px;
          font-weight: 700;
          color: var(--primary-text-color);
        }

        .ai-asset-layout {
          display: grid;
          grid-template-columns: minmax(320px, 1.05fr) minmax(420px, 1.2fr) minmax(300px, 0.95fr);
          gap: 18px;
          align-items: start;
        }

        .ai-room-layout {
          display: grid;
          grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr);
          gap: 18px;
          align-items: start;
        }

        .ai-column {
          display: flex;
          flex-direction: column;
          gap: 18px;
          min-width: 0;
        }

        .ai-asset-shell .ai-panel-card {
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: 14px;
          background: var(--ha-card-background, var(--card-background-color));
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.2));
          position: relative;
          overflow: hidden;
        }

        .ai-asset-shell .ai-panel-card::before {
          content: "";
          position: absolute;
          left: 0;
          right: 0;
          top: 0;
          height: 3px;
          background: linear-gradient(
            90deg,
            color-mix(in srgb, var(--primary-color) 82%, white 18%) 0%,
            color-mix(in srgb, var(--primary-color) 40%, transparent 60%) 100%
          );
          opacity: 0.32;
          pointer-events: none;
        }

        .ai-room-shell .ai-panel-card {
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: 14px;
          background: var(--ha-card-background, var(--card-background-color));
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.2));
          position: relative;
          overflow: hidden;
        }

        .ai-room-shell .ai-panel-card::before {
          content: "";
          position: absolute;
          left: 0;
          right: 0;
          top: 0;
          height: 3px;
          background: linear-gradient(
            90deg,
            color-mix(in srgb, var(--primary-color) 82%, white 18%) 0%,
            color-mix(in srgb, var(--primary-color) 40%, transparent 60%) 100%
          );
          opacity: 0.32;
          pointer-events: none;
        }

        .ai-room-shell .ai-panel-body {
          padding: 18px;
        }

        .ai-room-shell .ai-panel-title-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 10px;
        }

        .ai-room-shell .ai-panel-title {
          font-size: 1.02rem;
          font-weight: 700;
          color: var(--primary-text-color);
        }

        .ai-room-shell .ai-panel-subtitle {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }

        .ai-asset-shell .ai-panel-body {
          padding: 18px;
        }

        .ai-asset-shell .ai-panel-title-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 14px;
          padding-bottom: 10px;
          border-bottom: 1px solid color-mix(in srgb, var(--divider-color) 86%, transparent 14%);
        }

        .ai-asset-shell .ai-panel-title {
          font-size: 1.05rem;
          font-weight: 700;
          letter-spacing: 0.01em;
          margin: 0;
        }

        .ai-asset-shell .ai-panel-subtitle {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-top: 3px;
          line-height: 1.45;
        }

        .ai-advisory-banner {
          border: 1px solid rgba(198,40,40,0.22);
          background: rgba(198,40,40,0.08);
          border-radius: 12px;
          padding: 12px 14px;
        }

        .ai-advisory-banner.warning {
          border-color: rgba(239,108,0,0.22);
          background: rgba(239,108,0,0.08);
        }

        .ai-advisory-kicker {
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          margin-bottom: 4px;
        }

        .ai-advisory-title {
          font-size: 14px;
          font-weight: 700;
          margin-bottom: 4px;
        }

        .ai-advisory-copy {
          font-size: 13px;
          color: var(--primary-text-color);
          line-height: 1.45;
        }

        .ai-form-grid {
          display: grid;
          grid-template-columns: 140px minmax(0, 1fr);
          gap: 12px 14px;
          align-items: start;
        }

        .ai-form-label {
          font-size: 13px;
          font-weight: 600;
          color: var(--secondary-text-color);
          padding-top: 10px;
        }

        .ai-form-control,
        .ai-form-control input,
        .ai-form-control textarea,
        .ai-form-control select,
        .ai-form-readonly {
          width: 100%;
          min-width: 0;
          box-sizing: border-box;
        }

        .ai-form-readonly {
          min-height: 42px;
          display: flex;
          align-items: center;
          padding: 0 12px;
          border-radius: 8px;
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 14px;
        }

        .ai-readout-grid {
          display: flex;
          flex-direction: column;
          gap: 0;
        }

        .ai-readout-row {
          display: grid;
          grid-template-columns: 140px minmax(0, 1fr);
          gap: 12px 14px;
          align-items: start;
          padding: 10px 0;
          border-bottom: 1px solid color-mix(in srgb, var(--divider-color) 78%, transparent 22%);
        }

        .ai-readout-row:last-child {
          border-bottom: none;
        }

        .ai-readout-row.ai-readout-section {
          grid-template-columns: 1fr;
          gap: 8px;
        }

        .ai-readout-row.ai-readout-section .ai-readout-label {
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--secondary-text-color);
          padding-top: 0;
        }

        .ai-readout-row.ai-readout-section .ai-readout-value {
          padding-left: 2ch;
        }

        .ai-readout-label {
          font-size: 13px;
          font-weight: 700;
          color: var(--secondary-text-color);
          padding-top: 2px;
        }

        .ai-readout-value {
          font-size: 14px;
          color: var(--primary-text-color);
          line-height: 1.45;
          min-width: 0;
          word-break: break-word;
        }

        .ai-readout-muted {
          color: var(--secondary-text-color);
        }

        .ai-readout-bullets {
          margin: 0;
          padding-left: 18px;
          display: flex;
          flex-direction: column;
          gap: 3px;
        }

        .ai-readout-kv {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .ai-readout-kv-row {
          display: grid;
          grid-template-columns: minmax(120px, auto) minmax(0, 1fr);
          gap: 10px;
        }

        .ai-readout-kv-key {
          color: var(--secondary-text-color);
          font-weight: 600;
        }

        .ai-readout-kv-value {
          color: var(--primary-text-color);
          min-width: 0;
          word-break: break-word;
        }

        .ai-input,
        .ai-textarea,
        .ai-select {
          min-height: 42px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          padding: 10px 12px;
          font-size: 14px;
          outline: none;
        }

        .ai-textarea {
          min-height: 92px;
          resize: vertical;
        }

        .ai-inline-actions {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          margin-top: 14px;
        }

        .ai-plain-button {
          appearance: none;
          border: none;
          background: transparent;
          color: var(--primary-color);
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          padding: 0;
        }

        .ai-plain-button.ai-danger {
          color: #d32f2f;
        }

        .ai-warning-box {
          border: 1px dashed #ef6c00;
          border-radius: 12px;
          background: rgba(239,108,0,0.08);
          padding: 12px 14px;
          color: var(--primary-text-color);
          font-size: 13px;
          line-height: 1.45;
        }

        .ai-doc-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .ai-doc-card {
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          overflow: hidden;
          background: var(--secondary-background-color);
        }

        .ai-doc-body {
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .ai-doc-head {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: start;
        }

        .ai-doc-title {
          font-size: 14px;
          font-weight: 700;
        }

        .ai-doc-meta {
          display: grid;
          grid-template-columns: 120px minmax(0, 1fr);
          gap: 6px 10px;
          font-size: 13px;
        }

        .ai-doc-meta-label {
          color: var(--secondary-text-color);
          font-weight: 600;
        }

        .ai-doc-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
        }

        .ai-doc-action-button {
          appearance: none;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          padding: 6px 12px;
          line-height: 1.2;
          transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
        }

        .ai-doc-action-button.is-ghost {
          border: none;
          background: transparent;
          color: var(--primary-color);
          padding-left: 0;
          padding-right: 0;
        }

        .ai-doc-action-button.is-secondary {
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
        }

        .ai-doc-action-button.is-secondary:hover {
          background: var(--secondary-background-color);
        }

        .ai-doc-action-button.is-danger {
          border: 1px solid #ef9a9a;
          background: #fff5f5;
          color: #c62828;
        }

        .ai-doc-action-button.is-danger:hover {
          background: #ffeaea;
        }

        .ai-doc-action-button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .ai-measure-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .ai-category-card {
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          overflow: hidden;
        }

        .ai-category-head {
          padding: 12px 14px;
          background: var(--secondary-background-color);
          border-bottom: 1px solid var(--divider-color);
          font-size: 14px;
          font-weight: 700;
        }

        .ai-category-body {
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }

        .ai-debounce-grid {
          display: grid;
          grid-template-columns: 1fr;
          gap: 12px;
        }

        .ai-debounce-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 130px;
          gap: 10px;
          align-items: center;
        }

        .ai-debounce-label {
          font-size: 13px;
          font-weight: 700;
          color: var(--primary-text-color);
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }

        .ai-debounce-help {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 16px;
          height: 16px;
          border-radius: 50%;
          border: 1px solid var(--divider-color);
          color: var(--secondary-text-color);
          font-size: 11px;
          font-weight: 700;
          cursor: help;
          user-select: none;
        }

        .ai-debounce-subtle {
          font-size: 12px;
          color: var(--secondary-text-color);
          line-height: 1.45;
        }

        .ai-measure-card {
          display: flex;
          flex-direction: column;
          gap: 3px;
          padding: 4px 0;
        }

        .ai-measure-title-row {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          gap: 8px;
          margin-bottom: 1px;
        }

        .ai-measure-title {
          font-size: 13px;
          font-weight: 700;
        }

        .ai-measure-state {
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
        }

        .ai-measure-state.green { color: #2e7d32; }
        .ai-measure-state.amber { color: #ef6c00; }
        .ai-measure-state.red { color: #c62828; }

        .ai-range-row {
          display: grid;
          grid-template-columns: 64px minmax(0, 1fr) 64px;
          gap: 10px;
          align-items: start;
        }
        .ai-range-input {
          min-height: 25px;
          height: 25px;
          padding: 2px 6px;
          font-size: 13px;
          line-height: 1.2;
          text-align: center;
          font-variant-numeric: tabular-nums;
          }
        .ai-range-input-error {
          border-color: #c62828 !important;
          box-shadow: 0 0 0 1px rgba(198,40,40,0.2);
        }
        .ai-range-track {
          position: relative;
          height: 12px;
          margin-top: 4px;
          margin-bottom: 14px;
          background: linear-gradient(
            to right,
            rgba(198,40,40,0.12) 0%,
            rgba(239,108,0,0.14) 18%,
            rgba(46,125,50,0.16) 35%,
            rgba(46,125,50,0.16) 65%,
            rgba(239,108,0,0.14) 82%,
            rgba(198,40,40,0.12) 100%
          );
          border-radius: 999px;
          overflow: visible;
          border: 1px solid rgba(0,0,0,0.06);
        }
        .ai-range-threshold {
          position: absolute;
          top: -3px;
          width: 2px;
          height: 18px;
          background: rgba(0,0,0,0.25);
          border-radius: 999px;
        }
        .ai-range-threshold-low {
          left: 25%;
          transform: translateX(-50%);
        }
        .ai-range-threshold-high {
          left: 75%;
          transform: translateX(-50%);
        }
        .ai-range-marker {
          position: absolute;
          top: 50%;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          transform: translate(-50%, -50%);
          background: var(--primary-color);
          border: 2px solid white;
          box-shadow: 0 2px 6px rgba(0,0,0,0.18);
        }

        .ai-range-marker.green {
          background-color: #2e7d32;
        }

        .ai-range-marker.amber {
          background-color: #ef6c00;
        }

        .ai-range-marker.red {
          background-color: #c62828;
        }
        .ai-range-current-label {
          position: absolute;
          top: 18px;
          transform: translateX(-50%);
          font-size: 11px;
          color: var(--secondary-text-color);
          white-space: nowrap;
          font-variant-numeric: tabular-nums;
        }
        .ai-measure-detail {
          font-size: 11px;
          line-height: 1.1;
          color: var(--secondary-text-color);
          min-height: 6px;
          margin-top: 1px;
        }

        .ai-timeline-filters {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 12px;
        }

        .ai-filter-chip {
          appearance: none;
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
        }

        .ai-filter-chip.tone-neutral {
          border-color: rgba(96, 125, 139, 0.35);
          color: #455a64;
        }

        .ai-filter-chip.tone-amber {
          border-color: rgba(239, 108, 0, 0.45);
          color: #ef6c00;
        }

        .ai-filter-chip.tone-red {
          border-color: rgba(198, 40, 40, 0.45);
          color: #c62828;
        }

        .ai-filter-chip.tone-green {
          border-color: rgba(46, 125, 50, 0.45);
          color: #2e7d32;
        }

        .ai-filter-chip.active {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          border-color: var(--primary-color);
        }

        .ai-filter-chip.tone-neutral.active {
          background: #607d8b;
          border-color: #607d8b;
          color: #fff;
        }

        .ai-filter-chip.tone-amber.active {
          background: #ef6c00;
          border-color: #ef6c00;
          color: #fff;
        }

        .ai-filter-chip.tone-red.active {
          background: #c62828;
          border-color: #c62828;
          color: #fff;
        }

        .ai-filter-chip.tone-green.active {
          background: #2e7d32;
          border-color: #2e7d32;
          color: #fff;
        }

        .ai-timeline {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .ai-timeline-item {
          border-left: 3px solid var(--divider-color);
          padding-left: 12px;
          cursor: pointer;
          border-radius: 6px;
          transition: background-color 120ms ease;
        }

        .ai-timeline-item:hover {
          background: rgba(0,0,0,0.04);
        }

        .ai-timeline-item.red {
          border-left-color: #c62828;
        }

        .ai-timeline-item.amber {
          border-left-color: #ef6c00;
        }

        .ai-timeline-item.green {
          border-left-color: #2e7d32;
        }

        .ai-timeline-title {
          font-size: 13px;
          font-weight: 700;
          margin-bottom: 2px;
        }

        .ai-timeline-meta {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
        }

        .ai-timeline-copy {
          font-size: 13px;
          line-height: 1.45;
          color: var(--primary-text-color);
        }

        @media (max-width: 1280px) {
          .ai-asset-layout {
            grid-template-columns: 1fr;
          }

          .ai-room-layout {
            grid-template-columns: 1fr;
          }

          .ai-asset-header-main {
            grid-template-columns: 80px 1fr;
          }

          .ai-asset-header-actions {
            grid-column: 1 / -1;
            justify-content: flex-end;
          }

          .ai-asset-status-strip {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }

        @media (max-width: 720px) {
          .ai-form-grid {
            grid-template-columns: 1fr;
          }

          .ai-debounce-row {
            grid-template-columns: 1fr;
            gap: 6px;
          }

          .ai-readout-row {
            grid-template-columns: 1fr;
            gap: 6px;
          }

          .ai-readout-kv-row {
            grid-template-columns: 1fr;
            gap: 2px;
          }

          .ai-form-label {
            padding-top: 0;
          }

          .ai-asset-status-strip {
            grid-template-columns: 1fr;
          }

          .ai-asset-header-main {
            grid-template-columns: 1fr;
          }

          .ai-asset-hero {
            width: 84px;
            height: 84px;
          }
        }

        .ai-fab {
          position: fixed !important;
          bottom: 24px;
          right: 24px;

          display: flex;
          align-items: center;
          gap: 10px;

          padding: 12px 18px;

          border-radius: 28px;
          border: none;

          background: linear-gradient(180deg, #1e88e5 0%, #1976d2 100%);
          color: white;

          font-size: 14px;
          font-weight: 700;

          box-shadow: 0 4px 12px rgba(0,0,0,0.25);
          cursor: pointer;

          z-index: 9999;
        }

        .ai-fab:hover {
          background: linear-gradient(180deg, #1976d2 0%, #1565c0 100%);
        }

        .ai-tag {
          background: var(--secondary-background-color);
          padding: 4px 8px;
          border-radius: 6px;
          font-size: 12px;
        }

      </style>

      <div class="ai-container">
        ${content}
      </div>
    `;

    try {
      if (this._ai_mutation_observer) {
        try { this._ai_mutation_observer.disconnect(); } catch (e) {}
        this._ai_mutation_observer.observe(this, { childList: true, subtree: true });
      }
    } catch (e) {}

    if (typeof this._initializeAssetDetailPickers === "function") {
      this._initializeAssetDetailPickers();
    }

    if (typeof this._primeProtectedImageBackgrounds === "function") {
      this._primeProtectedImageBackgrounds();
    }

    if (this._view?.type === "asset-detail") {
      this._bindAssetDetailInteractionGuards();
    }

    if (typeof this._applyHassToHAElements === "function") {
      this._applyHassToHAElements();
    }
    this._ensurePickerDefinitions();
    this._attachNavigationHandlers();

    requestAnimationFrame(() => {
      if (typeof this._initializeAssetDetailPickers === "function") {
        this._initializeAssetDetailPickers();
      }
      if (typeof this._applyHassToHAElements === "function") {
        this._applyHassToHAElements();
      }
      if (typeof this._applyAuthenticatedImages === "function") {
        this._applyAuthenticatedImages();
      }
      if (typeof this._enforceImageOverIconPrecedence === "function") {
        this._enforceImageOverIconPrecedence();
      }
      if (typeof this._syncMeasurementTimerUi === "function") {
        this._syncMeasurementTimerUi();
      }
      if (this._view?.type === "asset-detail" && this._view?.assetId) {
        this._ensureAssetHistoryLoaded(this._view.assetId);
      }
    });
    } catch (err) {
      console.error("Asset Intelligence render failed", err);
      this.innerHTML = `
        <div style="padding:16px; color: var(--primary-text-color);">
          <div style="font-size:1.2rem; font-weight:700; margin-bottom:8px;">Asset Intelligence</div>
          <div style="background:#ffeceb; border-left:4px solid #d32f2f; padding:12px; border-radius:4px;">
            <div style="font-weight:600; margin-bottom:6px;">Frontend render error</div>
            <div style="font-size:13px; white-space:pre-wrap;">${this._escapeHtml(String(err?.message || err || "Unknown error"))}</div>
          </div>
        </div>
      `;
    }
  }

  /* ===========================
    HOME VIEW
  =========================== */

  _isCoordinatorInitializing(roomEntities) {
    // If all visible room environments are STALE and no recent data, assume initializing
    if (roomEntities.length === 0) return false;
    
    const allStale = roomEntities.every((room) => {
      const confidence = String(room.attributes?.confidence || "").toUpperCase();
      return confidence === "STALE";
    });
    
    return allStale;
  }

  _enforceImageOverIconPrecedence() {
    const imageBackedSelectors = [
      ".ai-card-top.has-image",
      ".ai-asset-hero.has-image",
      ".ai-card-top[data-ai-image-url]",
      ".ai-asset-hero[data-ai-image-url]",
    ];

    imageBackedSelectors.forEach((selector) => {
      this.querySelectorAll(selector).forEach((container) => {
        if (!(container instanceof HTMLElement)) return;

        container.querySelectorAll(".ai-icon-wrap, ha-icon").forEach((node) => {
          try {
            node.remove();
          } catch (e) {}
        });
      });
    });
  }

  _renderHome(roomEntities, assetEntities, areaMap, floorMap, documentStorageState) {
    const grouped = {};

    const storageEnabled = !!documentStorageState?.enabled;
    const storageAvailable = !!documentStorageState?.available;
    const isInitializing = this._isCoordinatorInitializing(roomEntities);

    roomEntities.forEach((room) => {
      const areaId = room.attributes?.area_id || "unknown";
      const area = areaMap[areaId];

      const floorId = area?.floor_id || null;
      const floorName =
        floorId && floorMap[floorId]
          ? floorMap[floorId].name
          : "No Floor";

      if (!grouped[floorName]) grouped[floorName] = [];
      grouped[floorName].push({ room, area });
    });

    const sortedFloorNames = Object.keys(grouped).sort((a, b) => {
      const floorA = this._floors.find((f) => f.name === a);
      const floorB = this._floors.find((f) => f.name === b);

      const levelA =
        typeof floorA?.level === "number" ? floorA.level : Number.MAX_SAFE_INTEGER;
      const levelB =
        typeof floorB?.level === "number" ? floorB.level : Number.MAX_SAFE_INTEGER;

      if (levelA !== levelB) return levelA - levelB;
      return a.localeCompare(b);
    });

    return `
      <div class="ai-title">Asset Intelligence</div>
      <div class="ai-storage-indicator ${storageEnabled ? "available" : "unavailable"}">
        ${storageEnabled
          ? (storageAvailable
              ? "Document Management Enabled"
              : "Document Management Enabled (Storage currently unavailable)")
          : "Document Management Disabled"}
      </div>
      <div class="ai-subtitle">${roomEntities.length} room${roomEntities.length === 1 ? "" : "s"} monitored</div>
      ${
        isInitializing
          ? `<div class="ai-info" style="background: #e3f2fd; border-left: 4px solid #1976d2; padding: 12px 16px; margin: 12px 0; border-radius: 4px;">
              <div style="font-weight: 600; color: #1565c0; margin-bottom: 4px;">â³ Initializing Environment Monitor</div>
              <div style="font-size: 13px; color: #0d47a1;">The system is currently loading room environment data from your sensors. Data will appear once the coordinator completes its first refresh cycle (typically within 1-2 minutes).</div>
            </div>`
          : ``
      }
      ${
        sortedFloorNames.length === 0
          ? `<div class="ai-empty">No rooms found.</div>`
          : sortedFloorNames
              .map((floor) => `
                <div class="ai-floor">
                  <div class="ai-floor-title">
                    <button class="ai-floor-button" data-floor="${this._escapeHtml(floor)}">
                      ðŸ  ${this._escapeHtml(floor)}
                    </button>
                  </div>

                  <div class="ai-grid">
                    ${grouped[floor]
                      .sort((a, b) => {
                        const nameA = this._displayRoomName(a.area, a.room).toLowerCase();
                        const nameB = this._displayRoomName(b.area, b.room).toLowerCase();
                        return nameA.localeCompare(nameB);
                      })
                      .map(({ room, area }) => this._renderRoomCard(room, area, assetEntities))
                      .join("")}
                  </div>
                </div>
              `)
              .join("")
      }
    `;
  }

  /* ===========================
     FLOOR DETAIL VIEW
  =========================== */

  _renderFloorDetail(floorName, roomEntities, assetEntities, areaMap, floorMap) {
    const floorAssets = this._getAssetsForFloor(assetEntities, floorName, areaMap, floorMap);

    return `
      <div class="ai-title-row">
        <button class="ai-back-button" data-nav="home">â† Back</button>
        <div class="ai-title">${this._escapeHtml(floorName)}</div>
      </div>
      <div class="ai-subtitle">${floorAssets.length} asset${floorAssets.length === 1 ? "" : "s"} on this floor</div>

      ${
        floorAssets.length === 0
          ? `<div class="ai-empty">No assets found on this floor.</div>`
          : `<div class="ai-grid">
              ${floorAssets
                .sort((a, b) => {
                  const nameA = this._displayAssetName(a).toLowerCase();
                  const nameB = this._displayAssetName(b).toLowerCase();
                  return nameA.localeCompare(nameB);
                })
                .map((assetEntity) => this._renderAssetCard(assetEntity, areaMap))
                .join("")}
            </div>`
      }
    `;
  }

  /* ===========================
     ROOM DETAIL VIEW
  =========================== */

  _renderRoomDetail(roomId, roomEntities, assetEntities, areaMap, floorMap) {
    const room = roomEntities.find((r) => r.attributes?.area_id === roomId);
    if (!room) {
      return `
        <div class="ai-breadcrumb">
          <button data-nav="home">Asset Intelligence</button> &gt; ${this._escapeHtml(roomName)}
          </div>
        <div class="ai-empty">Room not found.</div>
      `;
    }

    const attrs = room.attributes || {};
    const confidence = String(attrs.confidence || "").toUpperCase();
    const isInitializing = confidence === "STALE";
    const area = areaMap[roomId];
    const roomName = this._displayRoomName(area, room);
    const updatedText = this._formatLocalDateTime(attrs.last_updated);
    const roomAssets = assetEntities.filter((a) => {
      const aAttrs = a.attributes || {};
      return this._resolveAssetRoomAreaId(aAttrs, a.entity_id) === roomId;
    });
    const roomMeasurementHistoryAll = this._buildRoomMeasurementHistory(roomId, roomName, roomAssets);
    const roomHistoryFilter = String(this._roomHistoryFilterByRoom?.[roomId] || "all").toLowerCase();
    const roomHistoryAssetFilter = String(this._roomHistoryAssetFilterByRoom?.[roomId] || "all");
    const roomAssetOptions = roomAssets
      .map((assetEntity) => ({
        asset_id: String(assetEntity?.attributes?.asset_id || "").trim(),
        asset_name: this._displayAssetName(assetEntity),
      }))
      .filter((item) => !!item.asset_id)
      .sort((a, b) => String(a.asset_name || "").localeCompare(String(b.asset_name || "")));

    const roomMeasurementHistory = roomMeasurementHistoryAll.filter((entry) => {
      const details = entry?.details && typeof entry.details === "object" ? entry.details : {};
      const eventType = String(details.event_type || "").toLowerCase();
      const entryAssetId = String(details.asset_id || "").trim();

      if (roomHistoryFilter === "start" && eventType !== "start") return false;
      if (roomHistoryFilter === "stop" && eventType !== "stop") return false;
      if (roomHistoryFilter === "asset") {
        if (roomHistoryAssetFilter && roomHistoryAssetFilter !== "all" && entryAssetId !== roomHistoryAssetFilter) {
          return false;
        }
      }

      return true;
    });

    const roomMeasurementSummary = this._buildRoomMeasurementSummary(
      roomMeasurementHistoryAll,
      roomAssets.length,
    );

    const sourceStatus = attrs.source_status && typeof attrs.source_status === "object"
      ? attrs.source_status
      : {};
    const configuredSignals = Number(sourceStatus.configured_signals || 0);
    const signalsWithData = Number(sourceStatus.signals_with_data || 0);
    const coveragePercent = configuredSignals > 0
      ? Math.round((signalsWithData / configuredSignals) * 100)
      : 0;
    const sourceDetails = sourceStatus.details && typeof sourceStatus.details === "object"
      ? sourceStatus.details
      : {};
    const configuredEntries = Object.entries(sourceDetails).filter(([, meta]) => {
      return meta && typeof meta === "object" && !!meta.configured;
    });
    const missingSignalLabels = configuredEntries
      .filter(([, meta]) => !meta.has_data)
      .map(([key]) => this._titleCase(String(key).replaceAll("_", " ").replaceAll(".", " â€¢ ")));
    const reportingSignalLabels = configuredEntries
      .filter(([, meta]) => !!meta.has_data)
      .map(([key]) => this._titleCase(String(key).replaceAll("_", " ").replaceAll(".", " â€¢ ")));
    const roomConfidenceSummary = (() => {
      const normalized = String(attrs.confidence || "").toUpperCase();
      if (normalized === "GOOD") {
        return "Most configured room signals are reporting valid data.";
      }
      if (normalized === "PARTIAL") {
        return "Some configured room signals are missing data, reducing certainty.";
      }
      if (normalized === "DEGRADED") {
        return "A significant portion of configured room signals are unavailable.";
      }
      if (normalized === "STALE") {
        return "Room signal data is stale or unavailable; confidence is low.";
      }
      return "Confidence is based on configured sensor coverage and data availability.";
    })();

    const humanHealth = attrs.human_health && typeof attrs.human_health === "object"
      ? attrs.human_health
      : {};
    const humanHealthState = String(humanHealth.state || "UNKNOWN").toUpperCase();
    const humanHealthConfidence = String(humanHealth.confidence || "LOW").toUpperCase();
    const humanHealthAdvisoryState = String(humanHealth.advisory_state || humanHealthState || "UNKNOWN").toUpperCase();
    const humanHealthAdvisoryConfidence = String(humanHealth.advisory_confidence || humanHealthConfidence || "LOW").toUpperCase();
    const humanHealthStatusSince = this._formatLocalDateTime(humanHealth.status_since || attrs.last_updated);
    const humanHealthReasons = Array.isArray(humanHealth.reasons)
      ? humanHealth.reasons
      : (typeof humanHealth.reasons === "string" && humanHealth.reasons.trim() ? [humanHealth.reasons.trim()] : []);
    const humanHealthAdvisoryReasons = Array.isArray(humanHealth.advisory_reasons)
      ? humanHealth.advisory_reasons
      : (typeof humanHealth.advisory_reasons === "string" && humanHealth.advisory_reasons.trim() ? [humanHealth.advisory_reasons.trim()] : []);
    const humanHealthObserved = Number(humanHealth.observed_signals || 0);
    const humanHealthTotal = Number(humanHealth.total_signals || 0);

    this._currentHistory = roomMeasurementHistory;

    const climate = attrs.climate || {};
    const light = attrs.light || {};
    const airQuality = attrs.air_quality || {};
    const particulates = attrs.particulates || {};
    const biological = attrs.biological || {};
    const safety = attrs.safety || {};
    const structural = attrs.structural || {};
    const context = attrs.context || {};
    const controlContext = attrs.control_context || {};
    const windows = Array.isArray(attrs.windows) ? attrs.windows : [];

    const temperatureUnit = this._getUnitForRoomField(room, "climate.temperature", " degF");
    const humidityUnit = this._getUnitForRoomField(room, "climate.humidity", " %");
    const dewPointUnit = this._getUnitForRoomField(room, "climate.dew_point", temperatureUnit);

    const luxUnit = this._getUnitForRoomField(room, "light.lux", " lx");

    const vocUnit = this._getUnitForRoomField(room, "air_quality.voc", " ppb");
    const formaldehydeUnit = this._getUnitForRoomField(room, "air_quality.formaldehyde", " ppb");
    const ozoneUnit = this._getUnitForRoomField(room, "air_quality.ozone", " ppb");
    const no2Unit = this._getUnitForRoomField(room, "air_quality.no2", " ppb");

    const pm25Unit = this._getUnitForRoomField(room, "particulates.pm2_5", " ug/m3");
    const pm10Unit = this._getUnitForRoomField(room, "particulates.pm10", " ug/m3");

    const pressureUnit = this._getUnitForRoomField(room, "structural.pressure", " hPa");
    const vibrationUnit = this._getUnitForRoomField(room, "structural.vibration", " mm/s");

    const noiseUnit = this._getUnitForRoomField(room, "context.noise", " dB");
    const co2Unit = this._getUnitForRoomField(room, "control_context.co2", " ppm");

    return `
      <div class="ai-breadcrumb">
        <button data-nav="home">Asset Intelligence</button> &gt; ${this._escapeHtml(roomName)}
      </div>

      ${
        isInitializing
          ? `<div class="ai-info" style="background: #e3f2fd; border-left: 4px solid #1976d2; padding: 12px 16px; margin: 12px 0; border-radius: 4px;">
              <div style="font-weight: 600; color: #1565c0; margin-bottom: 4px;">â³ Loading Room Environment Data</div>
              <div style="font-size: 13px; color: #0d47a1;">Sensor readings are being collected from your devices. Data will appear here once the environment monitor completes its first update cycle.</div>
            </div>`
          : ``
      }

      <div class="ai-header-card">
        <div class="ai-header-body">
          <div class="ai-header-top">
            <div class="ai-header-title">${this._escapeHtml(roomName)}</div>
            <button class="ai-gear-button" data-room-config="${this._escapeHtml(roomId)}" title="Room configuration">âš™ï¸</button>
          </div>

          <div class="ai-header-grid">
            <div class="ai-group-card">
              <div class="ai-group-title">Climate</div>
              <div class="ai-group-row"><span class="ai-muted">Temperature</span><span>${this._displayValueWithUnit(climate.temperature, temperatureUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">Humidity</span><span>${this._displayValueWithUnit(climate.humidity, humidityUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">Dew Point</span><span>${this._displayValueWithUnit(climate.dew_point, dewPointUnit)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Light</div>
              <div class="ai-group-row"><span class="ai-muted">Lux</span><span>${this._displayValueWithUnit(light.lux, luxUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">UV</span><span>${this._displayValue(light.uv)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Air Quality</div>
              <div class="ai-group-row"><span class="ai-muted">VOC</span><span class="${this._getValueSeverity('air_quality.voc', airQuality.voc) === 'high' ? 'ai-value-high' : ''}">${this._displayValueWithUnit(airQuality.voc, vocUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">Formaldehyde</span><span>${this._displayValueWithUnit(airQuality.formaldehyde, formaldehydeUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">Ozone</span><span>${this._displayValueWithUnit(airQuality.ozone, ozoneUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">NO2</span><span>${this._displayValueWithUnit(airQuality.no2, no2Unit)}</span></div>
            </div>


            <div class="ai-group-card">
              <div class="ai-group-title">Particulates</div>
              <div class="ai-group-row"><span class="ai-muted">PM2.5</span><span>${this._displayValueWithUnit(particulates.pm2_5, pm25Unit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">PM10</span><span>${this._displayValueWithUnit(particulates.pm10, pm10Unit)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Biological</div>
              <div class="ai-group-row"><span class="ai-muted">Mold Index</span><span>${this._displayValue(biological.mold_index)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Safety</div>
              <div class="ai-group-row"><span class="ai-muted">Leak</span><span>${this._displayValue(safety.leak)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Structural</div>
              <div class="ai-group-row"><span class="ai-muted">Pressure</span><span>${this._displayValueWithUnit(structural.pressure, pressureUnit)}</span></div>
              <div class="ai-group-row"><span class="ai-muted">Vibration</span><span>${this._displayValueWithUnit(structural.vibration, vibrationUnit)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Context</div>
              <div class="ai-group-row"><span class="ai-muted">Noise</span><span>${this._displayValueWithUnit(context.noise, noiseUnit)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Control Context</div>
              <div class="ai-group-row"><span class="ai-muted">CO2</span><span>${this._displayValueWithUnit(controlContext.co2, co2Unit)}</span></div>
            </div>

            <div class="ai-group-card">
              <div class="ai-group-title">Windows</div>
              ${
                windows.length === 0
                  ? `<div class="ai-group-row"><span class="ai-muted">Configured</span><span>None</span></div>`
                  : windows
                      .map((w, idx) => `
                        <div class="ai-group-row">
                          <span class="ai-muted">Window ${idx + 1}</span>
                          <span>${this._escapeHtml(w.direction || "â€”")}</span>
                        </div>
                      `).join("")
              }
            </div>
          </div>

          <div class="ai-updated">Updated: ${this._escapeHtml(updatedText)}</div>
        </div>

        <div class="ai-status-bar">
          <div class="ai-status-half" style="background:${this._stateColor(room.state)}">
            State
          </div>
          <div class="ai-status-half" style="background:${this._confidenceColor(attrs.confidence)}">
            Confidence
          </div>
        </div>
      </div>

      <div class="ai-room-shell">
        <div class="ai-room-layout">
          <div class="ai-column">
            <div class="ai-section-label">
              ${roomAssets.length === 1 ? "1 Asset in this room" : `${roomAssets.length} Assets in this room`}
            </div>

            ${
              roomAssets.length === 0
                ? `<div class="ai-empty">No assets found in this room.</div>`
                : `<div class="ai-grid">
                    ${roomAssets.map((a) => this._renderRoomAssetCard(a, roomName, room)).join("")}
                  </div>`
            }
          </div>

          <div class="ai-column">
            <div class="ai-panel-card" style="margin-bottom: 12px;">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Room Confidence Drivers</div>
                    <div class="ai-panel-subtitle">Why the room confidence is currently ${this._escapeHtml(this._titleCase(String(attrs.confidence || "Unknown").toLowerCase()))}</div>
                  </div>
                </div>

                <div class="ai-readout-card" style="margin-bottom:12px;">
                  <div class="ai-readout-grid">
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Coverage</div>
                      <div class="ai-readout-value">${this._escapeHtml(`${signalsWithData}/${configuredSignals} (${coveragePercent}%)`)}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Configured signals</div>
                      <div class="ai-readout-value">${this._escapeHtml(String(configuredSignals))}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Signals reporting</div>
                      <div class="ai-readout-value">${this._escapeHtml(String(signalsWithData))}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Signals missing</div>
                      <div class="ai-readout-value">${this._escapeHtml(String(Math.max(configuredSignals - signalsWithData, 0)))}</div>
                    </div>
                  </div>
                </div>

                <div class="ai-group-card" style="margin-bottom:12px;">
                  <div class="ai-group-title">Confidence summary</div>
                  <div class="ai-group-row"><span class="ai-muted">Reason</span><span>${this._escapeHtml(roomConfidenceSummary)}</span></div>
                </div>

                <div class="ai-group-card" style="margin-bottom:12px;">
                  <div class="ai-group-title">Signals currently missing â€” <button class="ai-link-btn" style="font-size:12px;" data-room-config="${this._escapeHtml(roomId)}">Configure sensors</button></div>
                  ${missingSignalLabels.length
                    ? missingSignalLabels.slice(0, 5).map((label) => `
                        <div class="ai-group-row"><span class="ai-muted">Missing</span><span>${this._escapeHtml(label)}</span></div>
                      `).join("")
                    : `<div class="ai-group-row"><span class="ai-muted">Missing</span><span>None â€” all configured signals are reporting</span></div>`
                  }
                </div>

                <div class="ai-group-card" style="margin-bottom:12px;">
                  <div class="ai-group-title">Signals supporting confidence</div>
                  ${reportingSignalLabels.length
                    ? reportingSignalLabels.slice(0, 5).map((label) => `
                        <div class="ai-group-row"><span class="ai-muted">Reporting</span><span>${this._escapeHtml(label)}</span></div>
                      `).join("")
                    : `<div class="ai-group-row"><span class="ai-muted">Reporting</span><span>No configured signals are reporting</span></div>`
                  }
                </div>
              </div>
            </div>

            <div class="ai-panel-card" style="margin-bottom: 12px;">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">People Health</div>
                    <div class="ai-panel-subtitle">Baseline room health and comfort assessment for occupants</div>
                  </div>
                </div>

                <div class="ai-readout-card" style="margin-bottom:12px;">
                  <div class="ai-readout-grid">
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Status since</div>
                      <div class="ai-readout-value">${this._escapeHtml(humanHealthStatusSince)}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Health state</div>
                      <div class="ai-readout-value">${this._escapeHtml(this._titleCase(humanHealthState.toLowerCase()))}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Confidence</div>
                      <div class="ai-readout-value">${this._escapeHtml(this._titleCase(humanHealthConfidence.toLowerCase()))}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Signals observed</div>
                      <div class="ai-readout-value">${this._escapeHtml(`${humanHealthObserved}/${humanHealthTotal || 0}`)}</div>
                    </div>
                  </div>
                </div>

                <div class="ai-readout-card" style="margin-bottom:12px;">
                  <div class="ai-readout-grid">
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Advisory state</div>
                      <div class="ai-readout-value">${this._escapeHtml(this._titleCase(humanHealthAdvisoryState.toLowerCase()))}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Advisory confidence</div>
                      <div class="ai-readout-value">${this._escapeHtml(this._titleCase(humanHealthAdvisoryConfidence.toLowerCase()))}</div>
                    </div>
                  </div>
                </div>

                <div class="ai-group-card" style="margin-bottom:12px;">
                  <div class="ai-group-title">Why this state</div>
                  ${humanHealthReasons.length
                    ? humanHealthReasons.slice(0, 4).map((reason) => `
                        <div class="ai-group-row"><span class="ai-muted">Reason</span><span>${this._escapeHtml(reason)}</span></div>
                      `).join("")
                    : `<div class="ai-group-row"><span class="ai-muted">Reason</span><span>Room conditions are within baseline comfort ranges</span></div>`
                  }
                </div>

                <div class="ai-group-card" style="margin-bottom:12px;">
                  <div class="ai-group-title">Advisory guidance</div>
                  ${humanHealthAdvisoryReasons.length
                    ? humanHealthAdvisoryReasons.slice(0, 4).map((reason) => `
                        <div class="ai-group-row"><span class="ai-muted">Action</span><span>${this._escapeHtml(reason)}</span></div>
                      `).join("")
                    : `<div class="ai-group-row"><span class="ai-muted">Action</span><span>No immediate occupant actions needed</span></div>`
                  }
                </div>

                <div class="ai-updated" style="margin-top:6px;">
                  State colors: Green = healthy, Amber = caution, Red = unhealthy. Confidence colors: High = strong coverage, Medium = partial coverage, Low = limited coverage.
                </div>
              </div>

              <div class="ai-status-bar">
                <div class="ai-status-half" style="background:${this._stateColor(humanHealthState)}">
                  Health State
                </div>
                <div class="ai-status-half" style="background:${this._confidenceColor(humanHealthConfidence)}">
                  Confidence
                </div>
              </div>
            </div>

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Room Measurement History</div>
                    <div class="ai-panel-subtitle">
                      All room measurements across assets, newest first
                    </div>
                  </div>
                </div>

                <div class="ai-readout-card" style="margin-bottom:12px;">
                  <div class="ai-readout-grid">
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Session count</div>
                      <div class="ai-readout-value">${roomMeasurementSummary.sessionCount}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Last session</div>
                      <div class="ai-readout-value">${this._escapeHtml(roomMeasurementSummary.lastSessionAt)}</div>
                    </div>
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Avg observations / session</div>
                      <div class="ai-readout-value">${this._escapeHtml(roomMeasurementSummary.avgObservationsText)}</div>
                    </div>
                  </div>
                </div>

                <div class="ai-timeline-filters">
                  <button type="button" class="ai-filter-chip tone-neutral ${roomHistoryFilter === "all" ? "active" : ""}" data-room-history-filter="all" data-room-history-room="${this._escapeHtml(roomId)}">All</button>
                  <button type="button" class="ai-filter-chip tone-neutral ${roomHistoryFilter === "start" ? "active" : ""}" data-room-history-filter="start" data-room-history-room="${this._escapeHtml(roomId)}">Start</button>
                  <button type="button" class="ai-filter-chip tone-green ${roomHistoryFilter === "stop" ? "active" : ""}" data-room-history-filter="stop" data-room-history-room="${this._escapeHtml(roomId)}">Stop</button>
                  <button type="button" class="ai-filter-chip tone-amber ${roomHistoryFilter === "asset" ? "active" : ""}" data-room-history-filter="asset" data-room-history-room="${this._escapeHtml(roomId)}">Asset</button>
                </div>

                ${roomHistoryFilter === "asset"
                  ? `
                    <div style="margin-bottom:12px;">
                      <select class="ai-select" data-room-history-asset data-room-history-room="${this._escapeHtml(roomId)}" style="width:100%;">
                        <option value="all" ${roomHistoryAssetFilter === "all" ? "selected" : ""}>All assets</option>
                        ${roomAssetOptions.map((item) => `
                          <option value="${this._escapeHtml(item.asset_id)}" ${roomHistoryAssetFilter === item.asset_id ? "selected" : ""}>
                            ${this._escapeHtml(item.asset_name)}
                          </option>
                        `).join("")}
                      </select>
                    </div>
                  `
                  : ""
                }

                <div class="ai-timeline">
                  ${roomMeasurementHistory.length
                    ? roomMeasurementHistory.map((item, index) => `
                      <div
                        class="ai-timeline-item ${this._escapeHtml(item.color || "neutral")}" 
                        data-history-kind="${this._escapeHtml(item.kind || "measurements")}" 
                        data-history-index="${index}"
                        title="Click to view details"
                      >
                        <div class="ai-timeline-meta">
                          ${this._escapeHtml(item.meta || "")}
                        </div>
                        <div class="ai-timeline-title">
                          ${this._escapeHtml(item.title || "Measurement event")}
                        </div>
                        ${item.copy ? `<div class="ai-timeline-copy">${this._escapeHtml(item.copy)}</div>` : ""}
                      </div>
                    `).join("")
                    : `<div class="ai-empty">No completed measurement history for this room yet.</div>`
                  }
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <button class="ai-fab" title="Add new asset">
        <span style="font-size:18px; line-height:1;">+</span>
        <span>Add Asset</span>
      </button>
    `;
  }

  _buildRoomMeasurementHistory(roomId, roomName, roomAssets) {
    const normalizedRoomId = String(roomId || "").trim();
    if (!normalizedRoomId || !Array.isArray(roomAssets) || !roomAssets.length) {
      return [];
    }

    const entries = [];

    roomAssets.forEach((assetEntity) => {
      const attrs = assetEntity?.attributes || {};
      const auditLog = Array.isArray(attrs.audit_log) ? attrs.audit_log : [];
      if (!auditLog.length) return;

      const assetId = String(attrs.asset_id || "").trim();
      const assetName = this._displayAssetName(assetEntity);

      auditLog.forEach((evt) => {
        if (!evt || typeof evt !== "object") return;

        const rawAction = String(evt.action || evt.message || "").trim();
        if (!rawAction) return;

        const action = rawAction.toLowerCase();
        if (!action.includes("measurement")) return;

        const details = evt.details && typeof evt.details === "object" ? evt.details : {};
        const detailRoomId = String(
          details.room_area_id || details.room_id || details.area_id || ""
        ).trim();

        if (detailRoomId && detailRoomId !== normalizedRoomId) {
          return;
        }

        const timestampValue = String(
          evt.timestamp || evt.occurred_at || evt.effective_at || details.completed_at || details.started_at || ""
        ).trim();

        const parsedTs = new Date(timestampValue).getTime();
        const ts = Number.isFinite(parsedTs) ? parsedTs : 0;
        const actor = String(evt.actor || evt.user || "").trim();
        const observationCount = Number(details.observation_count ?? NaN);
        const hasObservationCount = Number.isFinite(observationCount) && observationCount >= 0;

        const isStopMeasurement = action.includes("stop_measurement") || action.includes("measurement_stop");
        const title = isStopMeasurement
          ? `Stop Measurement - ${assetName}`
          : `Start Measurement - ${assetName}`;

        const copyParts = [];
        if (actor) {
          copyParts.push(`By ${actor}`);
        }
        if (hasObservationCount) {
          copyParts.push(`${Math.trunc(observationCount)} observations`);
        }

        entries.push({
          kind: "measurements",
          color: isStopMeasurement ? "green" : "neutral",
          source: "audit",
          title,
          meta: this._formatLocalDateTime(timestampValue),
          copy: copyParts.join(" â€¢ "),
          details: {
            event_type: isStopMeasurement ? "stop" : "start",
            room_id: normalizedRoomId,
            room_name: roomName,
            asset_id: assetId,
            asset_name: assetName,
            action: rawAction,
            ...(details && typeof details === "object" ? details : {}),
          },
          _ts: ts,
        });
      });
    });

    return entries.sort((a, b) => Number(b._ts || 0) - Number(a._ts || 0));
  }

  _buildRoomMeasurementSummary(historyItems, roomAssetCount = 0) {
    const history = Array.isArray(historyItems) ? historyItems : [];
    const completedSessions = history.filter((entry) => {
      const details = entry?.details && typeof entry.details === "object" ? entry.details : {};
      return String(details.event_type || "").toLowerCase() === "stop";
    });

    const sessionCount = completedSessions.length;
    const lastSessionTs = completedSessions.length
      ? Math.max(...completedSessions.map((entry) => Number(entry?._ts || 0)))
      : 0;
    const lastSessionAt = lastSessionTs > 0
      ? this._formatLocalDateTime(new Date(lastSessionTs).toISOString())
      : "â€”";

    const observationValues = completedSessions
      .map((entry) => Number(entry?.details?.observation_count ?? NaN))
      .filter((value) => Number.isFinite(value) && value >= 0);
    const avgObservations = observationValues.length
      ? (observationValues.reduce((sum, value) => sum + value, 0) / observationValues.length)
      : null;

    return {
      roomAssetCount: Number.isFinite(Number(roomAssetCount)) ? Number(roomAssetCount) : 0,
      sessionCount,
      lastSessionAt,
      avgObservationsText: avgObservations === null ? "â€”" : String(Math.round(avgObservations * 10) / 10),
    };
  }

  _initializeAssetDetailPickers() {

    if (this._view?.type !== "asset-detail" || !this._view?.assetId || !this._hass) {
      return;
    }

    const assetId = this._view.assetId;
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === assetId);
    if (!asset) return;
    console.log("INIT ASSET DETAIL PICKERS:", assetId);
    const attrs = asset.attributes || {};
    const draft = this._assetInfoDrafts[assetId] || {};
    const deviceMeta = this._getDeviceMetadataForAsset(assetId, attrs, asset.entity_id);

    // Ensure HA components receive `hass` and safe defaults BEFORE interaction
    const haComponents = this.querySelectorAll(
      "ha-area-picker, ha-labels-picker, ha-selector, ha-entity-picker"
    );

    haComponents.forEach((el) => {
      if (!el) return;
      if (this._hass && el.hass !== this._hass) {
        el.hass = this._hass;
      }

      const tag = (el.tagName || "").toLowerCase();
      if (tag === "ha-selector" && (el.selector === undefined || el.selector === null)) {
        el.selector = {};
      }
      if (tag === "ha-labels-picker" && (el.value === undefined || el.value === null)) {
        el.value = [];
      }
      if ((tag === "ha-area-picker" || tag === "ha-entity-picker") && (el.value === undefined || el.value === null)) {
        el.value = "";
      }

      if (typeof el.requestUpdate === "function") {
        try { el.requestUpdate(); } catch (e) {}
      }
    });
 
    const roomAreaId =
      deviceMeta.area_id || "";

    const labels = this._normalizeLabelList(deviceMeta.labels);

    // --------------------------------------------------
    // âœ… Restore draft values into normal input/select/textarea fields
    // --------------------------------------------------
    const watchedFields = this.querySelectorAll("[data-asset-info-watch][data-asset-field]");
    console.log("WATCHED FIELDS FOUND:", watchedFields.length);

    watchedFields.forEach((el) => {
      const fieldName = el.getAttribute("data-asset-field");
      if (!fieldName) return;

      // Use draft value if present, otherwise leave rendered value alone
      if (Object.prototype.hasOwnProperty.call(draft, fieldName)) {
        el.value = draft[fieldName] ?? "";
      }

      // Prevent double-binding on repeated renders
      if (!el.dataset.assetDraftBound) {
      const handler = (e) => {
        if (!this._assetInfoDrafts[assetId]) {
          this._assetInfoDrafts[assetId] = {};
        }

        this._assetInfoDrafts[assetId][fieldName] = e.target.value;

        // âœ… DEBUG: prove draft is capturing
        console.log("DRAFT UPDATE:", assetId, fieldName, e.target.value);

        this._refreshAssetInfoSaveState();
      };

        el.addEventListener("input", handler);
        el.addEventListener("change", handler);
        el.dataset.assetDraftBound = "true";
      }
    });

    // --------------------------------------------------
    // âœ… Room picker
    // --------------------------------------------------
    const areaPicker = this.querySelector("[data-asset-area]");
    if (areaPicker) {
      areaPicker.hass = this._hass;
      areaPicker.value = Object.prototype.hasOwnProperty.call(draft, "area_id")
        ? draft.area_id
        : roomAreaId;
      areaPicker.label = "Room";

      if (!areaPicker.dataset.assetDraftBound) {
        areaPicker.addEventListener("value-changed", (ev) => {
          if (!this._assetInfoDrafts[assetId]) {
            this._assetInfoDrafts[assetId] = {};
          }
          this._assetInfoDrafts[assetId].area_id = ev.detail?.value || "";
          this._refreshAssetInfoSaveState();
        });
        areaPicker.dataset.assetDraftBound = "true";
      }
    }

    // --------------------------------------------------
    // âœ… Labels picker
    // --------------------------------------------------
    const labelsPicker = this.querySelector("[data-asset-labels]");
    if (labelsPicker) {
      labelsPicker.hass = this._hass;
      labelsPicker.value = Object.prototype.hasOwnProperty.call(draft, "labels")
        ? draft.labels
        : labels;
      labelsPicker.label = "";

      if (!labelsPicker.dataset.assetDraftBound) {
        labelsPicker.addEventListener("value-changed", (ev) => {
          if (!this._assetInfoDrafts[assetId]) {
            this._assetInfoDrafts[assetId] = {};
          }
          this._assetInfoDrafts[assetId].labels = Array.isArray(ev.detail?.value)
            ? ev.detail.value
            : [];
          this._refreshAssetInfoSaveState();
        });
        labelsPicker.dataset.assetDraftBound = "true";
      }
    }

    // --------------------------------------------------
    // âœ… Action button state
    // --------------------------------------------------
    this._refreshAssetInfoSaveState();
  }

  _bindAssetDetailInteractionGuards() {
    const shell = this.querySelector(".ai-asset-shell");
    if (!shell) return;

    if (this._assetDetailInteractionBoundShell === shell) return;

    const PICKER_TAGS = new Set([
      "ha-labels-picker", "ha-label-picker", "ha-area-picker",
      "ha-entity-picker", "ha-selector", "ha-icon-picker",
    ]);

    const isEditableControl = (target) => {
      if (!(target instanceof HTMLElement)) return false;
      return !!target.closest(
        "input, select, textarea, ha-entity-picker, ha-area-picker, ha-labels-picker, ha-selector, .ai-form-control"
      );
    };

    // Walk up through shadow roots to find if an element is inside the shell
    const isInsideShell = (el) => {
      let node = el;
      while (node) {
        if (node === shell) return true;
        // Cross shadow boundary upward
        const root = node.getRootNode && node.getRootNode();
        if (root instanceof ShadowRoot) {
          node = root.host;
        } else {
          node = node.parentElement;
        }
      }
      return false;
    };

    // Check if any picker inside the shell currently has an open overlay
    const anyPickerOpen = () => {
      const pickers = shell.querySelectorAll(
        "ha-labels-picker, ha-label-picker, ha-area-picker, ha-entity-picker, ha-selector"
      );
      for (const picker of pickers) {
        if (picker.hasAttribute("open") || picker.hasAttribute("opened")) return true;
        // Check shadow DOM for open mwc-menu or paper-dialog
        try {
          const inner = picker.shadowRoot;
          if (inner) {
            const menu = inner.querySelector("mwc-menu, paper-listbox, ha-combo-box, vaadin-combo-box");
            if (menu && (menu.hasAttribute("open") || menu.opened === true)) return true;
          }
        } catch (_) {}
      }
      return false;
    };

    const keepActive = () => {
      this._assetDetailInteractionActive = true;
      if (this._assetDetailInteractionTimer) {
        clearTimeout(this._assetDetailInteractionTimer);
        this._assetDetailInteractionTimer = null;
      }
    };

    const releaseSoon = (delay = 1500) => {
      if (this._assetDetailInteractionTimer) {
        clearTimeout(this._assetDetailInteractionTimer);
      }
      this._assetDetailInteractionTimer = setTimeout(() => {
        this._assetDetailInteractionTimer = null;

        // If any picker is still open, extend the guard
        if (anyPickerOpen()) {
          releaseSoon(800);
          return;
        }

        const active = document.activeElement;
        // Check standard DOM containment first
        if (active instanceof HTMLElement && !!active.closest(".ai-asset-shell")) return;
        // Check shadow-root-aware containment (handles portalled overlays focused inside pickers)
        if (active instanceof HTMLElement && isInsideShell(active)) return;
        // Check if focus is inside a picker tag at document level (portalled overlay)
        if (active instanceof HTMLElement) {
          const pickerAncestor = active.closest(
            "ha-labels-picker, ha-label-picker, ha-area-picker, ha-entity-picker, ha-selector"
          );
          if (pickerAncestor && isInsideShell(pickerAncestor)) return;
        }

        this._assetDetailInteractionActive = false;
      }, delay);
    };

    // Keep active on any pointerdown inside the shell
    shell.addEventListener("pointerdown", (event) => {
      if (!isEditableControl(event.target)) return;
      keepActive();
    }, true);

    // Also catch pointerdown on portalled picker overlays at document level
    if (!this._assetDetailDocPointerBound) {
      document.addEventListener("pointerdown", (event) => {
        if (this._view?.type !== "asset-detail") return;
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;

        // Check if the clicked element is inside a picker that belongs to our shell
        const closestPicker = target.closest(
          "ha-labels-picker, ha-label-picker, ha-area-picker, ha-entity-picker, ha-selector, mwc-menu, paper-listbox, vaadin-combo-box-overlay"
        );
        if (!closestPicker) return;

        // Find if this picker (or an ancestor) is inside our shell
        const shellPickers = shell.querySelectorAll(
          "ha-labels-picker, ha-area-picker, ha-entity-picker, ha-selector"
        );
        for (const sp of shellPickers) {
          if (sp === closestPicker || sp.contains(closestPicker) || closestPicker.contains(sp)) {
            keepActive();
            return;
          }
        }

        // Also handle when the overlay is portalled: check if the tag is a known picker type
        const tag = String(closestPicker.tagName || "").toLowerCase();
        if (PICKER_TAGS.has(tag)) {
          keepActive();
        }
      }, true);
      this._assetDetailDocPointerBound = true;
    }

    shell.addEventListener("focusin", (event) => {
      if (!isEditableControl(event.target)) return;
      keepActive();
    }, true);

    shell.addEventListener("focusout", (event) => {
      if (!isEditableControl(event.target)) return;
      releaseSoon(1500);
    }, true);

    shell.addEventListener("input", (event) => {
      if (!isEditableControl(event.target)) return;
      keepActive();
    }, true);

    shell.addEventListener("change", (event) => {
      if (!isEditableControl(event.target)) return;
      keepActive();
      releaseSoon(800);
    }, true);

    this._assetDetailInteractionBoundShell = shell;
  }

  _collectAssetInfoValuesFromDom(asset) {
    const attrs = asset?.attributes || {};
    const assetId = asset?.attributes?.asset_id || this._view?.assetId || "";
    const draft = this._assetInfoDrafts[assetId] || {};

    const getField = (name) => {
      if (Object.prototype.hasOwnProperty.call(draft, name)) {
        return String(draft[name] || "").trim();
      }
      const el = this.querySelector(`[data-asset-field="${name}"]`);
      return el ? String(el.value || "").trim() : "";
    };

    const areaPicker = this.querySelector("[data-asset-area]");
    const labelsPicker = this.querySelector("[data-asset-labels]");

    const parseBool = (value, fallback = false) => {
      if (typeof value === "boolean") return value;
      if (value === null || value === undefined || value === "") return !!fallback;
      const normalized = String(value).trim().toLowerCase();
      if (normalized === "true" || normalized === "1" || normalized === "yes") return true;
      if (normalized === "false" || normalized === "0" || normalized === "no") return false;
      return !!fallback;
    };

    const basePlacement = attrs.placement && typeof attrs.placement === "object" ? attrs.placement : {};
    const baseEnclosure = attrs.enclosure && typeof attrs.enclosure === "object" ? attrs.enclosure : {};

    return {
      name: getField("name"),
      asset_type: getField("asset_type"),
      area_id: Object.prototype.hasOwnProperty.call(draft, "area_id")
        ? draft.area_id || ""
        : (areaPicker?.value || ""),
      location_detail: getField("location_detail"),
      labels: Object.prototype.hasOwnProperty.call(draft, "labels")
        ? (Array.isArray(draft.labels) ? draft.labels : [])
        : (Array.isArray(labelsPicker?.value) ? labelsPicker.value : []),
      description_guest: getField("description_guest"),
      description_owner: getField("description_owner"),
      description_insurance: getField("description_insurance"),
      manufacturer_detail: getField("manufacturer_detail"),
      warranty: getField("warranty"),
      near_window: Object.prototype.hasOwnProperty.call(draft, "near_window")
        ? parseBool(draft.near_window, basePlacement.near_window)
        : parseBool(getField("near_window"), basePlacement.near_window),
      facing_direction: getField("facing_direction"),
      exposure_zone: getField("exposure_zone"),
      placement_description: getField("placement_description"),
      enclosure_type: getField("enclosure_type"),
      enclosure_sealed: Object.prototype.hasOwnProperty.call(draft, "enclosure_sealed")
        ? parseBool(draft.enclosure_sealed, baseEnclosure.sealed)
        : parseBool(getField("enclosure_sealed"), baseEnclosure.sealed),
      purchase_date: getField("purchase_date"),
      purchase_price: getField("purchase_price"),
      purchase_source: getField("purchase_source"),
      purchase_notes: getField("purchase_notes"),
      valuation_estimated_value: getField("valuation_estimated_value"),
      valuation_date: getField("valuation_date"),
      valuation_method: getField("valuation_method"),
      valuation_notes: getField("valuation_notes"),
      linked_device_id: getField("linked_device_id"),
      tracker_entity_id: getField("tracker_entity_id"),
    };
  }

  _assetHeaderDraftKeys() {
    return ["area_id", "labels"];
  }

  _assetInfoDraftKeys() {
    return [
      "name",
      "asset_type",
      "location_detail",
      "description_guest",
      "description_owner",
      "description_insurance",
      "manufacturer_detail",
      "warranty",
      "near_window",
      "facing_direction",
      "exposure_zone",
      "placement_description",
      "enclosure_type",
      "enclosure_sealed",
      "linked_device_id",
      "tracker_entity_id",
    ];
  }

  _assetFinancialDraftKeys() {
    return [
      "purchase_date",
      "purchase_price",
      "purchase_source",
      "purchase_notes",
      "valuation_estimated_value",
      "valuation_date",
      "valuation_method",
      "valuation_notes",
    ];
  }

  _dropAssetDraftKeys(assetId, keys = []) {
    if (!assetId || !this._assetInfoDrafts?.[assetId]) return;
    keys.forEach((key) => {
      delete this._assetInfoDrafts[assetId][key];
    });
    if (!Object.keys(this._assetInfoDrafts[assetId]).length) {
      delete this._assetInfoDrafts[assetId];
    }
  }

  _discardAssetDetailDrafts(assetId) {
    if (!assetId) return;
    delete this._assetInfoDrafts[assetId];
    this._clearAssetEnvironmentDraft(assetId);
  }

  _isAssetHeaderDirty(asset) {
    const values = this._collectAssetInfoValuesFromDom(asset) || {};
    const base = asset?.attributes || {};
    const assetId = base.asset_id || this._view?.assetId || "";
    const deviceMeta = this._getDeviceMetadataForAsset(assetId, base, asset?.entity_id);

    const valuesLabels = this._normalizeLabelList(values.labels);
    const baseLabels = this._normalizeLabelList(deviceMeta.labels);

    return (
      (values.area_id || "") !== (deviceMeta.area_id || "") ||
      JSON.stringify(valuesLabels) !== JSON.stringify(baseLabels)
    );
  }

  _isAssetInfoDirty(asset) {
    const values = this._collectAssetInfoValuesFromDom(asset) || {};
    const base = asset?.attributes || {};
    const placement = base.placement && typeof base.placement === "object" ? base.placement : {};
    const enclosure = base.enclosure && typeof base.enclosure === "object" ? base.enclosure : {};
    const descriptions = base.descriptions && typeof base.descriptions === "object" ? base.descriptions : {};
    const links = base.links && typeof base.links === "object" ? base.links : {};
    const trackers = Array.isArray(base.trackers) ? base.trackers : [];
    const currentTrackerEntityId = String(trackers[0]?.entity_id || "");

    return (
      (values.name || "") !== (base.name || "") ||
      (values.asset_type || "") !== (base.asset_type || "") ||
      (values.location_detail || "") !== (base.location_detail || "") ||
      (values.description_guest || "") !== (base.description_guest || descriptions.guest || "") ||
      (values.description_owner || "") !== (base.description_owner || descriptions.owner || "") ||
      (values.description_insurance || "") !== (base.description_insurance || descriptions.insurance || "") ||
      this._normalizeComparableText(values.manufacturer_detail) !== this._normalizeComparableText(base.manufacturer_detail) ||
      this._normalizeComparableText(values.warranty) !== this._normalizeComparableText(base.warranty) ||
      !!values.near_window !== !!placement.near_window ||
      (values.facing_direction || "") !== (placement.facing_direction || "") ||
      (values.exposure_zone || "") !== (placement.exposure_zone || "") ||
      (values.placement_description || "") !== (placement.description || "") ||
      (values.enclosure_type || "") !== (enclosure.type || "") ||
      !!values.enclosure_sealed !== !!enclosure.sealed ||
      (values.linked_device_id || "") !== String(links.device_id || "") ||
      (values.tracker_entity_id || "") !== currentTrackerEntityId
    );
  }

  _isAssetFinancialDirty(asset) {
    const values = this._collectAssetInfoValuesFromDom(asset) || {};
    const base = asset?.attributes || {};
    const purchase = base.purchase && typeof base.purchase === "object" ? base.purchase : {};
    const valuation = base.valuation && typeof base.valuation === "object" ? base.valuation : {};

    const basePurchaseDate = purchase.purchase_date || purchase.date || "";
    const basePurchasePrice = purchase.purchase_price || purchase.price || "";
    const basePurchaseSource = purchase.source || "";
    const basePurchaseNotes = purchase.notes || "";

    const baseValuationEstimated = valuation.estimated_value || valuation.value || "";
    const baseValuationDate = valuation.valuation_date || valuation.date || "";
    const baseValuationMethod = valuation.method || "";
    const baseValuationNotes = valuation.notes || "";

    return (
      (values.purchase_date || "") !== String(basePurchaseDate || "") ||
      (values.purchase_price || "") !== String(basePurchasePrice || "") ||
      (values.purchase_source || "") !== String(basePurchaseSource || "") ||
      (values.purchase_notes || "") !== String(basePurchaseNotes || "") ||
      (values.valuation_estimated_value || "") !== String(baseValuationEstimated || "") ||
      (values.valuation_date || "") !== String(baseValuationDate || "") ||
      (values.valuation_method || "") !== String(baseValuationMethod || "") ||
      (values.valuation_notes || "") !== String(baseValuationNotes || "")
    );
  }

  _hasUnsavedAssetDetailChanges(assetId = null) {
    const effectiveAssetId = assetId || (this._view?.type === "asset-detail" ? this._view.assetId : null);
    if (!effectiveAssetId) return false;

    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === effectiveAssetId);
    if (!asset) return false;

    return (
      this._isAssetHeaderDirty(asset) ||
      this._isAssetInfoDirty(asset) ||
      this._isAssetFinancialDirty(asset) ||
      this._isAssetEnvironmentDirty(effectiveAssetId, asset.attributes || {})
    );
  }

  _handleBeforeUnload(event) {
    if (!this._hasUnsavedAssetDetailChanges()) return;
    event.preventDefault();
    event.returnValue = "";
  }

  async _confirmLeaveWithUnsavedChanges(assetId) {
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === assetId);
    if (!asset) return "discard";
    if (!this._hasUnsavedAssetDetailChanges(assetId)) return "discard";

    return this._showUnsavedChangesDialog();
  }

  async _attemptNavigate(nextView) {
    const fromAssetId = this._view?.type === "asset-detail" ? this._view.assetId : null;

    if (fromAssetId && this._hasUnsavedAssetDetailChanges(fromAssetId)) {
      const choice = await this._confirmLeaveWithUnsavedChanges(fromAssetId);

      if (choice === "stay") {
        return;
      }

      if (choice === "save") {
        const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === fromAssetId);
        if (!asset) return;

        try {
          if (this._isAssetHeaderDirty(asset)) {
            const ok = await this._saveAssetHeaderBlock(fromAssetId);
            if (!ok) return;
          }
          if (this._isAssetInfoDirty(asset)) {
            const ok = await this._saveAssetInfoBlock(fromAssetId);
            if (!ok) return;
          }
          if (this._isAssetFinancialDirty(asset)) {
            const ok = await this._saveAssetFinancialBlock(fromAssetId);
            if (!ok) return;
          }
          if (this._isAssetEnvironmentDirty(fromAssetId, asset.attributes || {})) {
            const ok = await this._saveAssetEnvironmentLimits(fromAssetId);
            if (!ok) return;
          }
        } catch (err) {
          console.error("Failed while saving unsaved changes before navigation", err);
          return;
        }
      }

      if (choice === "discard") {
        this._discardAssetDetailDrafts(fromAssetId);
      }
    }

    this._view = nextView;
    this._render();
  }

  _refreshAssetInfoSaveState() {
    if (this._view?.type !== "asset-detail" || !this._view?.assetId) return;
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === this._view.assetId);
    if (!asset) return;

    const headerDirty = this._isAssetHeaderDirty(asset);
    const infoDirty = this._isAssetInfoDirty(asset);
    const financialDirty = this._isAssetFinancialDirty(asset);

    const headerActions = this.querySelector("[data-asset-header-actions]");
    if (headerActions) {
      headerActions.style.display = headerDirty ? "flex" : "none";
    }

    const infoActions = this.querySelector("[data-asset-info-actions]");
    if (infoActions) {
      infoActions.style.display = infoDirty ? "flex" : "none";
    }

    const financialActions = this.querySelector("[data-asset-financial-actions]");
    if (financialActions) {
      financialActions.style.display = financialDirty ? "flex" : "none";
    }

    const saveButton = this.querySelector("[data-asset-info-save]");
    if (saveButton) {
      saveButton.disabled = !infoDirty;
    }

    const headerSaveButton = this.querySelector("[data-asset-header-save]");
    if (headerSaveButton) {
      headerSaveButton.disabled = !headerDirty;
    }

    const financialSaveButton = this.querySelector("[data-asset-financial-save]");
    if (financialSaveButton) {
      financialSaveButton.disabled = !financialDirty;
    }

    const environmentSaveButton = this.querySelector("[data-asset-environment-save]");
    const environmentActions = this.querySelector("[data-asset-environment-actions]");
    if (environmentSaveButton && environmentActions) {
      const attrs = asset.attributes || {};
      const hasErrors = this._assetEnvironmentHasValidationErrors(this._view.assetId, attrs);
      const envDirty = this._isAssetEnvironmentDirty(this._view.assetId, attrs);
      environmentSaveButton.disabled = hasErrors || !envDirty;
      environmentActions.style.display = envDirty ? "flex" : "none";
    }
  }

  async _saveAssetHeaderBlock(assetId) {
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === assetId);
    if (!asset) return false;

    const values = this._collectAssetInfoValuesFromDom(asset);
    const payload = {
      asset_id: assetId,
      area_id: values.area_id || null,
      labels: this._normalizeLabelList(values.labels || []),
    };

    try {
      await this._callService("asset_intelligence", "update_asset", payload);
      this._dropAssetDraftKeys(assetId, this._assetHeaderDraftKeys());
      await this._load();
      return true;
    } catch (err) {
      console.error("Failed to save header changes", err);
      alert("Failed to update room/labels");
      return false;
    }
  }

  async _saveAssetInfoBlock(assetId) {
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === assetId);
    if (!asset) return false;

    const values = this._collectAssetInfoValuesFromDom(asset);
    const existingLinks = asset.attributes?.links && typeof asset.attributes.links === "object"
      ? asset.attributes.links
      : {};
    const existingTrackers = Array.isArray(asset.attributes?.trackers)
      ? asset.attributes.trackers
      : [];
    const currentLinkedDeviceId = String(existingLinks.device_id || "");
    const nextLinkedDeviceId = String(values.linked_device_id || "");
    const currentTrackerEntityId = String(existingTrackers[0]?.entity_id || "");
    const nextTrackerEntityId = String(values.tracker_entity_id || "");

    const existingPlacement = asset.attributes?.placement && typeof asset.attributes.placement === "object"
      ? asset.attributes.placement
      : {};
    const existingEnclosure = asset.attributes?.enclosure && typeof asset.attributes.enclosure === "object"
      ? asset.attributes.enclosure
      : {};

    const payload = {
      asset_id: assetId,
      name: values.name,
      asset_type: values.asset_type,
      location_detail: values.location_detail || null,
      descriptions: {
        guest: values.description_guest || "",
        owner: values.description_owner || "",
        insurance: values.description_insurance || "",
      },
      manufacturer_detail: values.manufacturer_detail || "",
      warranty: values.warranty || "",
      placement: {
        ...existingPlacement,
        near_window: !!values.near_window,
        facing_direction: values.facing_direction || "",
        exposure_zone: values.exposure_zone || "",
        description: values.placement_description || "",
        location_detail: values.location_detail || "",
      },
      enclosure: {
        ...existingEnclosure,
        type: values.enclosure_type || "",
        sealed: !!values.enclosure_sealed,
      },
    };

    try {
      await this._callService("asset_intelligence", "update_asset", payload);

      if (nextLinkedDeviceId !== currentLinkedDeviceId) {
        if (currentLinkedDeviceId) {
          await this._callService("asset_intelligence", "unlink_from_device", {
            asset_id: assetId,
            remove_all: true,
          });
        }
        if (nextLinkedDeviceId) {
          await this._callService("asset_intelligence", "link_to_device", {
            asset_id: assetId,
            device_id: nextLinkedDeviceId,
          });
        }
      }

      if (nextTrackerEntityId !== currentTrackerEntityId) {
        if (currentTrackerEntityId) {
          await this._callService("asset_intelligence", "remove_tracker", {
            asset_id: assetId,
            entity_id: currentTrackerEntityId,
          });
        }
        if (nextTrackerEntityId) {
          await this._callService("asset_intelligence", "add_tracker", {
            asset_id: assetId,
            entity_id: nextTrackerEntityId,
          });
        }
      }

      this._dropAssetDraftKeys(assetId, this._assetInfoDraftKeys());
      await this._load();
      return true;
    } catch (err) {
      console.error("Failed to save asset info block", err);
      alert("Failed to save asset information");
      return false;
    }
  }

  async _saveAssetFinancialBlock(assetId) {
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === assetId);
    if (!asset) return false;

    const values = this._collectAssetInfoValuesFromDom(asset);
    const basePurchase = asset.attributes?.purchase && typeof asset.attributes.purchase === "object"
      ? asset.attributes.purchase
      : {};
    const baseValuation = asset.attributes?.valuation && typeof asset.attributes.valuation === "object"
      ? asset.attributes.valuation
      : {};

    const payload = {
      asset_id: assetId,
      purchase: {
        ...basePurchase,
        purchase_date: values.purchase_date || null,
        purchase_price: values.purchase_price === "" ? null : Number(values.purchase_price),
        source: values.purchase_source || "",
        notes: values.purchase_notes || "",
      },
      valuation: {
        ...baseValuation,
        estimated_value: values.valuation_estimated_value === "" ? null : Number(values.valuation_estimated_value),
        valuation_date: values.valuation_date || null,
        method: values.valuation_method || "",
        notes: values.valuation_notes || "",
      },
    };

    try {
      await this._callService("asset_intelligence", "update_asset", payload);
      this._dropAssetDraftKeys(assetId, this._assetFinancialDraftKeys());
      await this._load();
      return true;
    } catch (err) {
      console.error("Failed to save financial block", err);
      alert("Failed to save financial information");
      return false;
    }
  }

  _renderWindowsSection(room) {
    const roomId = room?.attributes?.area_id;
    const windows = this._getDraftWindows(roomId, room);

    return `
      <div class="ai-config-section">

        <div class="ai-section-title">Windows</div>

        ${
          windows.length === 0
            ? `<div class="ai-empty">No windows configured</div>`
            : windows.map((w, i) => {
                const isEditing = this._editingWindowIndex === i;

                return `
                  <div class="ai-config-row">

                    <!-- Column 1 -->
                    <div>
                      Window ${i + 1}
                    </div>

                    <!-- Column 2 -->
                    <div style="display:flex; flex-direction:column; gap:8px; align-items:stretch; min-width:0; overflow:visible;">

                      ${
                        isEditing
                          ? `
                            <select class="ai-config-dropdown" data-window-direction="${i}">
                              <option value="">Select directionâ€¦</option>
                              ${WINDOW_DIRECTIONS.map(dir => `
                                <option value="${dir}" ${dir === w.direction ? "selected" : ""}>
                                  ${this._escapeHtml(this._titleCase(dir))}
                                </option>
                              `).join("")}
                            </select>

                            <select class="ai-config-dropdown" data-window-exposure="${i}">
                              <option value="">Select exposureâ€¦</option>
                              ${WINDOW_EXPOSURES.map(exp => `
                                <option value="${exp}" ${exp === w.exposure ? "selected" : ""}>
                                  ${this._escapeHtml(this._titleCase(exp))}
                                </option>
                              `).join("")}
                            </select>
                          `
                          : `
                            <span class="ai-tag">
                              ${this._escapeHtml(this._titleCase(w.direction || "â€”"))}
                            </span>
                            <span class="ai-tag">
                              ${this._escapeHtml(this._titleCase(w.exposure || "â€”"))}
                            </span>
                          `
                      }

                    </div>

                    <!-- Column 3 -->
                    <div></div>

                    <!-- Column 4 -->
                    <div style="display:flex; gap:8px;">
                      ${
                        isEditing
                          ? `
                            <button class="ai-link-btn" data-save-window="${i}">Save</button>
                            <button class="ai-link-btn" data-cancel-window>Cancel</button>
                          `
                          : `
                            <button class="ai-link-btn" data-edit-window="${i}">Update</button>
                            <button class="ai-link-btn ai-danger" data-remove-window="${i}">Remove</button>
                          `
                      }
                    </div>

                  </div>
                `;
              }).join("")}

        <div style="margin-top:10px;">
          <button class="ai-link-btn" data-add-window>+ Add Window</button>
        </div>

      </div>
    `;
  }

  /* ===========================
     ROOM/ASSET CARDS
  =========================== */

  _renderRoomCard(roomEntity, area, assetEntities) {
    const attrs = roomEntity.attributes || {};
    const areaId = attrs.area_id || "unknown";
    const roomName = this._displayRoomName(area, roomEntity);

    const state = String(roomEntity.state || "unknown").toUpperCase();
    const confidence = String(attrs.confidence || "unknown").toUpperCase();

    const stateColor = this._stateColor(state);
    const confidenceColor = this._confidenceColor(confidence);

    const sourceStatus = attrs.source_status || {};
    const details = sourceStatus.details || {};

    const configured = attrs.configured === true;
    const configuredText = configured ? "Yes" : "No";

    const assetCount = this._countAssetsForRoom(assetEntities, areaId);

    const atRiskCount = assetEntities.filter((entity) => {
      const attrs = entity.attributes || {};
      const roomAreaId = this._resolveAssetRoomAreaId(attrs, entity.entity_id);

      if (roomAreaId !== areaId) return false;

      const risk = String(
        attrs.environment_risk_state ||
        attrs.risk_state ||
        ""
      ).toUpperCase();

      return risk === "RED";
    }).length;

    const totals = {
      climate: 3,
      light: 2,
      air_quality: 4,
      particulates: 2,
      biological: 1,
      safety: 1,
      structural: 2,
      context: 1,
      control_context: 1,
    };

    const configuredCounts = {
      climate: this._countConfigured(details, "climate."),
      light: this._countConfigured(details, "light."),
      air_quality: this._countConfigured(details, "air_quality."),
      particulates: this._countConfigured(details, "particulates."),
      biological: this._countConfigured(details, "biological."),
      safety: this._countConfigured(details, "safety."),
      structural: this._countConfigured(details, "structural."),
      context: this._countConfigured(details, "context."),
      control_context: this._countConfigured(details, "control_context."),
    };

    const windows = Array.isArray(attrs.windows) ? attrs.windows : [];
    const windowsConfigured = windows.length;
    const windowsTotal = windows.length;

    const areaImageUrl = area?.picture || area?.image || null;
    const imageUrl = this._resolvePrimaryDocumentImage(attrs) || areaImageUrl || attrs.image || attrs.primary_image || attrs.image_url || null;
    const icon = area?.icon || "mdi:home";
    const updatedText = this._formatLocalDateTime(attrs.last_updated);

    return `
      <div class="ai-card ai-room-click" data-room="${this._escapeHtml(areaId)}">
        <div class="ai-card-top ${imageUrl ? "has-image" : ""}" ${
          imageUrl ? this._buildImageContainerAttrs(imageUrl) : ""
        }>
        ${
          imageUrl
            ? ""
            : `
              <div class="ai-icon-wrap">
                <ha-icon icon="${this._escapeHtml(icon)}"></ha-icon>
              </div>
            `
        }

        </div>

        <div class="ai-card-body">
          <div class="ai-room-name">${this._escapeHtml(roomName)}</div>

          <div class="ai-room-summary">
            <span>
              Assets: <strong>${assetCount}</strong>
              ${atRiskCount > 0 ? `
                <span class="ai-separator">â€¢</span>
                <span class="ai-risk-badge">${atRiskCount} at risk</span>
              ` : ""}

            </span>
            <span>Configured: <strong>${configuredText}</strong></span>
          </div>


          <div class="ai-divider"></div>

          <div class="ai-room-metrics-grid">
            <div class="ai-room-metric-item" title="Temperature, humidity, dew point">
              <div class="ai-data-label">Climate</div>
              <div class="ai-data-value">${configuredCounts.climate}/${totals.climate}</div>
            </div>
            <div class="ai-room-metric-item" title="Lux, UV">
              <div class="ai-data-label">Light</div>
              <div class="ai-data-value">${configuredCounts.light}/${totals.light}</div>
            </div>
            <div class="ai-room-metric-item" title="VOC, formaldehyde, ozone, NOâ‚‚">
              <div class="ai-data-label">Air Quality</div>
              <div class="ai-data-value">${configuredCounts.air_quality}/${totals.air_quality}</div>
            </div>
            <div class="ai-room-metric-item" title="PM2.5, PM10">
              <div class="ai-data-label">Particulates</div>
              <div class="ai-data-value">${configuredCounts.particulates}/${totals.particulates}</div>
            </div>
            <div class="ai-room-metric-item" title="Mold index">
              <div class="ai-data-label">Biological</div>
              <div class="ai-data-value">${configuredCounts.biological}/${totals.biological}</div>
            </div>
            <div class="ai-room-metric-item" title="Leak">
              <div class="ai-data-label">Safety</div>
              <div class="ai-data-value">${configuredCounts.safety}/${totals.safety}</div>
            </div>
            <div class="ai-room-metric-item" title="Pressure, vibration">
              <div class="ai-data-label">Structural</div>
              <div class="ai-data-value">${configuredCounts.structural}/${totals.structural}</div>
            </div>
            <div class="ai-room-metric-item" title="Noise">
              <div class="ai-data-label">Context</div>
              <div class="ai-data-value">${configuredCounts.context}/${totals.context}</div>
            </div>
            <div class="ai-room-metric-item" title="COâ‚‚">
              <div class="ai-data-label">Control Context</div>
              <div class="ai-data-value">${configuredCounts.control_context}/${totals.control_context}</div>
            </div>
            <div class="ai-room-metric-item" title="Configured windows for this room">
              <div class="ai-data-label">Windows</div>
              <div class="ai-data-value">${windowsConfigured}/${windowsTotal}</div>
            </div>
          </div>

          <div class="ai-updated">Updated: ${this._escapeHtml(updatedText)}</div>
          <div style="margin-top: 8px;">
            <button class="ai-link-btn" data-room-config="${this._escapeHtml(areaId)}">
              ${configured ? "Edit" : "Initialize"}
            </button>
          </div>
        </div>

        <div class="ai-status-bar">
          <div class="ai-status-half" style="background:${stateColor}">
            State
          </div>
          <div class="ai-status-half" style="background:${confidenceColor}">
            Confidence
          </div>
        </div>
      </div>
    `;
  }

  _renderAssetCard(assetEntity, areaMap) {
    const attrs = assetEntity.attributes || {};
    const assetId = attrs.asset_id || "";
    const deviceMeta = this._getDeviceMetadataForAsset(assetId, attrs, assetEntity.entity_id);
    const assetName = this._displayAssetName(assetEntity);
    const roomAreaId = this._resolveAssetRoomAreaId(attrs, assetEntity.entity_id);
    const roomArea = roomAreaId ? areaMap[roomAreaId] : null;
    const roomName = roomArea?.name || (roomAreaId ? this._titleCase(String(roomAreaId).replaceAll("_", " ")) : "No Room");
    const assetType = attrs.asset_type || attrs.type || "â€”";
    const documentCount = attrs.document_count ?? 0;
    const updatedText = this._formatLocalDateTime(
      attrs.room_last_updated || attrs.updated_at || assetEntity.last_updated
    );
    const riskState = String(
      attrs.environment_risk_state ||
      attrs.risk_state ||
      "UNKNOWN"
    ).toUpperCase();
    const confidence = String(
      attrs.room_confidence ||
      attrs.confidence ||
      "UNKNOWN"
    ).toUpperCase();
    const stateColor = this._stateColor(riskState);
    const confidenceColor = this._confidenceColor(confidence);
    const icon = this._getAssetIcon(attrs.asset_type, deviceMeta.labels);
    const imageUrl = this._resolvePrimaryDocumentImage(attrs) || attrs.image || attrs.primary_image || attrs.image_url || null;

    return `
      <div class="ai-card ai-asset-click">
        <div class="ai-card-top ${imageUrl ? "has-image" : ""}" ${
          imageUrl ? this._buildImageContainerAttrs(imageUrl) : ""
        }>
          ${
            imageUrl
              ? ""
              : `<ha-icon icon="${this._escapeHtml(icon)}" style="width:40px;height:40px; color: var(--secondary-text-color); opacity: 0.6; position: relative; z-index: 1;"></ha-icon>`
          }
        </div>
        <div class="ai-card-body">
          <div class="ai-asset-name">${this._escapeHtml(assetName)}</div>
          <div class="ai-data-grid">
            <div class="ai-data-label ai-highlight">Room</div>
            <div class="ai-data-value ai-highlight">${this._escapeHtml(roomName)}</div>

            <div class="ai-data-label">Asset Type</div>
            <div class="ai-data-value">${this._escapeHtml(assetType)}</div>

            <div class="ai-data-label">Documents</div>
            <div class="ai-data-value">${documentCount}</div>
          </div>
          <div class="ai-divider"></div>
          <div class="ai-updated">Updated: ${this._escapeHtml(updatedText)}</div>
        </div>
        <div class="ai-status-bar">
          <div class="ai-status-half" style="background:${stateColor}">
            State
          </div>
          <div class="ai-status-half" style="background:${confidenceColor}">
            Confidence
          </div>
        </div>
      </div>
    `;
  }

  _renderRoomAssetCard(assetEntity, roomName, roomEntity) {
    const attrs = assetEntity.attributes || {};
    const assetId = attrs.asset_id || "";
    const deviceMeta = this._getDeviceMetadataForAsset(assetId, attrs, assetEntity.entity_id);
    const assetName = this._displayAssetName(assetEntity);
    const imageUrl = this._resolvePrimaryDocumentImage(attrs) || attrs.image || attrs.primary_image || attrs.image_url || null;
    const icon = this._getAssetIcon(attrs.asset_type, deviceMeta.labels);


    const assetTypeRaw = attrs.asset_type || attrs.type || "â€”";
    const assetType = assetTypeRaw && assetTypeRaw !== "â€”"
      ? this._titleCase(String(assetTypeRaw).replaceAll("_", " "))
      : "â€”";

    const labelSummary = this._summarizeLabels(deviceMeta.labels, assetTypeRaw);

    const locationDetail =
      attrs.location_detail || "â€”";

    const insuranceDescription =
      attrs.descriptions?.insurance ||
      attrs.insurance_description ||
      "â€”";

    const atRiskValue = String(
      attrs.environment_risk_state ||
      attrs.risk_state ||
      attrs.at_risk_state ||
      "UNKNOWN"
    ).toUpperCase();

    const rawReasons =
      // âœ… 1. New structured event reasons (BEST SOURCE)
      Array.isArray(attrs.last_environment_event?.reasons)
        ? attrs.last_environment_event.reasons

      // âœ… 2. Direct array field
      : Array.isArray(attrs.environment_reasons)
        ? attrs.environment_reasons

      // âœ… 3. String field (convert to array)
      : typeof attrs.environment_reasons === "string" && attrs.environment_reasons.trim()
        ? [attrs.environment_reasons.trim()]

      // âœ… 4. Generic fallback fields
      : Array.isArray(attrs.reasons)
        ? attrs.reasons

      : typeof attrs.reasons === "string" && attrs.reasons.trim()
        ? [attrs.reasons.trim()]

      : Array.isArray(attrs.risk_reasons)
        ? attrs.risk_reasons

      : typeof attrs.risk_reasons === "string" && attrs.risk_reasons.trim()
        ? [attrs.risk_reasons.trim()]

      : [];


    let riskReason =
      rawReasons.length > 0
        ? rawReasons[0]
        : (atRiskValue === "UNCONFIGURED"
            ? "No environmental limits configured"
            : "No active environmental risk");

    let riskReasonTooltip =
      rawReasons.length > 0
        ? rawReasons.join(" â€¢ ")
        : (atRiskValue === "UNCONFIGURED"
            ? "No environmental limits configured"
            : "No active environmental risk");


    const environmentStateSinceRaw =
      attrs.environment_state_since ||
      attrs.environment_state_changed_at ||
      attrs.risk_state_since ||
      attrs.state_since ||
      null;

    const environmentStateSinceText = environmentStateSinceRaw
      ? this._formatLocalDateTime(environmentStateSinceRaw)
      : "â€”";

    const atRiskColor = this._stateColor(atRiskValue);

    const statusBarLabel =
      atRiskValue === "RED"
        ? "Environmental Risk"
        : atRiskValue === "PARTIAL"
          ? "Partial Exposure"
          : atRiskValue === "UNCONFIGURED"
            ? "Unconfigured"
          : "Stable";

    const riskReasonClass =
      atRiskValue === "RED"
        ? "ai-risk-reason-text ai-value-high"
        : atRiskValue === "PARTIAL"
          ? "ai-risk-reason-text ai-value-moderate"
          : "ai-risk-reason-text";

    return `
      <div class="ai-card ai-room-asset-card ai-asset-click" data-asset="${this._escapeHtml(attrs.asset_id)}">
        <div class="ai-card-top ${imageUrl ? "has-image" : ""}" ${
          imageUrl ? this._buildImageContainerAttrs(imageUrl) : ""
        }>
          ${
            imageUrl
              ? ""
              : `
                <div class="ai-icon-wrap" style="opacity:1;">
                  <ha-icon icon="${this._escapeHtml(icon)}"></ha-icon>
                </div>
              `
          }
        </div>

        <div class="ai-card-body">
          <div class="ai-asset-name">${this._escapeHtml(assetName)}</div>
          <div class="ai-asset-summary">${this._escapeHtml(labelSummary)}</div>

          <div class="ai-asset-detail-grid">
            <div class="ai-asset-detail-label">Asset Type</div>
            <div class="ai-asset-detail-value">
              <span class="ai-truncate" title="${this._escapeHtml(assetType)}">${this._escapeHtml(assetType)}</span>
            </div>

            <div class="ai-asset-detail-label">Location</div>
            <div class="ai-asset-detail-value">
              <span class="ai-truncate" title="${this._escapeHtml(locationDetail)}">${this._escapeHtml(locationDetail)}</span>
            </div>

            <div class="ai-asset-detail-label">Insurance</div>
            <div class="ai-asset-detail-value">
              <span class="ai-truncate" title="${this._escapeHtml(insuranceDescription)}">${this._escapeHtml(insuranceDescription)}</span>
            </div>

            <div class="ai-asset-detail-label">Risk</div>
            <div class="ai-asset-detail-value">
              <span class="ai-truncate ${riskReasonClass}" title="${this._escapeHtml(riskReasonTooltip)}">${this._escapeHtml(riskReason)}</span>
            </div>

            <div class="ai-asset-detail-label">State Since</div>
            <div class="ai-asset-detail-value">
              <span class="ai-truncate" title="${this._escapeHtml(environmentStateSinceText)}">${this._escapeHtml(environmentStateSinceText)}</span>
            </div>
          </div>
        </div>

        <div class="ai-status-bar">
          <div
            class="ai-status-half"
            style="background:${atRiskColor}; flex: 1 1 100%;"
            title="${this._escapeHtml(riskReasonTooltip)}"
          >
            ${this._escapeHtml(statusBarLabel)}
          </div>
        </div>
      </div>
    `;
  }

  _renderRoomConfig(roomId, roomEntities, areaMap) {
    const room = roomEntities.find((r) => r.attributes?.area_id === roomId);
    const area = areaMap[roomId];

    const roomName = room
      ? this._displayRoomName(area, room)
      : "Unknown Room";

    return `
      ${this._renderBreadcrumb([
        { label: "Asset Intelligence", nav: "home" },
        { label: roomName, roomId },
        { label: "Room Configuration" }
      ])}

      <div class="ai-title">Room Configuration</div>
      <div class="ai-subtitle">Configure sensors and environment mapping for ${this._escapeHtml(roomName)}</div>

      ${Object.entries(this._getCategoryConfig()).map(([categoryName, metrics]) => {
        if (categoryName === "windows") {
          return this._renderWindowsSection(room);
        }

        return `
          <div class="ai-config-section">
            <div class="ai-section-title">${this._titleCase(categoryName).replaceAll("_", " ")}</div>

            ${Object.entries(metrics).map(([metricKey, metricDef]) => {
              const fieldPath = `${categoryName}.${metricKey}`;

              const draftValue = this._draftMetrics[fieldPath]?.entity;
              const configured = draftValue ?? this._getConfiguredSensorForMetric(room, fieldPath);
              const sensors = this._getRoomSensorsForMetric(
                roomId,
                metricDef,
                this._showAllSensorsByMetric?.[fieldPath]
              );
              const reading = this._getFormattedRoomMetricValue(room, fieldPath);
              const isEditing = this._editingMetric === fieldPath;

              return `
                <div class="ai-config-row">

                  <div style="flex:1;">
                    ${this._titleCase(metricKey.replaceAll("_", " "))}
                  </div>

                  <div style="flex:2;">
                    ${
                      isEditing
                        ? `
                            <div class="ai-form-control" style="display:flex; flex-direction:column; gap:8px;">
                              <ha-entity-picker
                                class="ai-config-dropdown"
                                data-metric="${fieldPath}"
                                value="${this._escapeHtml(configured || "")}"
                              ></ha-entity-picker>

                              <label
                                class="ai-config-toggle"
                              >
                                <input
                                  type="checkbox"
                                  data-show-all-sensors="${fieldPath}"
                                  ${this._showAllSensorsByMetric?.[fieldPath] ? "checked" : ""}
                                />
                                Show all sensors of this type
                              </label>
                            </div>

                        `
                        : configured
                          ? `
                            <div class="ai-config-readonly">
                              ${this._escapeHtml(
                                this._hass?.states?.[configured]?.attributes?.friendly_name || configured
                              )}
                              <span class="ai-muted" style="margin-left:8px;">
                                (${this._escapeHtml(configured)})
                              </span>
                            </div>
                          `
                          : `<span class="ai-empty">No sensor assigned</span>`
                    }
                  </div>

                  <div style="width:120px;">
                    ${
                      configured && !isEditing
                        ? this._escapeHtml(reading)
                        : ""
                    }
                  </div>

                  <div style="display:flex; gap:8px;">
                    ${
                      isEditing
                        ? `
                            <button class="ai-link-btn" data-save-metric="${fieldPath}">Save</button>
                            <button class="ai-link-btn" data-cancel-metric="${fieldPath}">Cancel</button>
                          `
                        : `
                            <button class="ai-link-btn" data-edit-metric="${fieldPath}">Update</button>
                            <button class="ai-link-btn ai-danger" data-remove-metric="${fieldPath}">Remove</button>
                          `
                    }
                  </div>

                </div>
              `;
            }).join("")}
          </div>
        `;
      }).join("")}

      <div class="ai-footer-actions">
        <button
          class="ai-primary-button"
          data-save-room-config="${this._escapeHtml(roomId)}"
          ${this._savingRoomId === roomId ? "disabled" : ""}
        >
          ${this._savingRoomId === roomId ? "Saving..." : "Save"}
        </button>
      </div>
    `;
  }


  _renderAssetDetail(assetId, assetEntities, areaMap, documentStorageState) {
    const asset = assetEntities.find((a) => a.attributes?.asset_id === assetId);
    if (!asset) {
      return `
        ${this._renderBreadcrumb([
          { label: "Asset Intelligence", nav: "home" },
          { label: "Unknown Asset" }
        ])}
        <div class="ai-empty">Asset not found.</div>
      `;
    }

    const attrs = asset.attributes || {};
    const draft = this._assetInfoDrafts?.[assetId] || {};
    const deviceMeta = this._getDeviceMetadataForAsset(assetId, attrs, asset.entity_id);
    const assetName = this._displayAssetName(asset);
    const storageEnabled = !!documentStorageState?.enabled;
    const storageAvailable = !!documentStorageState?.available;
    const roomAreaId = deviceMeta.area_id;
    const roomArea = roomAreaId ? areaMap[roomAreaId] : null;
    const roomName =
      roomArea?.name ||
      (roomAreaId
        ? this._titleCase(String(roomAreaId).replaceAll("_", " "))
        : "No room assigned");

    const breadcrumbItems = [{ label: "Asset Intelligence", nav: "home" }];
    if (roomAreaId) {
      breadcrumbItems.push({ label: roomName, roomId: roomAreaId });
    }
    breadcrumbItems.push({ label: assetName });

    const icon = this._getAssetIcon(attrs.asset_type, deviceMeta.labels);
    const imageUrl = this._resolvePrimaryDocumentImage(attrs) || attrs.image || attrs.primary_image || attrs.image_url || null;

    const riskState = String(
      attrs.environment_risk_state ||
      attrs.risk_state ||
      attrs.at_risk_state ||
      "UNKNOWN"
    ).toUpperCase();

    const advisories =
      Array.isArray(attrs.advisories)
        ? attrs.advisories
        : Array.isArray(attrs.asset_advisories)
          ? attrs.asset_advisories
          : [];

    const primaryAdvisory =
      attrs.primary_advisory_message ||
      attrs.primary_advisory ||
      advisories[0] ||
      null;

    const labels = this._normalizeLabelList(deviceMeta.labels);
    const documents = Array.isArray(attrs.documents) ? attrs.documents : [];
    const physicalLocations = Array.isArray(attrs.physical_document_locations)
      ? attrs.physical_document_locations
      : (Array.isArray(attrs.physical_documents) ? attrs.physical_documents : []);

    const activeHistoryFilter = String(this._assetHistoryFilter || "all").toLowerCase();
    const serviceHistoryPayload = this._assetHistoryCache?.[assetId] || null;
    const timelinePayload = serviceHistoryPayload || null;
    const timelineAll = Array.isArray(timelinePayload?.all) ? timelinePayload.all : [];
    const timelineByFilter = timelinePayload?.by_filter && typeof timelinePayload.by_filter === "object"
      ? timelinePayload.by_filter
      : null;
    const hasTimelinePayload = !!timelinePayload && Array.isArray(timelinePayload.all);

    const history = hasTimelinePayload ? timelineAll : [];
    const filteredHistory = hasTimelinePayload
      ? (() => {
        if (timelineByFilter && Array.isArray(timelineByFilter[activeHistoryFilter])) {
          const bucket = timelineByFilter[activeHistoryFilter];
          if (bucket.every((entry) => typeof entry === "number")) {
            return bucket.map((index) => history[Number(index)]).filter((entry) => !!entry);
          }
          return bucket;
        }
        return history;
      })()
      : [];
    this._currentHistory = filteredHistory;
    const statusSince = this._formatLocalDateTime(
      attrs.environment_state_since ||
      attrs.risk_state_since ||
      attrs.state_since ||
      attrs.updated_at ||
      asset.last_updated
    );

    const custody = attrs.custody && typeof attrs.custody === "object"
      ? attrs.custody
      : {};
    const loans = Array.isArray(attrs.loans) ? attrs.loans : [];
    const activeLoanOuts = this._getActiveLoanOuts(loans);

    const custodyStatus =
      attrs.custody_status ||
      custody.status ||
      "unknown";

    const custodyStatusText = this._titleCase(String(custodyStatus).replaceAll("_", " "));

    const holder =
      attrs.holder ||
      custody.owner ||
      custody.holder ||
      "â€”";

    const custodyLocationDetail =
      custody.location_detail ||
      custody.location ||
      attrs.location_detail ||
      this._readPath(attrs, "placement.location_detail") ||
      "â€”";

    const custodyEffectiveAt = this._formatLocalDateTime(
      custody.effective_at || attrs.updated_at || asset.last_updated
    );

    const descriptions = attrs.descriptions || {};
    const guestDescription =
      descriptions.guest ||
      attrs.description_guest ||
      "";
    const ownerDescription =
      descriptions.owner ||
      attrs.description_owner ||
      "";
    const insuranceDescription =
      descriptions.insurance ||
      attrs.insurance_description ||
      attrs.description_insurance ||
      "";

    const purchase = attrs.purchase || {};
    const valuation = attrs.valuation || {};
    const warranty = attrs.warranty || {};
    const links = attrs.links || {};
    const roomEnvironment = attrs.room_environment || {};

    const normalizedAssetType = String(
      draft.asset_type ?? attrs.asset_type ?? ""
    ).trim().toLowerCase();

    const headerRoomAreaId =
      draft.area_id ??
      deviceMeta.area_id ??
      null;

    const headerRoomArea = headerRoomAreaId ? areaMap[headerRoomAreaId] : null;
    const headerRoomName =
      headerRoomArea?.name ||
      (headerRoomAreaId
        ? this._titleCase(String(headerRoomAreaId).replaceAll("_", " "))
        : "No room assigned");

    const effectiveLabels = Array.isArray(draft.labels)
      ? draft.labels
      : this._normalizeLabelList(deviceMeta.labels);

    const effectiveIcon = this._getAssetIcon(attrs.asset_type, deviceMeta.labels);

    const placement = attrs.placement || {};
    const enclosure = attrs.enclosure || {};
    const trackers = Array.isArray(attrs.trackers) ? attrs.trackers : [];

    const nearWindowValue =
      draft.near_window ??
      placement.near_window ??
      false;

    const facingDirectionValue =
      draft.facing_direction ??
      placement.facing_direction ??
      "";

    const exposureZoneValue =
      draft.exposure_zone ??
      placement.exposure_zone ??
      "";

    const placementDescriptionValue =
      draft.placement_description ??
      placement.description ??
      placement.placement ??
      "";

    const locationDetailValue =
      draft.location_detail ??
      attrs.location_detail ??
      this._readPath(attrs, "custody.location") ??
      this._readPath(attrs, "placement.location_detail") ??
      "";

    const enclosureTypeValue =
      draft.enclosure_type ??
      enclosure.type ??
      "";

    const enclosureSealedValue =
      draft.enclosure_sealed ??
      enclosure.sealed ??
      false;

    const showManufacturerWarranty =
      ["electronics", "infrastructure", "instrument", "furniture"].includes(normalizedAssetType);

    const showAttachedDevice =
      ["electronics", "infrastructure", "instrument"].includes(normalizedAssetType);

    const linkedDeviceIdRaw =
      this._readPath(attrs, "links.device_id") ||
      links.device_id ||
      "";

    const currentTrackerEntityId = String(trackers[0]?.entity_id || "");
    const roomDeviceOptions = (() => {
      const roomArea = headerRoomAreaId || roomAreaId || "";
      const devices = (this._deviceRegistry || []).filter((device) => {
        const identifiers = Array.isArray(device?.identifiers) ? device.identifiers : [];
        const isInternal = identifiers.some((identifier) => (
          Array.isArray(identifier)
          && String(identifier[0] || "") === "asset_intelligence"
        ));
        if (isInternal) return false;
        if (!roomArea) return true;
        if (String(device?.id || "") === String(linkedDeviceIdRaw || "")) return true;
        return String(device?.area_id || "") === String(roomArea);
      });

      return devices
        .map((device) => ({
          id: String(device?.id || ""),
          name: String(device?.name_by_user || device?.name || device?.id || "Unknown device"),
        }))
        .filter((item) => item.id)
        .sort((a, b) => a.name.localeCompare(b.name));
    })();

    const trackerOptions = (() => {
      const allTrackerStates = Object.values(this._hass?.states || {})
        .filter((state) => String(state?.entity_id || "").startsWith("device_tracker."));

      const assigned = new Set();
      this._getAssetEntities().forEach((entity) => {
        const a = entity?.attributes || {};
        const aid = String(a.asset_id || "");
        if (aid === assetId) return;
        const t = Array.isArray(a.trackers) ? a.trackers : [];
        t.forEach((entry) => {
          const eid = String(entry?.entity_id || "");
          if (eid) assigned.add(eid);
        });
      });

      return allTrackerStates
        .filter((state) => {
          const eid = String(state?.entity_id || "");
          return eid === currentTrackerEntityId || !assigned.has(eid);
        })
        .map((state) => ({
          entity_id: String(state.entity_id || ""),
          name: String(state.attributes?.friendly_name || state.entity_id || "Tracker"),
        }))
        .sort((a, b) => a.name.localeCompare(b.name));
    })();

    const purchaseDateValue =
      purchase.purchase_date ||
      purchase.date ||
      "";

    const purchasePriceValue =
      purchase.purchase_price ||
      purchase.price ||
      "";

    const purchaseSourceValue =
      purchase.source ||
      "";

    const purchaseNotesValue =
      purchase.notes ||
      "";

    const valuationValue =
      valuation.estimated_value ||
      valuation.value ||
      "";

    const valuationDateValue =
      valuation.valuation_date ||
      valuation.date ||
      "";

    const valuationMethodValue =
      valuation.method ||
      "";

    const valuationNotesValue =
      valuation.notes ||
      "";
    const environmentReasons =
      Array.isArray(attrs.environment_risk_reasons)
        ? attrs.environment_risk_reasons
        : typeof attrs.environment_risk_reasons === "string" && attrs.environment_risk_reasons.trim()
          ? [attrs.environment_risk_reasons.trim()]
          : Array.isArray(attrs.environment_reasons)
            ? attrs.environment_reasons
            : typeof attrs.environment_reasons === "string" && attrs.environment_reasons.trim()
              ? [attrs.environment_reasons.trim()]
              : [];

    const candidateStateText = (() => {
      const raw = attrs.candidate_environment_risk_state || attrs.candidate_state || "";
      if (!raw) return "Unknown";
      return this._titleCase(String(raw).replaceAll("_", " ").toLowerCase());
    })();

    const primaryAdvisoryText = String(attrs.primary_advisory || "").trim() || "None";
    const primaryMessageText = String(attrs.primary_advisory_message || "").trim() || "No advisory message";
    const exposureRiskView = this._normalizeExposureRisk(attrs.exposure_risk);
    const activeMeasurement = attrs.active_measurement && typeof attrs.active_measurement === "object"
      ? attrs.active_measurement
      : null;
    const measurementStartedAt = String(activeMeasurement?.started_at || "").trim();
    const measurementIsActive = !!measurementStartedAt && !activeMeasurement?.completed;
    const measurementUpdateCount = Number(
      activeMeasurement?.update_count
      ?? (Array.isArray(activeMeasurement?.observations) ? activeMeasurement.observations.length : 0)
      ?? 0
    );
    const measurementElapsed = measurementStartedAt
      ? this._formatMeasurementElapsed(measurementStartedAt)
      : "00:00:00";

    return `
      ${this._renderBreadcrumb(breadcrumbItems)}

      <div class="ai-asset-shell">

        <div class="ai-asset-header-card">
          <div class="ai-asset-header-main">
            <div
              class="ai-asset-hero ${imageUrl ? "has-image" : ""}"
              ${imageUrl
                ? this._buildImageContainerAttrs(imageUrl)
                : ""}
            >
              ${
                imageUrl
                  ? ""
                  : `<ha-icon icon="${this._escapeHtml(effectiveIcon)}" style="opacity:0.7;"></ha-icon>`
              }
            </div>

            <div class="ai-asset-header-copy">
              <div class="ai-asset-header-title-row">
                <div class="ai-asset-header-title">
                  ${this._escapeHtml(draft.name ?? assetName)}
                </div>
              </div>

              <div class="ai-form-grid" style="margin-top: 10px;">
                <div class="ai-form-label">Room</div>
                <ha-area-picker
                  class="ai-form-control"
                  data-asset-info-watch
                  data-asset-area
                ></ha-area-picker>

                <div class="ai-form-label">Labels</div>
                <ha-labels-picker
                  class="ai-form-control"
                  data-asset-info-watch
                  data-asset-labels
                ></ha-labels-picker>

              </div>

            </div>

            <div class="ai-asset-header-actions">
              ${measurementIsActive
                ? `
                  <div
                    class="ai-measurement-pill"
                    data-measurement-started-at="${this._escapeHtml(measurementStartedAt)}"
                  >
                    <span class="ai-measurement-elapsed" data-measurement-elapsed>${this._escapeHtml(measurementElapsed)}</span>
                    <span class="ai-measurement-count">Updates: ${Number.isFinite(measurementUpdateCount) ? measurementUpdateCount : 0}</span>
                    <button
                      class="ai-measurement-stop"
                      type="button"
                      title="Stop measurement"
                      data-asset-stop-measure="${this._escapeHtml(assetId)}"
                    >
                      <ha-icon icon="mdi:stop"></ha-icon>
                    </button>
                  </div>
                `
                : ""
              }

              <div class="ai-inline-actions" data-asset-header-actions style="display:none; margin-top:0;">
                <button
                  class="ai-primary-button"
                  data-asset-header-save="${this._escapeHtml(assetId)}"
                  disabled
                >
                  Update
                </button>
                <button
                  class="ai-secondary-button"
                  data-asset-header-cancel="${this._escapeHtml(assetId)}"
                >
                  Cancel
                </button>
              </div>
              <div
                class="ai-overflow"
                data-asset-overflow="${this._escapeHtml(assetId)}"
              >
                <button class="ai-overflow-button" type="button" title="More actions">
                  â‹®
                </button>
                <div class="ai-overflow-menu">
                  ${measurementIsActive
                    ? `
                      <button
                        class="ai-overflow-item"
                        data-asset-stop-measure="${this._escapeHtml(assetId)}"
                      >
                        Stop measurement
                      </button>
                    `
                    : `
                      <button
                        class="ai-overflow-item"
                        data-asset-measure="${this._escapeHtml(assetId)}"
                      >
                        Start measurement
                      </button>
                    `
                  }
                  <button
                    class="ai-overflow-item"
                    data-asset-export="${this._escapeHtml(assetId)}"
                  >
                    Export asset
                  </button>
                  <button
                    class="ai-overflow-item ai-danger"
                    data-asset-delete="${this._escapeHtml(assetId)}"
                  >
                    Delete asset
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div class="ai-asset-status-strip">
            <div
              class="ai-asset-status-cell ai-risk-cell ai-risk-${riskState.toLowerCase()}"
              title="${this._escapeHtml(environmentReasons.length ? environmentReasons.join(' â€¢ ') : '')}"
            >
              <div class="ai-asset-status-label">Risk</div>
              <div class="ai-asset-status-value">
                ${riskState === "RED"
                  ? "Environmental Risk"
                  : this._escapeHtml(this._titleCase(String(riskState).toLowerCase()))}
              </div>
            </div>
            <div class="ai-asset-status-cell">
              <div class="ai-asset-status-label">Custody</div>
              <div class="ai-asset-status-value">
                ${this._escapeHtml(custodyStatusText)}
              </div>
            </div>
          </div>
        </div>

        <div class="ai-asset-layout">
          <!-- LEFT COLUMN -->
          <div class="ai-column">
            ${primaryAdvisory ? this._renderAssetAdvisoryBanner(primaryAdvisory, riskState) : ""}

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Asset information</div>
                    <div class="ai-panel-subtitle">
                      Identity, placement, enclosure, descriptions, and attachments
                    </div>
                  </div>
                </div>

                <div class="ai-form-grid">
                  <div class="ai-form-label">Asset ID</div>
                  <div class="ai-form-readonly">${this._escapeHtml(attrs.asset_id || "")}</div>

                  <div class="ai-form-label">Asset name</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="name"
                    value="${this._escapeHtml(draft.name ?? attrs.name ?? "")}"
                  />

                  <div class="ai-form-label">Asset type</div>
                  <select
                    class="ai-select ai-form-control"
                    data-asset-info-watch
                    data-asset-field="asset_type"
                  >
                    <option value="">Select asset type</option>
                    ${this._getAssetTypeOptions().map((opt) => `
                      <option
                        value="${this._escapeHtml(opt.value)}"
                        ${String(draft.asset_type ?? attrs.asset_type ?? "") === opt.value ? "selected" : ""}
                      >
                        ${this._escapeHtml(opt.label)}
                      </option>
                    `).join("")}

                  </select>

                  <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                    Placement / Location
                  </div>

                  <div class="ai-form-label">Near window</div>
                  <select
                    class="ai-select ai-form-control"
                    data-asset-info-watch
                    data-asset-field="near_window"
                  >
                    <option value="false" ${nearWindowValue ? "" : "selected"}>No</option>
                    <option value="true" ${nearWindowValue ? "selected" : ""}>Yes</option>
                  </select>

                  <div class="ai-form-label">Facing direction</div>
                  <select
                    class="ai-select ai-form-control"
                    data-asset-info-watch
                    data-asset-field="facing_direction"
                  >
                    <option value="">Select direction</option>
                    ${WINDOW_DIRECTIONS.map((dir) => `
                      <option
                        value="${this._escapeHtml(dir)}"
                        ${String(facingDirectionValue) === dir ? "selected" : ""}
                      >
                        ${this._escapeHtml(this._titleCase(dir))}
                      </option>
                    `).join("")}
                  </select>

                  <div class="ai-form-label">Exposure zone</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="exposure_zone"
                    value="${this._escapeHtml(exposureZoneValue)}"
                  />

                  <div class="ai-form-label">Placement</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="placement_description"
                    value="${this._escapeHtml(placementDescriptionValue)}"
                  />

                  <div class="ai-form-label">Location detail</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="location_detail"
                    value="${this._escapeHtml(locationDetailValue)}"
                  />

                  <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                    Enclosure
                  </div>

                  <div class="ai-form-label">Enclosure type</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="enclosure_type"
                    value="${this._escapeHtml(enclosureTypeValue)}"
                  />

                  <div class="ai-form-label">Enclosure sealed</div>
                  <select
                    class="ai-select ai-form-control"
                    data-asset-info-watch
                    data-asset-field="enclosure_sealed"
                  >
                    <option value="false" ${enclosureSealedValue ? "" : "selected"}>No</option>
                    <option value="true" ${enclosureSealedValue ? "selected" : ""}>Yes</option>
                  </select>

                  <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                    Descriptions
                  </div>

                  <div class="ai-form-label">Guest</div>
                  <textarea
                    class="ai-textarea ai-form-control"
                    data-asset-info-watch
                    data-asset-field="description_guest"
                  >${this._escapeHtml(draft.description_guest ?? guestDescription)}</textarea>

                  <div class="ai-form-label">Owner</div>
                  <textarea
                    class="ai-textarea ai-form-control"
                    data-asset-info-watch
                    data-asset-field="description_owner"
                  >${this._escapeHtml(draft.description_owner ?? ownerDescription)}</textarea>

                  <div class="ai-form-label">Insurance</div>
                  <textarea
                    class="ai-textarea ai-form-control"
                    data-asset-info-watch
                    data-asset-field="description_insurance"
                  >${this._escapeHtml(draft.description_insurance ?? insuranceDescription)}</textarea>

                  ${showManufacturerWarranty ? `
                    <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                      Manufacturer / Warranty
                    </div>

                    <div class="ai-form-label">Manufacturer</div>
                    <textarea
                      class="ai-textarea ai-form-control"
                      data-asset-info-watch
                      data-asset-field="manufacturer_detail"
                    >${this._escapeHtml(
                      draft.manufacturer_detail ??
                      (typeof attrs.manufacturer_detail === "object"
                        ? JSON.stringify(attrs.manufacturer_detail, null, 2)
                        : (attrs.manufacturer_detail || ""))
                    )}</textarea>

                    <div class="ai-form-label">Warranty</div>
                    <textarea
                      class="ai-textarea ai-form-control"
                      data-asset-info-watch
                      data-asset-field="warranty"
                    >${this._escapeHtml(
                      draft.warranty ??
                      (typeof warranty === "object"
                        ? JSON.stringify(warranty, null, 2)
                        : (warranty || ""))
                    )}</textarea>
                  ` : ""}

                  ${showAttachedDevice ? `
                    <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                      Attached device
                    </div>

                    <div class="ai-form-label">Device</div>
                    <select
                      class="ai-select ai-form-control"
                      data-asset-info-watch
                      data-asset-field="linked_device_id"
                    >
                      <option value="">No linked device</option>
                      ${roomDeviceOptions.map((device) => `
                        <option
                          value="${this._escapeHtml(device.id)}"
                          ${String(draft.linked_device_id ?? linkedDeviceIdRaw ?? "") === device.id ? "selected" : ""}
                        >
                          ${this._escapeHtml(device.name)}
                        </option>
                      `).join("")}
                    </select>
                  ` : ""}

                  <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                    Attached tracker
                  </div>

                  <div class="ai-form-label">Tracker</div>
                  <select
                    class="ai-select ai-form-control"
                    data-asset-info-watch
                    data-asset-field="tracker_entity_id"
                  >
                    <option value="">No tracker</option>
                    ${trackerOptions.map((tracker) => `
                      <option
                        value="${this._escapeHtml(tracker.entity_id)}"
                        ${String(draft.tracker_entity_id ?? currentTrackerEntityId ?? "") === tracker.entity_id ? "selected" : ""}
                      >
                        ${this._escapeHtml(tracker.name)}
                      </option>
                    `).join("")}
                  </select>
                </div>

                <div class="ai-inline-actions" data-asset-info-actions style="display:none;">
                  <button
                    class="ai-primary-button"
                    data-asset-info-save="${this._escapeHtml(assetId)}"
                    disabled
                  >
                    Save changes
                  </button>
                  <button
                    class="ai-secondary-button"
                    data-asset-info-cancel="${this._escapeHtml(assetId)}"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Financial and reference</div>
                    <div class="ai-panel-subtitle">
                      Purchase and valuation reference data
                    </div>
                  </div>
                </div>

                <div class="ai-form-grid">
                  <div class="ai-form-label" style="grid-column: 1 / -1; font-weight: 700; color: var(--primary-text-color);">
                    Purchase
                  </div>

                  <div class="ai-form-label">Purchase date</div>
                  <input
                    class="ai-input ai-form-control"
                    type="date"
                    data-asset-info-watch
                    data-asset-field="purchase_date"
                    value="${this._escapeHtml(String(draft.purchase_date ?? purchaseDateValue ?? ""))}"
                  />

                  <div class="ai-form-label">Purchase price</div>
                  <input
                    class="ai-input ai-form-control"
                    type="number"
                    step="0.01"
                    min="0"
                    data-asset-info-watch
                    data-asset-field="purchase_price"
                    value="${this._escapeHtml(String(draft.purchase_price ?? purchasePriceValue ?? ""))}"
                  />

                  <div class="ai-form-label">Source</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="purchase_source"
                    value="${this._escapeHtml(String(draft.purchase_source ?? purchaseSourceValue ?? ""))}"
                  />

                  <div class="ai-form-label">Notes</div>
                  <textarea
                    class="ai-textarea ai-form-control"
                    data-asset-info-watch
                    data-asset-field="purchase_notes"
                  >${this._escapeHtml(String(draft.purchase_notes ?? purchaseNotesValue ?? ""))}</textarea>

                  <div class="ai-form-label" style="grid-column: 1 / -1; margin-top: 10px; font-weight: 700; color: var(--primary-text-color);">
                    Valuation
                  </div>

                  <div class="ai-form-label">Estimated value</div>
                  <input
                    class="ai-input ai-form-control"
                    type="number"
                    step="0.01"
                    min="0"
                    data-asset-info-watch
                    data-asset-field="valuation_estimated_value"
                    value="${this._escapeHtml(String(draft.valuation_estimated_value ?? valuationValue ?? ""))}"
                  />

                  <div class="ai-form-label">Valuation date</div>
                  <input
                    class="ai-input ai-form-control"
                    type="date"
                    data-asset-info-watch
                    data-asset-field="valuation_date"
                    value="${this._escapeHtml(String(draft.valuation_date ?? valuationDateValue ?? ""))}"
                  />

                  <div class="ai-form-label">Method</div>
                  <input
                    class="ai-input ai-form-control"
                    data-asset-info-watch
                    data-asset-field="valuation_method"
                    value="${this._escapeHtml(String(draft.valuation_method ?? valuationMethodValue ?? ""))}"
                  />

                  <div class="ai-form-label">Notes</div>
                  <textarea
                    class="ai-textarea ai-form-control"
                    data-asset-info-watch
                    data-asset-field="valuation_notes"
                  >${this._escapeHtml(String(draft.valuation_notes ?? valuationNotesValue ?? ""))}</textarea>
                </div>

                <div class="ai-inline-actions" data-asset-financial-actions style="display:none;">
                  <button
                    class="ai-primary-button"
                    data-asset-financial-save="${this._escapeHtml(assetId)}"
                    disabled
                  >
                    Save changes
                  </button>
                  <button
                    class="ai-secondary-button"
                    data-asset-financial-cancel="${this._escapeHtml(assetId)}"
                  >
                    Cancel
                  </button>
                </div>

              </div>
            </div>

            ${this._renderAssetDocumentPanel(
              assetId,
              attrs,
              documents,
              physicalLocations,
              storageEnabled,
              storageAvailable
            )}
          </div>

          <!-- MIDDLE COLUMN -->
          <div class="ai-column">

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Environment limits</div>
                    <div class="ai-panel-subtitle">
                      Requirement range vs current room conditions
                    </div>
                  </div>
                </div>

                <div class="ai-measure-list">
                  ${this._renderEnvironmentCategory(
                    "Climate",
                    attrs,
                    "climate",
                    ["temperature", "humidity", "dew_point"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Light",
                    attrs,
                    "light",
                    ["lux", "uv"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Air quality",
                    attrs,
                    "air_quality",
                    ["voc", "formaldehyde", "ozone", "no2"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Particulates",
                    attrs,
                    "particulates",
                    ["pm2_5", "pm10"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Biological",
                    attrs,
                    "biological",
                    ["mold_index"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Safety",
                    attrs,
                    "safety",
                    ["leak"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Structural",
                    attrs,
                    "structural",
                    ["pressure", "vibration"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Context",
                    attrs,
                    "context",
                    ["noise"]
                  )}
                  ${this._renderEnvironmentCategory(
                    "Control context",
                    attrs,
                    "control_context",
                    ["co2"]
                  )}
                  ${this._renderEnvironmentDebounceSettings(attrs)}
                </div>

                <div class="ai-inline-actions" data-asset-environment-actions style="display:none;">
                  <button
                    class="ai-primary-button"
                    data-asset-environment-save="${this._escapeHtml(assetId)}"
                    disabled
                  >
                    Save changes
                  </button>
                  <button
                    class="ai-secondary-button"
                    data-asset-environment-cancel="${this._escapeHtml(assetId)}"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- RIGHT COLUMN -->
          <div class="ai-column">

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Risk and advisory</div>
                    <div class="ai-panel-subtitle">
                      Current risk output and reasons
                    </div>
                  </div>
                </div>

                  <div class="ai-readout-grid">
                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Status since</div>
                      <div class="ai-readout-value">${this._escapeHtml(statusSince)}</div>
                    </div>

                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Candidate state</div>
                      <div class="ai-readout-value">${this._escapeHtml(candidateStateText)}</div>
                    </div>

                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Primary advisory</div>
                      <div class="ai-readout-value">${this._escapeHtml(primaryAdvisoryText)}</div>
                    </div>

                    <div class="ai-readout-row ai-readout-section">
                      <div class="ai-readout-label">Primary message</div>
                      <div class="ai-readout-value">${this._escapeHtml(primaryMessageText)}</div>
                    </div>

                    <div class="ai-readout-row ai-readout-section">
                      <div class="ai-readout-label">Risk reasons</div>
                      <div class="ai-readout-value">
                        ${this._renderStructuredReadoutValue(environmentReasons, "No risk reasons available")}
                      </div>
                    </div>

                    <div class="ai-readout-row ai-readout-section">
                      <div class="ai-readout-label">Exposure risk</div>
                      <div class="ai-readout-value">
                        ${this._renderExposureRiskReadout(exposureRiskView)}
                      </div>
                    </div>

                    <div class="ai-readout-row ai-readout-section">
                      <div class="ai-readout-label">Spatial context</div>
                      <div class="ai-readout-value">
                        ${this._renderStructuredReadoutValue(attrs.spatial_context, "No spatial context available")}
                      </div>
                    </div>

                    <div class="ai-readout-row">
                      <div class="ai-readout-label">Event count</div>
                      <div class="ai-readout-value">${this._escapeHtml(String(attrs.environment_event_count ?? "â€”"))}</div>
                    </div>
                  </div>
                </div>
            </div>

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Check in / Check out / Custody</div>
                    <div class="ai-panel-subtitle">
                      Current custody state and loan workflow actions
                    </div>
                  </div>
                </div>

                <div class="ai-readout-grid">
                  <div class="ai-readout-row">
                    <div class="ai-readout-label">Current status</div>
                    <div class="ai-readout-value">${this._escapeHtml(custodyStatusText)}</div>
                  </div>
                  <div class="ai-readout-row">
                    <div class="ai-readout-label">Holder</div>
                    <div class="ai-readout-value">${this._escapeHtml(holder)}</div>
                  </div>
                  <div class="ai-readout-row">
                    <div class="ai-readout-label">Location detail</div>
                    <div class="ai-readout-value">${this._escapeHtml(custodyLocationDetail)}</div>
                  </div>
                  <div class="ai-readout-row">
                    <div class="ai-readout-label">Effective at</div>
                    <div class="ai-readout-value">${this._escapeHtml(custodyEffectiveAt)}</div>
                  </div>
                  <div class="ai-readout-row">
                    <div class="ai-readout-label">Open loans</div>
                    <div class="ai-readout-value">${activeLoanOuts.length}</div>
                  </div>
                </div>

                <div
                  class="ai-inline-actions"
                  style="margin-top: 12px; display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:8px; align-items:stretch;"
                >
                  <div></div>
                  <button
                    class="ai-secondary-button"
                    data-custody-action="set_status"
                    data-custody-asset="${this._escapeHtml(assetId)}"
                    style="justify-self:end;"
                  >
                    Update custody
                  </button>
                  <button
                    class="ai-primary-button"
                    data-custody-action="loan_out"
                    data-custody-asset="${this._escapeHtml(assetId)}"
                    style="justify-self:start;"
                  >
                    Check out / Loan out
                  </button>
                  <button
                    class="ai-secondary-button"
                    data-custody-action="loan_in"
                    data-custody-asset="${this._escapeHtml(assetId)}"
                    ${activeLoanOuts.length ? "" : "disabled"}
                    style="justify-self:end;"
                  >
                    Check in / Loan in
                  </button>
                </div>

                ${activeLoanOuts.length
                  ? ""
                  : `<div class="ai-readout-muted" style="margin-top: 8px;">No active outgoing loan is open for this asset.</div>`
                }
              </div>
            </div>

            <div class="ai-panel-card">
              <div class="ai-panel-body">
                <div class="ai-panel-title-row">
                  <div>
                    <div class="ai-panel-title">Activity</div>
                    <div class="ai-panel-subtitle">
                      Environment, documents, custody, and audit timeline
                    </div>
                  </div>
                </div>

                <div class="ai-timeline-filters">
                  <button type="button" class="ai-filter-chip tone-neutral ${activeHistoryFilter === "all" ? "active" : ""}" data-asset-history-filter="all">All</button>
                  <button type="button" class="ai-filter-chip tone-neutral ${activeHistoryFilter === "audit" ? "active" : ""}" data-asset-history-filter="audit">Audit</button>
                  <button type="button" class="ai-filter-chip tone-amber ${activeHistoryFilter === "environment" ? "active" : ""}" data-asset-history-filter="environment">Environment</button>
                  <button type="button" class="ai-filter-chip tone-red ${activeHistoryFilter === "risk" ? "active" : ""}" data-asset-history-filter="risk">Risk</button>
                  <button type="button" class="ai-filter-chip tone-green ${activeHistoryFilter === "documents" ? "active" : ""}" data-asset-history-filter="documents">Documents</button>
                  <button type="button" class="ai-filter-chip tone-amber ${activeHistoryFilter === "custody" ? "active" : ""}" data-asset-history-filter="custody">Custody</button>
                  <button type="button" class="ai-filter-chip tone-neutral ${activeHistoryFilter === "measurements" ? "active" : ""}" data-asset-history-filter="measurements">Measurements</button>
                </div>

                <div class="ai-timeline">
                  ${!hasTimelinePayload && this._assetHistoryLoading?.[assetId]
                    ? `<div class="ai-empty">Loading activity...</div>`
                    : filteredHistory.length
                    ? filteredHistory.map((item, index) => `
                      <div
                        class="ai-timeline-item ${this._escapeHtml(item.color)}"
                        data-history-kind="${this._escapeHtml(item.kind)}"
                        data-history-index="${index}"
                        title="Click to view details"
                      >
                        <div class="ai-timeline-meta">
                          ${this._escapeHtml(item.meta)}
                        </div>
                        <div class="ai-timeline-title">
                          ${this._escapeHtml(item.title)}
                        </div>
                      </div>
                    `).join("")
                    : `<div class="ai-empty">No activity available for this filter.</div>`
                  }
                </div>
              </div>
            </div>

          </div>

        </div>
      </div>
    `;
  }

  _renderAssetAdvisoryBanner(primaryAdvisory, riskState) {
    const title =
      typeof primaryAdvisory === "string"
        ? primaryAdvisory
        : primaryAdvisory?.title || primaryAdvisory?.message || "Advisory";
    const copy =
      typeof primaryAdvisory === "string"
        ? ""
        : primaryAdvisory?.recommendation || primaryAdvisory?.detail || "";

    const tone = String(riskState || "").toUpperCase() === "RED" ? "" : "warning";

    return `
      <div class="ai-panel-card">
        <div class="ai-panel-body">
          <div class="ai-advisory-banner ${tone}">
            <div class="ai-advisory-kicker">Primary advisory</div>
            <div class="ai-advisory-title">${this._escapeHtml(title)}</div>
            ${copy ? `<div class="ai-advisory-copy">${this._escapeHtml(copy)}</div>` : ""}
          </div>
        </div>
      </div>
    `;
  }

  _renderAssetDocumentPanel(assetId, attrs, documents, physicalLocations, storageEnabled, storageAvailable) {
    return `
      <div class="ai-panel-card">
        <div class="ai-panel-body">
          <div class="ai-panel-title-row">
            <div>
              <div class="ai-panel-title">Documents</div>
              <div class="ai-panel-subtitle">Digital metadata plus physical location tracking</div>
            </div>
            <div style="display:flex; gap:10px;">
              <button
                class="ai-secondary-button"
                data-asset-attach-document="${this._escapeHtml(assetId)}"
              >
                Attach external
              </button>
              <button
                    class="ai-primary-button"
                data-asset-upload-document="${this._escapeHtml(assetId)}"
                ${storageEnabled ? "" : "disabled"}
              >
                Upload
              </button>
            </div>
          </div>

          ${!storageEnabled ? `
            <div class="ai-warning-box" style="margin-bottom:12px;">
              <strong>Document management is disabled in integration options.</strong><br/>
              Existing document metadata is shown below, but upload / attach / access actions must remain disabled.
            </div>
          ` : (!storageAvailable ? `
            <div class="ai-warning-box" style="margin-bottom:12px;">
              <strong>Document management is enabled, but storage is currently unavailable.</strong><br/>
              Actions are enabled from configuration, but file operations may fail until storage becomes available.
            </div>
          ` : "")}

          <div class="ai-doc-list">
            ${documents.length
              ? documents.map((doc, index) => {
                  const physical = this._resolvePhysicalDocumentLocation(doc, physicalLocations);
                  const title = doc?.title || doc?.filename || doc?.name || `Document ${index + 1}`;
                  const type = this._titleCase(String(doc?.type || "â€”").replaceAll("_", " "));
                  const date = doc?.date || doc?.created_at || "â€”";
                  const physicalLocationText = physical?.location
                    ? this._titleCase(String(physical.location).replaceAll("_", " "))
                    : "â€”";
                  const physicalNotesText = physical?.notes || "â€”";

                  return `
                    <div class="ai-doc-card">
                      <div class="ai-doc-body">
                        <div class="ai-doc-head">
                          <div class="ai-doc-title">${this._escapeHtml(title)}</div>
                        </div>

                        <div class="ai-doc-meta">
                          <div class="ai-doc-meta-label">Document type</div>
                          <div>${this._escapeHtml(String(type))}</div>

                          <div class="ai-doc-meta-label">Title</div>
                          <div>${this._escapeHtml(String(title))}</div>

                          <div class="ai-doc-meta-label">Date</div>
                          <div>${this._escapeHtml(String(date))}</div>

                          <div class="ai-doc-meta-label">Physical location</div>
                          <div>${this._escapeHtml(String(physicalLocationText))}</div>

                          <div class="ai-doc-meta-label">Notes</div>
                          <div>${this._escapeHtml(String(physicalNotesText))}</div>
                        </div>

                        <div class="ai-doc-actions">
                          <button class="ai-doc-action-button is-ghost" data-doc-view="${this._escapeHtml(doc.document_id || "")}">View</button>
                          <button class="ai-doc-action-button is-secondary" data-doc-edit="${this._escapeHtml(doc.document_id || "")}">Edit</button>
                          <button class="ai-doc-action-button is-secondary" data-doc-add-physical="${this._escapeHtml(doc.document_id || "")}">Edit Physical Location</button>
                          <button class="ai-doc-action-button is-danger" data-doc-delete="${this._escapeHtml(doc.document_id || "")}">Delete</button>
                        </div>
                      </div>
                    </div>
                  `;
                }).join("")
              : `<div class="ai-empty">No documents attached to this asset.</div>`
            }
          </div>
        </div>
      </div>
    `;
  }
_getAssetEnvironmentDraft(assetId, attrs) {
    if (!assetId) return {};
    if (!this._assetEnvironmentDrafts[assetId]) {
      const requirements =
        attrs?.environment_requirements ||
        {};
      this._assetEnvironmentDrafts[assetId] = JSON.parse(JSON.stringify(requirements));
    }
    return this._assetEnvironmentDrafts[assetId];
  }

  _clearAssetEnvironmentDraft(assetId) {
    if (!assetId) return;
    delete this._assetEnvironmentDrafts[assetId];
  }

  _updateAssetEnvironmentDraftField(assetId, categoryKey, metricKey, boundKey, rawValue) {
    if (!assetId || !categoryKey || !metricKey || !boundKey) return;
    const asset = this._getAssetEntities().find(
      (a) => a.attributes?.asset_id === assetId
    );
    if (!asset) return;

    const attrs = asset.attributes || {};
    const draft = this._getAssetEnvironmentDraft(assetId, attrs);

    if (!draft[categoryKey] || typeof draft[categoryKey] !== "object") {
      draft[categoryKey] = {};
    }
    if (!draft[categoryKey][metricKey] || typeof draft[categoryKey][metricKey] !== "object") {
      draft[categoryKey][metricKey] = { min: null, max: null };
    }

    const trimmed = String(rawValue ?? "").trim();
    draft[categoryKey][metricKey][boundKey] =
      trimmed === "" ? null : Number(trimmed);

    this._refreshAssetEnvironmentSaveState();
  }

  _updateAssetEnvironmentDebounceField(assetId, debounceKey, rawValue) {
    if (!assetId || !debounceKey) return;
    const asset = this._getAssetEntities().find(
      (a) => a.attributes?.asset_id === assetId
    );
    if (!asset) return;

    const attrs = asset.attributes || {};
    const draft = this._getAssetEnvironmentDraft(assetId, attrs);

    if (!draft.debounce || typeof draft.debounce !== "object") {
      draft.debounce = {};
    }

    const trimmed = String(rawValue ?? "").trim();
    draft.debounce[debounceKey] = trimmed === "" ? null : Number(trimmed);

    this._refreshAssetEnvironmentSaveState();
  }

  _formatEnvironmentMetricValue(categoryKey, metricKey, value) {
    if (value === null || value === undefined || value === "") return "-";

    const unitDefaults = {
      "climate.temperature": " degF",
      "climate.humidity": " %",
      "climate.dew_point": " degF",
      "light.lux": " lx",
      "light.uv": "",
      "air_quality.voc": " ppb",
      "air_quality.formaldehyde": " ppb",
      "air_quality.ozone": " ppb",
      "air_quality.no2": " ppb",
      "particulates.pm2_5": " ug/m3",
      "particulates.pm10": " ug/m3",
      "safety.leak": "",
      "structural.pressure": " hPa",
      "structural.vibration": " mm/s",
      "context.noise": " dB",
      "control_context.co2": " ppm",
    };

    const fieldPath = `${categoryKey}.${metricKey}`;
    const fallbackUnit = unitDefaults[fieldPath] || "";

    if (typeof value === "boolean") {
      return value ? "Detected" : "Clear";
    }

    return fallbackUnit
      ? this._displayValueWithUnit(value, fallbackUnit)
      : this._displayValue(value);
  }

  _computeEnvironmentMarkerPercent(current, min, max) {
    const value = Number(current);
    const low = Number(min);
    const high = Number(max);

    if (Number.isNaN(value)) return 50;
    if (Number.isNaN(low) || Number.isNaN(high) || high <= low) return 50;

    if (value < low) {
      const belowSpan = Math.max((high - low) * 0.5, 1);
      const ratio = Math.max(0, Math.min(1, (low - value) / belowSpan));
      return 25 - ratio * 25;
    }

    if (value > high) {
      const aboveSpan = Math.max((high - low) * 0.5, 1);
      const ratio = Math.max(0, Math.min(1, (value - high) / aboveSpan));
      return 75 + ratio * 25;
    }

    const inRangeRatio = (value - low) / (high - low);
    return 25 + inRangeRatio * 50;
  }

  _assetEnvironmentHasValidationErrors(assetId, attrs) {
    const draft = this._getAssetEnvironmentDraft(assetId, attrs);
    const categories = Object.entries(draft || {});
    for (const [categoryKey, categoryValue] of categories) {
      if (!categoryValue || typeof categoryValue !== "object") continue;
      for (const [metricKey, metricValue] of Object.entries(categoryValue)) {
        if (!metricValue || typeof metricValue !== "object") continue;
        const min = metricValue.min;
        const max = metricValue.max;
        if (
          min !== null &&
          min !== undefined &&
          max !== null &&
          max !== undefined &&
          !Number.isNaN(Number(min)) &&
          !Number.isNaN(Number(max)) &&
          Number(min) >= Number(max)
        ) {
          return true;
        }
      }
    }
    return false;
  }

  _isAssetEnvironmentDirty(assetId, attrs) {
    const liveRequirements =
      attrs?.environment_requirements ||
      {};
    const draft = this._getAssetEnvironmentDraft(assetId, attrs);

    return JSON.stringify(draft) !== JSON.stringify(liveRequirements);
  }

  _refreshAssetEnvironmentSaveState() {
    this._refreshAssetInfoSaveState();
  }

  _refreshAssetEnvironmentInputErrors(assetId) {
    if (!assetId) return;
    const asset = this._getAssetEntities().find((a) => a.attributes?.asset_id === assetId);
    if (!asset) return;
    const attrs = asset.attributes || {};
    const draft = this._getAssetEnvironmentDraft(assetId, attrs);

    this.querySelectorAll("[data-env-input]").forEach((el) => {
      const categoryKey = el.getAttribute("data-env-category");
      const metricKey = el.getAttribute("data-env-metric");
      if (!categoryKey || !metricKey) return;

      const metric = draft?.[categoryKey]?.[metricKey] || {};
      const min = metric?.min;
      const max = metric?.max;
      const hasRangeError =
        min !== null &&
        min !== undefined &&
        max !== null &&
        max !== undefined &&
        !Number.isNaN(Number(min)) &&
        !Number.isNaN(Number(max)) &&
        Number(min) >= Number(max);

      el.classList.toggle("ai-range-input-error", !!hasRangeError);
    });
  }

  async _saveAssetEnvironmentLimits(assetId) {
    const asset = this._getAssetEntities().find(
      (a) => a.attributes?.asset_id === assetId
    );
    if (!asset) return false;

    const attrs = asset.attributes || {};
    const draft = this._getAssetEnvironmentDraft(assetId, attrs);

    if (this._assetEnvironmentHasValidationErrors(assetId, attrs)) {
      alert("Each minimum value must be lower than its corresponding maximum value.");
      return false;
    }

    try {
      await this._callService("asset_intelligence", "set_environment_requirements", {
        asset_id: assetId,
        environment_requirements: JSON.parse(JSON.stringify(draft)),
      });
      this._clearAssetEnvironmentDraft(assetId);
      await this._load();
      return true;
    } catch (err) {
      console.error("Failed to save environment limits", err);
      alert("Failed to save environment limits");
      return false;
    }
  }

  _renderEnvironmentCategory(title, attrs, categoryKey, metricKeys) {
    const assetId = this._view?.assetId;
    const liveRequirements =
      attrs.environment_requirements?.[categoryKey] ||
      this._readPath(attrs, `environment_requirements.${categoryKey}`) ||
      {};
    const draftRequirements = assetId
      ? (this._getAssetEnvironmentDraft(assetId, attrs)?.[categoryKey] || {})
      : liveRequirements;

    const currentValues =
      attrs.room_environment?.[categoryKey] ||
      attrs[categoryKey] ||
      {};
    const advisories =
      attrs.evaluation?.[categoryKey] ||
      attrs.advisory?.[categoryKey] ||
      {};

    const body = metricKeys.map((metricKey) => {
      const requirement = draftRequirements?.[metricKey] || liveRequirements?.[metricKey] || {};
      const current = currentValues?.[metricKey];
      const min = requirement?.min ?? requirement?.low ?? null;
      const max = requirement?.max ?? requirement?.high ?? null;
      const advisory =
        advisories?.[metricKey] ||
        {};
      const state = this._deriveMeasureState(current, min, max);
      const stateClass =
        state === "critical" || state === "red" || state === "out_of_range"
          ? "red"
          : state === "warning" || state === "amber" || state === "near_edge"
            ? "amber"
            : "green";
      const recommendation =
        advisory?.recommendation ||
        advisory?.message ||
        "";

      const currentLabel = this._formatEnvironmentMetricValue(categoryKey, metricKey, current);
      const markerPercent = this._computeEnvironmentMarkerPercent(current, min, max);

      const unitLabel = (() => {
        const formatted = this._formatEnvironmentMetricValue(categoryKey, metricKey, 1);
        if (!formatted || formatted === "â€”") return "";
        const raw = String(formatted);

        if (raw.endsWith(" Â°F")) return "Â°F";
        if (raw.endsWith(" %")) return "%";
        if (raw.endsWith(" lx")) return "lx";
        if (raw.endsWith(" ppb")) return "ppb";
        if (raw.endsWith(" Âµg/mÂ³")) return "Âµg/mÂ³";
        if (raw.endsWith(" hPa")) return "hPa";
        if (raw.endsWith(" mm/s")) return "mm/s";
        if (raw.endsWith(" dB")) return "dB";
        if (raw.endsWith(" ppm")) return "ppm";

        return "";
      })();

      const titleText = this._titleCase(metricKey.replaceAll("_", " "));

      const hasRangeError =
        min !== null &&
        min !== undefined &&
        max !== null &&
        max !== undefined &&
        !Number.isNaN(Number(min)) &&
        !Number.isNaN(Number(max)) &&
        Number(min) >= Number(max);

      return `
        <div class="ai-measure-card">
          <div class="ai-measure-title-row">
            <div class="ai-measure-title">${this._escapeHtml(titleText)}${unitLabel ? ` (${this._escapeHtml(unitLabel)})` : ""}</div>
            <!-- removed textual state label -->
          </div>

          <div class="ai-range-row">
            <input
              type="number"
              step="any"
              inputmode="decimal"
              class="ai-input ai-range-input ${hasRangeError ? "ai-range-input-error" : ""}"
              data-env-input="min"
              data-env-category="${this._escapeHtml(categoryKey)}"
              data-env-metric="${this._escapeHtml(metricKey)}"
              value="${this._escapeHtml(min ?? "")}"
            />

            <div class="ai-range-track">
              <div class="ai-range-threshold ai-range-threshold-low"></div>
              <div class="ai-range-threshold ai-range-threshold-high"></div>
              <div
                class="ai-range-marker ${stateClass}"
                style="left:${markerPercent}%;"
                title="${this._escapeHtml(currentLabel)}"
              ></div>
              <div
                class="ai-range-current-label"
                style="left:${markerPercent}%;"
              >${currentLabel}</div>
            </div>

            <input
              type="number"
              step="any"
              inputmode="decimal"
              class="ai-input ai-range-input ${hasRangeError ? "ai-range-input-error" : ""}"
              data-env-input="max"
              data-env-category="${this._escapeHtml(categoryKey)}"
              data-env-metric="${this._escapeHtml(metricKey)}"
              value="${this._escapeHtml(max ?? "")}"
            />
          </div>

          <div class="ai-measure-detail">
            ${recommendation ? `${this._escapeHtml(recommendation)}` : "&nbsp;"}
          </div>
        </div>
      `;
    }).join("");

    return `
      <div class="ai-category-card">
        <div class="ai-category-head">${this._escapeHtml(title)}</div>
        <div class="ai-category-body">
          ${body}
        </div>
      </div>
    `;
  }

  _renderEnvironmentDebounceSettings(attrs) {
    const assetId = this._view?.assetId;
    const draft = assetId
      ? this._getAssetEnvironmentDraft(assetId, attrs)
      : (attrs?.environment_requirements || {});

    const liveDebounce = attrs?.environment_requirements?.debounce || {};
    const draftDebounce = draft?.debounce || liveDebounce || {};

    const redTransitionValue =
      draftDebounce?.red_transition_seconds ??
      liveDebounce?.red_transition_seconds ??
      "";

    const recoveryValue =
      draftDebounce?.recovery_seconds ??
      liveDebounce?.recovery_seconds ??
      "";

    return `
      <div class="ai-category-card">
        <div class="ai-category-head">Debounce settings</div>
        <div class="ai-category-body">
          <div class="ai-debounce-subtle">
            Debounce values smooth risk transitions to avoid rapid state flapping from brief spikes.
          </div>

          <div class="ai-debounce-grid">
            <div class="ai-debounce-row">
              <label
                class="ai-debounce-label"
                title="How long a RED candidate condition must continuously persist before the asset is promoted to RED risk state."
              >
                Red transition seconds
                <span class="ai-debounce-help" title="How long a RED candidate condition must continuously persist before the asset is promoted to RED risk state.">?</span>
              </label>

              <input
                type="number"
                min="0"
                step="1"
                class="ai-input ai-range-input"
                data-env-debounce-key="red_transition_seconds"
                value="${this._escapeHtml(redTransitionValue)}"
              />
            </div>

            <div class="ai-debounce-row">
              <label
                class="ai-debounce-label"
                title="How long stable in-range conditions must persist before clearing pending RED state and returning toward normal state."
              >
                Recovery seconds
                <span class="ai-debounce-help" title="How long stable in-range conditions must persist before clearing pending RED state and returning toward normal state.">?</span>
              </label>

              <input
                type="number"
                min="0"
                step="1"
                class="ai-input ai-range-input"
                data-env-debounce-key="recovery_seconds"
                value="${this._escapeHtml(recoveryValue)}"
              />
            </div>
          </div>
        </div>
      </div>
    `;
  }

_getAssetTimelineItems(attrs) {
    const items = [];

    const envEvents = Array.isArray(attrs.environment_events)
      ? attrs.environment_events
      : Array.isArray(this._readPath(attrs, "history.environment_events"))
        ? this._readPath(attrs, "history.environment_events")
        : [];

    let previousRoomSnapshot = null;
    envEvents.slice(-40).forEach((evt) => {
      const eventDetails = this._normalizeEnvironmentEventDetails(evt, previousRoomSnapshot);
      const currentSnapshot =
        eventDetails?.room_environment && typeof eventDetails.room_environment === "object"
          ? eventDetails.room_environment
          : null;
      if (currentSnapshot) {
        previousRoomSnapshot = currentSnapshot;
      }

      const changedCount = Array.isArray(eventDetails?.changed_fields)
        ? eventDetails.changed_fields.length
        : 0;

      const isRiskTransition = String(evt?.type || "").toLowerCase() === "environment_risk_state_changed";
      const transitionToState = evt?.new_state || evt?.risk_state || evt?.state || "amber";

      items.push({
        kind: isRiskTransition ? "risk" : "environment",
        color: this._timelineColorFromState(transitionToState),
        source: "environment_event",
        title: evt?.title
          || (evt?.type === "room_environment_changed"
            ? "Room environment changed"
            : evt?.type === "environment_risk_state_changed"
              ? "Risk state changed"
              : "Environment event"),
        meta: this._formatLocalDateTime(evt?.occurred_at || evt?.timestamp || attrs.updated_at),
        _ts: new Date(evt?.occurred_at || evt?.timestamp || attrs.updated_at).getTime(),
        copy:
          evt?.message
          || evt?.reason
          || evt?.summary
          || (changedCount > 0
            ? `${changedCount} room/environment field(s) changed`
            : "Environment condition recorded"),
        details: eventDetails,
      });
    });

    const custodyEvents = Array.isArray(attrs.custody_events)
      ? attrs.custody_events
      : Array.isArray(this._readPath(attrs, "history.custody_events"))
        ? this._readPath(attrs, "history.custody_events")
        : [];

    custodyEvents.slice(-8).forEach((evt) => {
      items.push({
        kind: "custody",
        color: "amber",
        source: "custody_event",
        title: evt?.title || evt?.status || "Custody event",
        meta: this._formatLocalDateTime(evt?.effective_at || evt?.timestamp || attrs.updated_at),
        _ts: new Date(evt?.occurred_at || evt?.timestamp || attrs.updated_at).getTime(),
        copy: evt?.notes || evt?.message || evt?.holder || "Custody updated",
        details: evt && typeof evt === "object" ? evt : { raw: evt },
      });
    });

    const pushAuditEntry = (timestampValue, userValue, actionValue, rawValue, detailsValue = {}) => {
      let readableAction = this._titleCase(
        String(actionValue || "").replaceAll("_", " ")
      );

      const docMatch = String(actionValue || "").match(/\(([a-f0-9-]+)\)/i);

      if (docMatch && Array.isArray(attrs.documents)) {
        const documentId = docMatch[1].toLowerCase();

        const doc = attrs.documents.find(
          (d) => String(d?.document_id || "").toLowerCase() === documentId
        );

        if (doc) {
          const type = doc.type
            ? this._titleCase(String(doc.type).replaceAll("_", " "))
            : "Document";

          const title = doc.title || "";

          readableAction = title
            ? `Uploaded "${title}" (${type})`
            : `Uploaded ${type}`;
        } else {
          readableAction = "Document uploaded";
        }
      }

      let kind = "audit";
      let color = "neutral";

      if (/(upload_document|attach_document|update_document_metadata|delete_document|add_physical_document_location)/i.test(String(actionValue || ""))) {
        kind = "documents";
        color = "green";
      } else if (/set_environment_requirements/i.test(String(actionValue || ""))) {
        kind = "environment";
        color = "amber";
      } else if (/(set_custody_status|record_loan_out|record_loan_in)/i.test(String(actionValue || ""))) {
        kind = "custody";
        color = "amber";
      }

      items.push({
        kind,
        color,
        source: "audit",
        title: userValue
          ? `${readableAction} by ${userValue}`
          : (readableAction || "Audit event"),
        meta: this._formatLocalDateTime(timestampValue || attrs.updated_at || attrs.created_at),
        _ts: new Date(timestampValue || attrs.updated_at || attrs.created_at).getTime(),
        copy: rawValue || String(actionValue || ""),
        details: {
          timestamp: timestampValue || attrs.updated_at || attrs.created_at,
          user: userValue || "",
          action: String(actionValue || ""),
          raw: rawValue || String(actionValue || ""),
          inferred_kind: kind,
          ...(detailsValue && typeof detailsValue === "object" ? detailsValue : {}),
        },
      });
    };

    const auditEvents = Array.isArray(attrs.audit_log)
      ? attrs.audit_log
      : Array.isArray(this._readPath(attrs, "history.audit_log"))
        ? this._readPath(attrs, "history.audit_log")
        : [];

    let previousEnvironmentRequirements = null;

    const maybeBackfillEnvironmentChanges = (actionValue, detailsValue) => {
      if (!detailsValue || typeof detailsValue !== "object") return detailsValue;

      const actionText = String(actionValue || "").toLowerCase();
      if (!actionText.includes("set_environment_requirements")) return detailsValue;

      const currentRequirements = detailsValue.environment_requirements;
      if (!currentRequirements || typeof currentRequirements !== "object") return detailsValue;

      const hasFieldChanges = detailsValue.field_changes && typeof detailsValue.field_changes === "object"
        && Object.keys(detailsValue.field_changes).length > 0;

      if (!hasFieldChanges && previousEnvironmentRequirements && typeof previousEnvironmentRequirements === "object") {
        const derivedFieldChanges = this._buildAuditFieldChanges(previousEnvironmentRequirements, currentRequirements);
        if (Object.keys(derivedFieldChanges).length > 0) {
          detailsValue.field_changes = derivedFieldChanges;
          detailsValue.changed_fields = Object.keys(derivedFieldChanges);
        }
      }

      previousEnvironmentRequirements = currentRequirements;
      return detailsValue;
    };

    if (auditEvents.length) {
      auditEvents.slice(-20).forEach((evt) => {
        const timestampValue = evt?.timestamp || evt?.occurred_at || attrs.updated_at;
        const userValue = String(evt?.actor || evt?.user || "");
        const detailsValue = maybeBackfillEnvironmentChanges(
          evt?.action || evt?.message || "",
          evt?.details && typeof evt.details === "object" ? { ...evt.details } : {}
        );
        const raw = String(evt?.action || evt?.message || "").trim();
        if (!raw) return;

        const structuredEntryPattern = /^\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}\s+â€”\s+/;
        if (!structuredEntryPattern.test(raw)) {
          pushAuditEntry(
            timestampValue,
            userValue,
            raw,
            raw,
            detailsValue
          );
          return;
        }

        const parts = raw
          .split(/(?=\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})/)
          .map((p) => p.trim().replace(/^,+|,+$/g, ""))
          .filter((p) => p);

        if (!parts.length) {
          pushAuditEntry(
            timestampValue,
            userValue,
            raw,
            raw,
            detailsValue
          );
          return;
        }

        parts.forEach((entry) => {
          const cleaned = entry.trim().replace(/^,+|,+$/g, "");

          const match = cleaned.match(
            /^(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})\s+â€”\s+(.*?)\s+â†’\s+(.*)$/
          );

          if (match) {
            const timestamp = match[1];
            const user = match[2];
            const action = String(match[3] || "").trim().replace(/^,+|,+$/g, "");
            pushAuditEntry(timestamp, user, action, cleaned, detailsValue);
          } else {
            pushAuditEntry(
              timestampValue,
              "",
              cleaned,
              cleaned,
              detailsValue
            );
          }
        });
      });
    } else if (attrs.audit_summary) {
      const raw = String(attrs.audit_summary).trim();

      const parts = raw
        .split(/(?=\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})/)
        .map((p) => p.trim().replace(/^,+|,+$/g, ""))
        .filter((p) => p);

      parts.forEach((entry) => {
        const cleaned = entry.trim().replace(/^,+|,+$/g, "");

        const match = cleaned.match(
          /^(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})\s+â€”\s+(.*?)\s+â†’\s+(.*)$/
        );

        if (match) {
          const timestamp = match[1];
          const user = match[2];
          const action = String(match[3] || "").trim().replace(/^,+|,+$/g, "");
          pushAuditEntry(timestamp, user, action, cleaned);
        } else {
          pushAuditEntry(
            attrs.updated_at || attrs.created_at,
            "",
            cleaned,
            cleaned
          );
        }
      });
    }

    if (!items.some((entry) => String(entry?.kind || "").toLowerCase() === "custody")) {
      const loans = Array.isArray(attrs?.loans) ? attrs.loans : [];
      const loanTimeline = loans
        .filter((loan) => loan && typeof loan === "object")
        .map((loan) => {
          const direction = String(loan.direction || "").toLowerCase();
          const state = String(loan.state || "").toLowerCase();
          const counterparty = String(loan.counterparty || "").trim();

          if (direction === "out" && state === "active") {
            const ts = loan.start_date || loan.recorded_at || attrs?.updated_at || attrs?.created_at || null;
            return {
              kind: "custody",
              color: "amber",
              source: "loan_snapshot",
              title: "Loan out recorded",
              meta: this._formatLocalDateTime(ts),
              _ts: new Date(ts || 0).getTime(),
              copy: counterparty ? `Loaned to ${counterparty}` : "Asset loaned out",
              details: {
                loan_id: loan.loan_id,
                counterparty: loan.counterparty,
                start_date: loan.start_date,
                expected_return_date: loan.expected_return_date,
                state: loan.state,
              },
            };
          }

          if (direction === "out" && state === "returned") {
            const ts = loan.actual_return_date || loan.closed_at || loan.recorded_at || attrs?.updated_at || attrs?.created_at || null;
            return {
              kind: "custody",
              color: "amber",
              source: "loan_snapshot",
              title: "Loan in recorded",
              meta: this._formatLocalDateTime(ts),
              _ts: new Date(ts || 0).getTime(),
              copy: counterparty ? `Returned from ${counterparty}` : "Asset returned",
              details: {
                loan_id: loan.loan_id,
                counterparty: loan.counterparty,
                actual_return_date: loan.actual_return_date,
                return_location_detail: loan.return_location_detail,
                return_notes: loan.return_notes,
                state: loan.state,
              },
            };
          }

          return null;
        })
        .filter((entry) => !!entry);

      if (loanTimeline.length) {
        items.push(...loanTimeline);
      }
    }

    if (!items.some((entry) => String(entry?.kind || "").toLowerCase() === "custody")) {
      const custody = attrs?.custody && typeof attrs.custody === "object"
        ? attrs.custody
        : {};
      const custodyStatus = String(attrs?.custody_status || custody?.status || "").trim();
      const holder = String(attrs?.holder || custody?.holder || custody?.owner || "").trim();
      const locationDetail = String(custody?.location_detail || custody?.location || attrs?.location_detail || "").trim();
      const effectiveAt = custody?.effective_at || attrs?.updated_at || attrs?.created_at || null;

      if (custodyStatus || holder || locationDetail) {
        items.push({
          kind: "custody",
          color: "amber",
          source: "snapshot",
          title: "Custody status snapshot",
          meta: this._formatLocalDateTime(effectiveAt),
          _ts: new Date(effectiveAt || 0).getTime(),
          copy: custodyStatus ? this._titleCase(custodyStatus.replaceAll("_", " ")) : "Custody state",
          details: {
            status: custodyStatus,
            holder,
            location_detail: locationDetail,
            effective_at: effectiveAt,
          },
        });
      }
    }

    return items
      .sort((a, b) => (b._ts || 0) - (a._ts || 0))
      .slice(0, 16);
  }

  _resolvePhysicalDocumentLocation(doc, physicalLocations) {
    const metadata = doc?.metadata && typeof doc.metadata === "object"
      ? doc.metadata
      : {};

    const metadataLocation = metadata.physical_location;
    if (metadataLocation) {
      return {
        location: metadataLocation,
        notes: metadata.physical_notes || "",
        recorded_at: metadata.physical_recorded_at || null,
        recorded_by: metadata.physical_recorded_by || null,
      };
    }

    const direct =
      doc?.physical_location ||
      doc?.physical_document_location ||
      null;

    if (direct) return direct;

    const docId = doc?.document_id;
    if (!docId || !Array.isArray(physicalLocations)) return null;

    return physicalLocations.find((entry) =>
      entry?.document_id === docId ||
      entry?.provider_document_id === doc?.provider_document_id ||
      entry?.type === doc?.type
    ) || null;
  }

  _timelineColorFromState(value) {
    const state = String(value || "").toLowerCase();
    if (state.includes("red") || state.includes("critical")) return "red";
    if (state.includes("green") || state.includes("good")) return "green";
    return "amber";
  }

  _renderStructuredReadoutValue(value, emptyText = "â€”") {
    if (value === null || value === undefined || value === "") {
      return `<span class="ai-readout-muted">${this._escapeHtml(emptyText)}</span>`;
    }

    if (Array.isArray(value)) {
      const items = value
        .map((entry) => String(entry ?? "").trim())
        .filter(Boolean);

      if (!items.length) {
        return `<span class="ai-readout-muted">${this._escapeHtml(emptyText)}</span>`;
      }

      return `
        <ul class="ai-readout-bullets">
          ${items.map((item) => `<li>${this._escapeHtml(item)}</li>`).join("")}
        </ul>
      `;
    }

    if (typeof value === "object") {
      const entries = Object.entries(value || {});
      if (!entries.length) {
        return `<span class="ai-readout-muted">${this._escapeHtml(emptyText)}</span>`;
      }
      return `
        <div class="ai-readout-kv">
          ${entries.map(([key, rawVal]) => {
            let displayVal;
            if (Array.isArray(rawVal)) {
              displayVal = rawVal.length
                ? rawVal.map((item) => String(item ?? "")).join(", ")
                : "[]";
            } else if (rawVal && typeof rawVal === "object") {
              displayVal = JSON.stringify(rawVal);
            } else if (rawVal === null || rawVal === undefined || rawVal === "") {
              displayVal = "â€”";
            } else {
              displayVal = String(rawVal);
            }

            const keyLabel = this._titleCase(String(key).replaceAll("_", " "));

            return `
              <div class="ai-readout-kv-row">
                <div class="ai-readout-kv-key">${this._escapeHtml(keyLabel)}</div>
                <div class="ai-readout-kv-value">${this._escapeHtml(displayVal)}</div>
              </div>
            `;
          }).join("")}
        </div>
      `;
    }

    return this._escapeHtml(String(value));
  }

  _normalizeExposureRisk(value) {
    const fallback = {
      level: "Unknown",
      reasons: [],
      azimuth: null,
      elevation: null,
    };

    if (value === null || value === undefined || value === "") {
      return fallback;
    }

    let parsed = value;
    if (typeof parsed === "string") {
      const raw = parsed.trim();
      if (!raw) return fallback;

      const normalizedJson = raw
        .replace(/([{,]\s*)'([^']+?)'\s*:/g, "$1\"$2\":")
        .replace(/:\s*'([^']*?)'/g, ': "$1"')
        .replace(/\bNone\b/g, "null")
        .replace(/\bTrue\b/g, "true")
        .replace(/\bFalse\b/g, "false");

      try {
        parsed = JSON.parse(normalizedJson);
      } catch (_err) {
        const level = raw.match(/['\"]?level['\"]?\s*:\s*['\"]?([^,'\"}\]]+)/i)?.[1] || "Unknown";
        const reasonsBlock = raw.match(/['\"]?reasons['\"]?\s*:\s*\[([^\]]*)\]/i)?.[1] || "";
        const reasons = reasonsBlock
          ? reasonsBlock
              .split(",")
              .map((item) => item.trim().replace(/^['\"]|['\"]$/g, ""))
              .filter(Boolean)
          : [];
        const azimuthRaw = raw.match(/['\"]?azimuth['\"]?\s*:\s*([-+]?\d*\.?\d+)/i)?.[1];
        const elevationRaw = raw.match(/['\"]?elevation['\"]?\s*:\s*([-+]?\d*\.?\d+)/i)?.[1];

        return {
          level,
          reasons,
          azimuth: azimuthRaw === undefined ? null : Number(azimuthRaw),
          elevation: elevationRaw === undefined ? null : Number(elevationRaw),
        };
      }
    }

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {
        ...fallback,
        level: String(parsed || fallback.level),
      };
    }

    const reasonsRaw = parsed.reasons;
    const reasons = Array.isArray(reasonsRaw)
      ? reasonsRaw.map((item) => String(item ?? "").trim()).filter(Boolean)
      : (typeof reasonsRaw === "string" && reasonsRaw.trim())
        ? [reasonsRaw.trim()]
        : [];

    const toNumberOrNull = (rawVal) => {
      const n = Number(rawVal);
      return Number.isFinite(n) ? n : null;
    };

    return {
      level: String(parsed.level ?? parsed.state ?? fallback.level),
      reasons,
      azimuth: toNumberOrNull(parsed.azimuth),
      elevation: toNumberOrNull(parsed.elevation),
    };
  }

  _renderExposureRiskReadout(exposureRisk) {
    const normalized = exposureRisk || this._normalizeExposureRisk(null);
    const levelText = this._titleCase(String(normalized.level || "Unknown").replaceAll("_", " ").toLowerCase());
    const reasons = Array.isArray(normalized.reasons) ? normalized.reasons : [];
    const azimuthText = normalized.azimuth === null ? "â€”" : `${Number(normalized.azimuth).toFixed(2)}Â°`;
    const elevationText = normalized.elevation === null ? "â€”" : `${Number(normalized.elevation).toFixed(2)}Â°`;

    return `
      <div class="ai-readout-kv">
        <div class="ai-readout-kv-row">
          <div class="ai-readout-kv-key">Level</div>
          <div class="ai-readout-kv-value">${this._escapeHtml(levelText)}</div>
        </div>
        <div class="ai-readout-kv-row">
          <div class="ai-readout-kv-key">Reasons</div>
          <div class="ai-readout-kv-value">
            ${reasons.length
              ? `<ul class="ai-readout-bullets">${reasons.map((item) => `<li>${this._escapeHtml(item)}</li>`).join("")}</ul>`
              : `<span class="ai-readout-muted">None</span>`}
          </div>
        </div>
        <div class="ai-readout-kv-row">
          <div class="ai-readout-kv-key">Azimuth</div>
          <div class="ai-readout-kv-value">${this._escapeHtml(azimuthText)}</div>
        </div>
        <div class="ai-readout-kv-row">
          <div class="ai-readout-kv-key">Elevation</div>
          <div class="ai-readout-kv-value">${this._escapeHtml(elevationText)}</div>
        </div>
      </div>
    `;
  }

  _deriveMeasureState(current, min, max) {
    const value = Number(current);
    const low = Number(min);
    const high = Number(max);

    if (Number.isNaN(value) || Number.isNaN(low) || Number.isNaN(high)) {
      return "warning";
    }
    if (value < low || value > high) {
      return "critical";
    }

    return "green";
  }

  _computeRangePercent(current, min, max) {
    const value = Number(current);
    const low = Number(min);
    const high = Number(max);

    if (Number.isNaN(value)) return 50;
    if (Number.isNaN(low) || Number.isNaN(high) || high <= low) return 50;

    const raw = ((value - low) / (high - low)) * 100;
    return Math.max(0, Math.min(100, raw));
  }

  _readPath(obj, path) {
    if (!obj || !path) return undefined;
    return String(path)
      .split(".")
      .reduce((acc, part) => (acc && typeof acc === "object" ? acc[part] : undefined), obj);
  }


  /* ===========================
     NAVIGATION
  =========================== */

  _attachNavigationHandlers() {
    console.log("ATTACH HANDLERS RUN");

    // Room click
    this.querySelectorAll(".ai-room-click").forEach((el) => {
      el.onclick = () => {
        const roomId = el.dataset.room;
        if (!roomId) return;
        const room = this._getRoomEntities().find(
          (r) => r.attributes?.area_id === roomId
        );
        const configured = room?.attributes?.configured === true;
        this._attemptNavigate(
          configured
            ? { type: "room", roomId }
            : { type: "room-config", roomId }
        );
      };
    });

    // Floor click
    this.querySelectorAll("[data-floor]").forEach((el) => {
      el.onclick = () => {
        const floorName = el.getAttribute("data-floor");
        if (!floorName) return;
        this._attemptNavigate({ type: "floor", floorName });
      };
    });

    this.querySelectorAll("[data-room-config]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();

        const roomId = el.getAttribute("data-room-config");
        if (!roomId) return;

        console.log("ROOM CONFIG CLICK", roomId);

        this._attemptNavigate({ type: "room-config", roomId });
      };
    });

    // Add Asset Click (OPEN MODAL, NO NAVIGATION)
    this.querySelectorAll(".ai-fab").forEach((el) => {
      el.onclick = () => {
        this._openAddAssetDialog(this._view.roomId);
      };
    });

    this.querySelectorAll("[data-asset]").forEach((el) => {
      el.onclick = () => {
        const assetId = el.dataset.asset;
        this._attemptNavigate({ type: "asset-detail", assetId });
      };
    });

    // Back/button nav
    this.querySelectorAll("[data-nav='home']").forEach((el) => {
      el.onclick = () => {
        this._attemptNavigate({ type: "home" });
      };
    });

    // Breadcrumb room nav
    this.querySelectorAll("[data-nav-room]").forEach((el) => {
      el.onclick = () => {
        const roomId = el.getAttribute("data-nav-room");
        if (!roomId) return;
        this._attemptNavigate({ type: "room", roomId });
      };
    });

    // Edit / save / cancel / remove metric are now handled by the delegated
    // listener in _bindRoomConfigDelegation() (bound once in connectedCallback)
    // so they survive innerHTML replacement between pointerdown and click.

    // ==========================================================
    // ASSET DETAIL: overflow, dirty tracking, and save
    // ==========================================================
    this.querySelectorAll("[data-asset-overflow]").forEach((wrap) => {
      const button = wrap.querySelector(".ai-overflow-button");
      if (button) {
        button.onclick = (e) => {
          e.stopPropagation();
          wrap.classList.toggle("open");
        };
      }
    });

    this.querySelectorAll("[data-asset-info-watch]").forEach((el) => {
      const refresh = () => this._refreshAssetInfoSaveState();
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("value-changed", refresh);
    });

    this.querySelectorAll("[data-asset-info-save]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-info-save");
        if (!assetId) return;
        await this._saveAssetInfoBlock(assetId);
      };
    });

    this.querySelectorAll("[data-asset-header-save]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-header-save");
        if (!assetId) return;
        await this._saveAssetHeaderBlock(assetId);
      };
    });

    this.querySelectorAll("[data-asset-header-cancel]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-header-cancel");
        if (!assetId) return;
        this._dropAssetDraftKeys(assetId, this._assetHeaderDraftKeys());
        this._render();
      };
    });

    this.querySelectorAll("[data-asset-info-cancel]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-info-cancel");
        if (!assetId) return;
        this._dropAssetDraftKeys(assetId, this._assetInfoDraftKeys());
        this._render();
      };
    });

    this.querySelectorAll("[data-asset-financial-save]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-financial-save");
        if (!assetId) return;
        await this._saveAssetFinancialBlock(assetId);
      };
    });

    this.querySelectorAll("[data-asset-financial-cancel]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-financial-cancel");
        if (!assetId) return;
        this._dropAssetDraftKeys(assetId, this._assetFinancialDraftKeys());
        this._render();
      };
    });

    this.querySelectorAll("[data-env-input]").forEach((el) => {
      const assetId = this._view?.type === "asset-detail" ? this._view.assetId : null;
      if (!assetId) return;

      const applyDraftValue = () => {
        const categoryKey = el.getAttribute("data-env-category");
        const metricKey = el.getAttribute("data-env-metric");
        const boundKey = el.getAttribute("data-env-input");
        if (!categoryKey || !metricKey || !boundKey) return;

        this._updateAssetEnvironmentDraftField(
          assetId,
          categoryKey,
          metricKey,
          boundKey,
          el.value
        );

        this._refreshAssetEnvironmentInputErrors(assetId);
      };

      const handleInput = () => {
        applyDraftValue();
        this._refreshAssetEnvironmentSaveState();
      };

      const handleChange = () => {
        applyDraftValue();
      };

      el.addEventListener("input", handleInput);
      el.addEventListener("change", handleChange);
    });

    this.querySelectorAll("[data-env-debounce-key]").forEach((el) => {
      const assetId = this._view?.type === "asset-detail" ? this._view.assetId : null;
      if (!assetId) return;

      const applyDraftValue = () => {
        const debounceKey = el.getAttribute("data-env-debounce-key");
        if (!debounceKey) return;
        this._updateAssetEnvironmentDebounceField(assetId, debounceKey, el.value);
      };

      const handleInput = () => {
        applyDraftValue();
        this._refreshAssetEnvironmentSaveState();
      };

      const handleChange = () => {
        applyDraftValue();
      };

      el.addEventListener("input", handleInput);
      el.addEventListener("change", handleChange);
    });

    this.querySelectorAll("[data-asset-environment-save]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-environment-save");
        if (!assetId) return;
        await this._saveAssetEnvironmentLimits(assetId);
      };
    });

    this.querySelectorAll("[data-asset-environment-cancel]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-environment-cancel");
        if (!assetId) return;
        this._clearAssetEnvironmentDraft(assetId);
        this._render();
      };
    });

    this.querySelectorAll("[data-asset-delete]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = el.getAttribute("data-asset-delete");
        if (!assetId) return;

        const assetEntity = this._getAssetEntities().find(
          (a) => a.attributes?.asset_id === assetId
        );
        const assetAttrs = assetEntity?.attributes || {};
        const assetName = this._displayAssetName(assetEntity || { attributes: { asset_id: assetId } });
        const roomAreaId =
          this._resolveAssetRoomAreaId(assetAttrs, assetEntity?.entity_id);

        const confirmed = await this._showConfirmDialog(
          `Are you sure you want to delete the asset \"${assetName}\"? This action cannot be undone.`,
          {
            title: "Delete asset",
            confirmText: this._hass?.localize?.("ui.common.delete") || "Delete",
            dismissText: this._hass?.localize?.("ui.common.cancel") || "Cancel",
            destructive: true,
          }
        );
        if (!confirmed) return;

        try {
          this._discardAssetDetailDrafts(assetId);
          await this._callService("asset_intelligence", "delete_asset", {
            asset_id: assetId,
          });
          await this._load();
          await this._attemptNavigate(
            roomAreaId
              ? { type: "room", roomId: roomAreaId }
              : { type: "home" }
          );
        } catch (err) {
          console.error("Failed to delete asset", err);
          alert("Failed to delete asset");
        }
      };
    });

    this.querySelectorAll(".ai-timeline-item").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();

        const index = Number(el.getAttribute("data-history-index"));
        if (Number.isNaN(index)) return;
        const item = this._currentHistory?.[index];
        if (!item) return;

        this._showActivityItemDialog(item);
      };
    });

    this.querySelectorAll("[data-asset-history-filter]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const nextFilter = String(el.getAttribute("data-asset-history-filter") || "all").toLowerCase();
        this._assetHistoryFilter = nextFilter || "all";
        this._render();
      };
    });

    this.querySelectorAll("[data-room-history-filter]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const roomId = String(el.getAttribute("data-room-history-room") || "").trim();
        if (!roomId) return;

        const nextFilter = String(el.getAttribute("data-room-history-filter") || "all").toLowerCase();
        this._roomHistoryFilterByRoom[roomId] = nextFilter || "all";

        if (nextFilter !== "asset") {
          this._roomHistoryAssetFilterByRoom[roomId] = "all";
        }

        this._render();
      };
    });

    this.querySelectorAll("[data-room-history-asset]").forEach((el) => {
      el.onchange = (e) => {
        e.preventDefault();
        e.stopPropagation();

        const roomId = String(el.getAttribute("data-room-history-room") || "").trim();
        if (!roomId) return;

        const nextAssetId = String(e?.target?.value || "all").trim() || "all";
        this._roomHistoryFilterByRoom[roomId] = "asset";
        this._roomHistoryAssetFilterByRoom[roomId] = nextAssetId;
        this._render();
      };
    });

    this.querySelectorAll("[data-custody-action]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();

        const assetId = String(el.getAttribute("data-custody-asset") || "").trim();
        const action = String(el.getAttribute("data-custody-action") || "").trim();
        if (!assetId || !action) return;

        this._openCustodyWorkflowDialog(assetId, action);
      };
    });

    this.querySelectorAll("[data-asset-upload-document]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = String(el.getAttribute("data-asset-upload-document") || "").trim();
        if (!assetId) return;
        this._openDocumentWorkflowDialog(assetId, "upload");
      };
    });

    this.querySelectorAll("[data-asset-attach-document]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const assetId = String(el.getAttribute("data-asset-attach-document") || "").trim();
        if (!assetId) return;
        this._openDocumentWorkflowDialog(assetId, "attach");
      };
    });

    this.querySelectorAll("[data-doc-view]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const docId = String(el.getAttribute("data-doc-view") || "").trim();
        const assetId = this._view?.type === "asset-detail" ? this._view.assetId : "";
        if (!assetId || !docId) return;
        this._viewDocument(assetId, docId);
      };
    });

    this.querySelectorAll("[data-doc-edit]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const docId = String(el.getAttribute("data-doc-edit") || "").trim();
        const assetId = this._view?.type === "asset-detail" ? this._view.assetId : "";
        if (!assetId || !docId) return;
        this._editDocumentMetadata(assetId, docId);
      };
    });

    this.querySelectorAll("[data-doc-add-physical]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const docId = String(el.getAttribute("data-doc-add-physical") || "").trim();
        const assetId = this._view?.type === "asset-detail" ? this._view.assetId : "";
        if (!assetId || !docId) return;
        this._openPhysicalDocumentDialog(assetId, docId);
      };
    });

    this.querySelectorAll("[data-doc-delete]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const docId = String(el.getAttribute("data-doc-delete") || "").trim();
        const assetId = this._view?.type === "asset-detail" ? this._view.assetId : "";
        if (!assetId || !docId) return;
        this._deleteDocument(assetId, docId);
      };
    });

    // âœ… SHOW ALL TOGGLE
    this.querySelectorAll("[data-show-all-sensors]").forEach((el) => {
      // âœ… prevent duplicate binding
      if (el.dataset.bound === "true") {
        return;
      }

      el.addEventListener("change", (e) => {
        const fieldPath = el.getAttribute("data-show-all-sensors");
        if (!fieldPath) return;

        // âœ… update state
        this._showAllSensorsByMetric[fieldPath] = e.target.checked === true;

        // âœ… find the picker for this metric
        const picker = this.querySelector(
          `ha-entity-picker[data-metric="${fieldPath}"]`
        );

        if (picker) {
          // âœ… force refresh and recalc filtering state
          picker.dataset.initialized = "false";
          if (typeof picker.requestUpdate === "function") {
            try { picker.requestUpdate(); } catch (e) {}
          }
        }

        this._applyHassToHAElements();
      });

      el.dataset.bound = "true";
    });

    this.querySelectorAll("ha-entity-picker[data-metric]").forEach((picker) => {
      if (picker.dataset.boundPicker === "true") {
        return;
      }

      const syncDraft = (event) => {
        const fieldPath = picker.dataset.metric;
        if (!fieldPath) return;

        const selected =
          event?.detail?.value ??
          event?.target?.value ??
          picker?.value ??
          picker?.entityId ??
          "";

        if (!this._draftMetrics[fieldPath]) {
          this._draftMetrics[fieldPath] = {};
        }

        this._draftMetrics[fieldPath].entity = selected;
      };

      picker.addEventListener("value-changed", syncDraft);
      picker.addEventListener("change", syncDraft);
      picker.addEventListener("input", syncDraft);
      picker.dataset.boundPicker = "true";
    });

    this.querySelectorAll(".ai-overflow-button").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const parent = btn.closest(".ai-overflow");
        parent.classList.toggle("open");
      };
    });

    this.querySelectorAll("[data-asset-measure]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const assetId = String(el.getAttribute("data-asset-measure") || "").trim();
        if (!assetId) return;

        try {
          await this._callService("asset_intelligence", "start_measurement", { asset_id: assetId });
          await this._load();
          await this._ensureAssetHistoryLoaded(assetId, true);
          this._render();
        } catch (err) {
          console.error("Failed to start measurement", err);
          alert("Failed to start measurement");
        }
      };
    });

    this.querySelectorAll("[data-asset-stop-measure]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const assetId = String(el.getAttribute("data-asset-stop-measure") || "").trim();
        if (!assetId) return;

        try {
          await this._callService("asset_intelligence", "stop_measurement", { asset_id: assetId });
          await this._load();
          await this._ensureAssetHistoryLoaded(assetId, true);
          this._render();
        } catch (err) {
          console.error("Failed to stop measurement", err);
          alert("Failed to stop measurement");
        }
      };
    });


    // ADD WINDOW
    this.querySelectorAll("[data-add-window]").forEach((el) => {
      el.onclick = (e) => {
        e.stopPropagation();

        const room = this._getRoomEntities().find(
          (r) => r.attributes?.area_id === this._view.roomId
        );
        if (!room) return;

        const windows = this._getDraftWindows(this._view.roomId, room);
        windows.push({
          direction: "",
          exposure: ""
        });

        this._draftWindows[this._view.roomId] = windows;
        this._editingWindowIndex = windows.length - 1;
        this._render();
      };
    });

    this.querySelectorAll("[data-asset-export]").forEach((el) => {
      el.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();

        const assetId = el.getAttribute("data-asset-export");
        if (!assetId) return;

        const asset = this._getAssetEntities().find(
          (a) => a.attributes?.asset_id === assetId
        );

        if (!asset) return;

        const blob = new Blob(
          [JSON.stringify(asset.attributes, null, 2)],
          { type: "application/json" }
        );

        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = `asset_${assetId}.json`;
        a.click();

        URL.revokeObjectURL(url);
      };
    });

    // Final Room Configuration Save (persist full payload)
    this.querySelectorAll("[data-save-room-config]").forEach((el) => {
      el.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const roomId = el.getAttribute("data-save-room-config");
        if (!roomId) return;

        const room = this._getRoomEntities().find(
          (r) => r.attributes?.area_id === roomId
        );
        if (!room) return;

        await this._saveRoomEnvironmentConfig(roomId, room);
      };
    });
  }

  async _ensureAssetHistoryLoaded(assetId, force = false) {
    const normalizedAssetId = String(assetId || "").trim();
    if (!normalizedAssetId || !this._hass) return;
    const cachedHistory = this._assetHistoryCache?.[normalizedAssetId] || null;
    const cacheLoadedAt = Number(cachedHistory?._loaded_at || 0);
    const historyCacheFresh = cacheLoadedAt > 0 && (Date.now() - cacheLoadedAt) < 15000;
    if (!force && cachedHistory && historyCacheFresh) return;
    if (this._assetHistoryLoading?.[normalizedAssetId]) return;

    this._assetHistoryLoading[normalizedAssetId] = true;
    try {
      const response = await this._callServiceWithResponse("asset_intelligence", "get_asset_history", {
        asset_id: normalizedAssetId,
        max_entries: 80,
      });

      this._assetHistoryCache[normalizedAssetId] = response && typeof response === "object"
        ? { ...response, _loaded_at: Date.now() }
        : { all: [], by_filter: { all: [] } };
    } catch (err) {
      console.error("Failed to load asset history", err);
      this._assetHistoryCache[normalizedAssetId] = { all: [], by_filter: { all: [] }, _loaded_at: Date.now() };
    } finally {
      delete this._assetHistoryLoading[normalizedAssetId];
      if (this._view?.type === "asset-detail" && this._view?.assetId === normalizedAssetId) {
        this._render();
      }
    }
  }

    /* ===========================
    ASSET CREATION
    =========================== */

    async _handleCreateAsset(dialog) {
      const draft = this._assetDraft;
      const rawName = String(draft?.name || "").trim();

      if (!rawName) {
        alert("Asset name is required");
        return;
      }
      if (!draft.asset_type) {
        alert("Asset type is required");
        return;
      }


      if (this._isDuplicateAssetName(rawName)) {
        alert("An asset with that name already exists. Please choose a different name.");
        return;
      }

      const assetId = this._generateUniqueAssetIdFromName(rawName);
      if (!assetId) {
        alert("Unable to generate a valid Asset ID from the name.");
        return;
      }

      // âœ… Step 1 â€” Create asset (ONLY critical step)
      let assetCreated = false;

      const selectedLabels = Array.isArray(draft?.label_ids)
        ? draft.label_ids.filter((label) => typeof label === "string" && label.trim())
        : [];
      const fallbackDefaultLabels = this._getDefaultLabelIds();
      const effectiveLabels = draft?.labels_touched
        ? selectedLabels
        : (selectedLabels.length ? selectedLabels : fallbackDefaultLabels);

      const addAssetPayload = {
        asset_id: assetId,
        name: rawName,
        asset_type: draft.asset_type,
        area_id: draft.area_id,
      };

      // Preserve backend default-label fallback when the user did not touch labels
      // and the UI has not yet resolved defaults. If labels were touched, always send
      // explicit intent (including an empty list when user cleared all labels).
      if (draft?.labels_touched || effectiveLabels.length) {
        addAssetPayload.labels = effectiveLabels;
      }

      try {
        await this._callService("asset_intelligence", "add_asset", addAssetPayload);

        assetCreated = true;

      } catch (err) {
        console.error("Create asset failed", err);
        alert("Failed to create asset");
        return; // âœ… STOP â€” this is the only real failure case
      }


      // âœ… Step 2 â€” Link device (non-critical)
      if (draft.device_id) {
        try {
          await this._callService("asset_intelligence", "link_to_device", {
            asset_id: assetId,
            device_id: draft.device_id
          });
        } catch (linkErr) {
          console.warn("Device link failed (non-fatal)", linkErr);
        }
      }


      // âœ… Step 3 â€” Reload UI and wait for room projection to settle
      try {
        await this._waitForAssetVisibleInRoom(assetId, draft.area_id || null);
      } catch (loadErr) {
        console.warn("Reload failed (non-fatal)", loadErr);
      }


      // âœ… Step 4 â€” Close dialog
      dialog.remove();

    }


  /* ===========================
  HELPERS
  =========================== */

  _getRoomEntities() {
    const roomEntities = Object.values(this._hass.states || {}).filter((e) =>
      e.entity_id.startsWith("sensor.asset_intelligence_") &&
      e.entity_id.endsWith("_environment")
    );

    const byArea = new Map();
    roomEntities.forEach((entity) => {
      const areaId = entity?.attributes?.area_id;
      if (areaId) byArea.set(areaId, entity);
    });

    const normalizedAreas = Array.isArray(this._areas) ? this._areas : [];
    return normalizedAreas.map((area) => {
      const areaId = area?.area_id;
      const live = byArea.get(areaId);
      const roomConfig = this._roomConfig?.[areaId];
      const hasRoomConfig = !!roomConfig;

      if (live) {
        const attrs = { ...(live.attributes || {}) };
        attrs.area_id = areaId;
        attrs.configured = attrs.configured === true || hasRoomConfig;
        attrs.image = attrs.image || area?.picture || null;
        return {
          ...live,
          attributes: attrs,
        };
      }

      return {
        entity_id: `sensor.asset_intelligence_${areaId}_environment`,
        state: "STALE",
        attributes: {
          area_id: areaId,
          configured: hasRoomConfig,
          climate: {},
          light: {},
          air_quality: {},
          particulates: {},
          biological: {},
          safety: {},
          structural: {},
          context: {},
          control_context: {},
          external_environment: {},
          windows: Array.isArray(roomConfig?.windows) ? roomConfig.windows : [],
          confidence: "STALE",
          last_updated: null,
          source_status: { details: {} },
          image: area?.picture || null,
        },
      };
    });
  }

  _getAssetEntities() {
    return Object.values(this._hass.states || {}).filter(e => {
      if (!e || !e.entity_id || !e.attributes) return false;

      const attrs = e.attributes;

      // âœ… Must be an asset
      if (attrs.asset_id === undefined) return false;

      // âœ… EXCLUDE derived / projection entities

      // Filter out "At Risk" style entities by name
      const name = (attrs.friendly_name || attrs.name || "").toLowerCase();
      if (name.includes("at risk")) return false;

      // Filter out risk/state projection entities
      if (attrs.entity_type === "risk") return false;
      if (attrs.entity_type === "projection") return false;

      // Optional: exclude by entity_id pattern if you use naming conventions
      if (e.entity_id.includes("_risk")) return false;
      if (e.entity_id.includes("_projection")) return false;

      return true;
    });
  }

  _resolveAssetRoomAreaId(attrs, entityId = null) {
    if (!attrs || typeof attrs !== "object") return null;
    const fromProjection = (
      attrs.room_area_id ||
      this._readPath(attrs, "room_environment.area_id")
    );
    if (fromProjection) return fromProjection;

    if (entityId) {
      const registryAreaId = this._getAreaIdForEntity(entityId);
      if (registryAreaId) return registryAreaId;
    }

    return null;
  }

  _normalizeLabelList(value) {
    if (!Array.isArray(value)) return [];
    const normalized = value
      .map((item) => String(item || "").trim())
      .filter((item) => !!item);
    return Array.from(new Set(normalized)).sort((a, b) => a.localeCompare(b));
  }

  _normalizeComparableText(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "object") {
      try {
        return JSON.stringify(value);
      } catch (err) {
        return "";
      }
    }
    return String(value);
  }

  _getDeviceForAsset(assetId) {
    const normalizedAssetId = String(assetId || "").trim();
    if (!normalizedAssetId) return null;

    return (this._deviceRegistry || []).find((device) => {
      const identifiers = Array.isArray(device?.identifiers) ? device.identifiers : [];
      return identifiers.some((identifier) => {
        if (!Array.isArray(identifier) || identifier.length < 2) return false;
        return (
          String(identifier[0] || "") === "asset_intelligence"
          && String(identifier[1] || "") === normalizedAssetId
        );
      });
    }) || null;
  }

  _getDeviceMetadataForAsset(assetId, attrs = {}, entityId = null) {
    const device = this._getDeviceForAsset(assetId);
    const areaId =
      device?.area_id ||
      this._resolveAssetRoomAreaId(attrs, entityId) ||
      "";

    let labels = this._normalizeLabelList(device?.labels);
    const validLabelIds = new Set(
      (this._labelRegistry || [])
        .map((entry) => String(entry?.label_id || "").trim())
        .filter((labelId) => !!labelId)
    );
    if (validLabelIds.size) {
      labels = labels.filter((labelId) => validLabelIds.has(labelId));
    }

    return {
      area_id: areaId,
      labels,
    };
  }

  _getAssetsForFloor(assetEntities, floorName, areaMap, floorMap) {
    return assetEntities.filter((entity) => {
      const attrs = entity.attributes || {};
      const roomAreaId = this._resolveAssetRoomAreaId(attrs, entity.entity_id);
      if (!roomAreaId) return floorName === "No Floor";

      const area = areaMap[roomAreaId];
      const floorId = area?.floor_id || null;
      const derivedFloorName =
        floorId && floorMap[floorId]
          ? floorMap[floorId].name
          : "No Floor";

      return derivedFloorName === floorName;
    });
  }

  _countAssetsForRoom(assetEntities, areaId) {
    return assetEntities.filter((entity) => {
      const attrs = entity.attributes || {};
      const assetRoom = this._resolveAssetRoomAreaId(attrs, entity.entity_id);
      return assetRoom === areaId;
    }).length;
  }

  _wait(ms) {
    return new Promise((resolve) => {
      setTimeout(resolve, ms);
    });
  }

  async _waitForAssetVisibleInRoom(assetId, roomId = null) {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await this._load();

      const created = this._getAssetEntities().find(
        (entity) => entity.attributes?.asset_id === assetId
      );

      if (created) {
        const resolvedRoomId = this._resolveAssetRoomAreaId(
          created.attributes || {},
          created.entity_id
        );

        if (!roomId || resolvedRoomId === roomId) {
          return true;
        }
      }

      await this._wait(250);
    }

    return false;
  }

  _countConfigured(details, prefix) {
    return Object.entries(details).filter(([key, value]) => {
      if (!String(key).startsWith(prefix)) return false;
      return value && typeof value === "object" && value.configured === true;
    }).length;
  }

  _getUnitForRoomField(roomEntity, fieldPath, fallbackUnit) {
    const details = roomEntity.attributes?.source_status?.details || {};

    const source = details[fieldPath];
    const entityId = source?.entity_id;

    if (entityId && this._hass?.states?.[entityId]) {
      const unit = this._hass.states[entityId].attributes?.unit_of_measurement;
      if (unit) return this._normalizeDisplayText(unit);
    }

    return this._normalizeDisplayText(fallbackUnit);
  }

  _normalizeDisplayText(value) {
    const raw = String(value ?? "");
    if (!raw) return raw;

    return raw
      .replaceAll("Ã‚Â°F", "degF")
      .replaceAll("Â°F", "degF")
      .replaceAll("Ã‚Âµg/mÃ‚Â³", "ug/m3")
      .replaceAll("Âµg/mÂ³", "ug/m3")
      .replaceAll("COÃ¢â€šâ€š", "CO2")
      .replaceAll("COâ‚‚", "CO2")
      .replaceAll("NOÃ¢â€šâ€š", "NO2")
      .replaceAll("NOâ‚‚", "NO2")
      .replaceAll("Ã¢â‚¬â€", "-")
      .replaceAll("â€”", "-")
      .replaceAll("Ã¢â‚¬Â¢", " | ")
      .replaceAll("â€¢", " | ")
      .replaceAll("Ã¢â€ â€™", "->")
      .replaceAll("â†’", "->")
      .replaceAll("Ã¢â‚¬Â¦", "...")
      .replaceAll("â€¦", "...");
  }

  _getAssetTypeOptions() {
    return [
      { value: "artwork", label: "Artwork" },
      { value: "rare_book", label: "Rare Book" },
      { value: "collectable", label: "Collectable" },
      { value: "electronics", label: "Electronics" },
      { value: "infrastructure", label: "Infrastructure" },
      { value: "furniture", label: "Furniture" },
      { value: "instrument", label: "Instrument" },
    ];
  }

  _getValueSeverity(fieldPath, value) {
    const num = Number(value);
    if (Number.isNaN(num)) return "normal";

    if (fieldPath === "air_quality.voc" && num > 100) return "high";

    return "normal";
  }

  _resolvePrimaryDocumentImage(attrs) {
    const documents = Array.isArray(attrs?.documents) ? attrs.documents : [];
    const assetId = String(attrs?.asset_id || "").trim();

    const imageDoc = documents.find((doc) => {
      const mime = String(doc?.mime_type || doc?.content_type || "").toLowerCase();
      const type = String(doc?.type || "").toLowerCase();
      const name = String(doc?.filename || doc?.name || doc?.title || "").toLowerCase();
      const url = this._resolveDocumentImageUrl(assetId, doc);

      const looksLikeImage =
        mime.startsWith("image/") ||
        type.includes("image") ||
        name.endsWith(".jpg") ||
        name.endsWith(".jpeg") ||
        name.endsWith(".png") ||
        name.endsWith(".webp");

      return looksLikeImage && !!url;
    });

    return (
      this._resolveDocumentImageUrl(assetId, imageDoc) ||
      null
    );
  }

  _resolveDocumentImageUrl(assetId, doc) {
    if (!doc || typeof doc !== "object") return null;

    const directUrl =
      doc?.thumbnail_url
      || doc?.preview_url
      || doc?.preview_uri
      || doc?.image_url
      || doc?.url
      || doc?.preview?.url
      || doc?.access?.preview?.url
      || null;
    if (directUrl) return directUrl;

    const normalizedAssetId = String(assetId || "").trim();
    const documentId = String(doc?.document_id || "").trim();
    if (!normalizedAssetId || !documentId) return null;

    return `/api/asset_intelligence/document/${encodeURIComponent(normalizedAssetId)}/${encodeURIComponent(documentId)}`;
  }

  _buildImageContainerAttrs(imageUrl) {
    if (!imageUrl) return "";

    const rawUrl = String(imageUrl);
    const escapedRawUrl = this._escapeHtml(rawUrl);
    const isProtectedApi = rawUrl.startsWith("/api/asset_intelligence/document/");

    if (!isProtectedApi) {
      return `style="background-image:url('${escapedRawUrl}')"`;
    }

    const cachedBlobUrl = this._protectedImageBlobCache?.[rawUrl];
    if (cachedBlobUrl) {
      return `style="background-image:url('${this._escapeHtml(cachedBlobUrl)}')" data-ai-image-url="${escapedRawUrl}"`;
    }

    return `data-ai-image-url="${escapedRawUrl}"`;
  }

  async _getAuthenticatedImageUrl(imageUrl) {
    if (!imageUrl) return null;

    // If it's an external URL or already a blob URL, return as-is
    if (String(imageUrl).startsWith("blob:") || String(imageUrl).startsWith("http")) {
      return imageUrl;
    }

    // If it's a local protected API URL, fetch it with authentication
    const isLocalProtectedApi = String(imageUrl).startsWith("/api/asset_intelligence/document/");
    if (!isLocalProtectedApi) {
      return imageUrl;
    }

    // Check cache first
    if (this._protectedImageBlobCache[imageUrl]) {
      return this._protectedImageBlobCache[imageUrl];
    }

    const token = this._hass?.auth?.data?.access_token;
    if (!token) {
      return null;
    }

    try {
      const response = await fetch(imageUrl, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        console.warn(`[AI] Failed to fetch protected image (${response.status}): ${imageUrl}`);
        return null;
      }

      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);

      // Cache it
      this._protectedImageBlobCache[imageUrl] = blobUrl;

      // Clean up after 1 hour
      setTimeout(() => {
        try {
          URL.revokeObjectURL(blobUrl);
          delete this._protectedImageBlobCache[imageUrl];
        } catch (e) {}
      }, 3600000);

      return blobUrl;
    } catch (err) {
      console.error(`[AI] Failed to fetch protected image: ${imageUrl}`, err);
      return null;
    }
  }

  _applyAuthenticatedImages() {
    // Find all elements with data-ai-image-url attribute
    const imageElements = this.querySelectorAll("[data-ai-image-url]");
    imageElements.forEach((el, index) => {
      const imageUrl = el.getAttribute("data-ai-image-url");
      if (!imageUrl) return;

      this._getAuthenticatedImageUrl(imageUrl).then((resolvedUrl) => {
        if (resolvedUrl) {
          if (el.dataset.aiResolvedImageUrl === resolvedUrl) return;
          el.style.backgroundImage = `url('${resolvedUrl}')`;
          el.dataset.aiResolvedImageUrl = resolvedUrl;
        }
      }).catch((err) => {
        console.error("Error applying authenticated image", err);
      });
    });
  }

  _primeProtectedImageBackgrounds() {
    const imageElements = this.querySelectorAll("[data-ai-image-url]");
    imageElements.forEach((el) => {
      const imageUrl = el.getAttribute("data-ai-image-url");
      if (!imageUrl) return;

      const cached = this._protectedImageBlobCache?.[imageUrl];
      if (!cached) return;

      if (el.dataset.aiResolvedImageUrl === cached) return;
      el.style.backgroundImage = `url('${cached}')`;
      el.dataset.aiResolvedImageUrl = cached;
    });
  }

  _scheduleRender(delayMs = 100) {
    try {
      if (this._renderDebounceTimer) {
        clearTimeout(this._renderDebounceTimer);
      }
    } catch (e) {}

    this._renderDebounceTimer = setTimeout(() => {
      this._renderDebounceTimer = null;
      if (this._renderQueued) return;
      this._renderQueued = true;

      requestAnimationFrame(() => {
        this._renderQueued = false;
        this._render();
      });
    }, Math.max(0, Number(delayMs) || 0));
  }

  _summarizeLabels(labels, assetType) {
    if (!Array.isArray(labels) || labels.length === 0) return "â€”";

    const normalizedType = String(assetType || "")
      .trim()
      .toLowerCase()
      .replaceAll("_", " ");

    const summary = labels
      .map((label) => this._titleCase(String(label).replaceAll("_", " ")))
      .filter((label) => {
        const normalizedLabel = String(label || "").trim().toLowerCase();
        return normalizedLabel && normalizedLabel !== normalizedType;
      })
      .slice(0, 3);

    return summary.length ? summary.join(" â€¢ ") : "â€”";
  }

  _renderBreadcrumb(items) {
      return `
        <div class="ai-breadcrumb">
          ${items.map((item, index) => {
            const isLast = index === items.length - 1;
            let content = this._escapeHtml(item.label);

            if (!isLast) {
              if (item.nav === "home") {
                content = `<button data-nav="home">${this._escapeHtml(item.label)}</button>`;
              } else if (item.roomId) {
                content = `<button data-nav-room="${this._escapeHtml(item.roomId)}">${this._escapeHtml(item.label)}</button>`;
              }
            }

            return `${content}${!isLast ? " &gt; " : ""}`;
          }).join("")}
        </div>
      `;
    }


  _displayRoomName(area, roomEntity) {
    if (area?.name) return area.name;

    const areaId = roomEntity.attributes?.area_id;
    if (areaId) {
      return this._titleCase(String(areaId).replaceAll("_", " "));
    }

    const friendly = roomEntity.attributes?.friendly_name || roomEntity.entity_id || "Unknown Room";
    return friendly
      .replace(/^Asset Intelligence\s+/i, "")
      .replace(/\s+Environment$/i, "")
      .trim();
  }

  _displayAssetName(assetEntity) {
    const attrs = assetEntity.attributes || {};
    return attrs.name || attrs.friendly_name || attrs.asset_id || assetEntity.entity_id;
  }

  _displayValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    if (typeof value === "object") return this._escapeHtml(JSON.stringify(value));
    return this._escapeHtml(this._normalizeDisplayText(value));
  }

  _formatMeasurementElapsed(startedAt) {
    if (!startedAt) return "00:00:00";
    const parsed = Date.parse(String(startedAt));
    if (Number.isNaN(parsed)) return "00:00:00";

    const elapsedMs = Math.max(0, Date.now() - parsed);
    const elapsedSeconds = Math.floor(elapsedMs / 1000);
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;

    const hh = String(hours).padStart(2, "0");
    const mm = String(minutes).padStart(2, "0");
    const ss = String(seconds).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
  }

  _syncMeasurementTimerUi() {
    const timerNodes = Array.from(this.querySelectorAll("[data-measurement-started-at]"));

    if (!timerNodes.length) {
      if (this._measurementTicker) {
        clearInterval(this._measurementTicker);
        this._measurementTicker = null;
      }
      return;
    }

    const updateTimerLabels = () => {
      timerNodes.forEach((node) => {
        const startedAt = node.getAttribute("data-measurement-started-at") || "";
        const elapsedEl = node.querySelector("[data-measurement-elapsed]");
        if (elapsedEl) {
          elapsedEl.textContent = this._formatMeasurementElapsed(startedAt);
        }
      });
    };

    updateTimerLabels();
    if (!this._measurementTicker) {
      this._measurementTicker = setInterval(updateTimerLabels, 1000);
    }
  }

  _getEntityRegistryEntry(entityId) {
    return (this._entityRegistry || []).find((entry) => entry.entity_id === entityId) || null;
  }

  _getCategoryConfig() {
    return {
      climate: {
        temperature: { entityDomain: "sensor", deviceClass: "temperature" },
        humidity: { entityDomain: "sensor", deviceClass: "humidity" },
        dew_point: { entityDomain: "sensor", deviceClass: "temperature" },
      },
      light: {
        lux: { entityDomain: "sensor", deviceClass: "illuminance" },
        uv: { entityDomain: "sensor", deviceClass: "" },
      },
      air_quality: {
        voc: { entityDomain: "sensor", deviceClass: "" },
        formaldehyde: { entityDomain: "sensor", deviceClass: "" },
        ozone: { entityDomain: "sensor", deviceClass: "" },
        no2: { entityDomain: "sensor", deviceClass: "" },
      },
      particulates: {
        pm2_5: { entityDomain: "sensor", deviceClass: "" },
        pm10: { entityDomain: "sensor", deviceClass: "" },
      },
      biological: {
        mold_index: { entityDomain: "sensor", deviceClass: "" },
      },
      safety: {
        leak: { entityDomain: "binary_sensor", deviceClass: "" },
      },
      structural: {
        pressure: { entityDomain: "sensor", deviceClass: "" },
        vibration: { entityDomain: "sensor", deviceClass: "" },
      },
      context: {
        noise: { entityDomain: "sensor", deviceClass: "" },
      },
      control_context: {
        co2: { entityDomain: "sensor", deviceClass: "carbon_dioxide" },
      },
      windows: {},
    };
  }

  _getDraftWindows(roomId, roomEntity) {
    if (roomId && Array.isArray(this._draftWindows?.[roomId])) {
      return JSON.parse(JSON.stringify(this._draftWindows[roomId]));
    }

    const liveWindows = Array.isArray(roomEntity?.attributes?.windows)
      ? roomEntity.attributes.windows
      : [];

    return JSON.parse(JSON.stringify(liveWindows));
  }


  _buildRoomEnvironmentConfig(roomId, roomEntity) {
    const environment_config = {};
    const categoryConfig = this._getCategoryConfig() || {};

    Object.entries(categoryConfig).forEach(([categoryName, metrics]) => {
      if (categoryName === "windows") {
        return; // âœ… windows are NOT part of environment_config
      }

      environment_config[categoryName] = {};

      Object.entries(metrics || {}).forEach(([metricKey]) => {
        const fieldPath = `${categoryName}.${metricKey}`;

        const draftEntity = this._draftMetrics[fieldPath]?.entity;
        const configuredEntity = this._getConfiguredSensorForMetric(roomEntity, fieldPath);

        const selectedEntity =
          draftEntity !== undefined
            ? draftEntity
            : configuredEntity || "";

        environment_config[categoryName][metricKey] = {
          source_entities: selectedEntity ? [selectedEntity] : [],
        };
      });
    });

    // âœ… DO NOT include windows here
    return environment_config;
  }

  async _saveRoomEnvironmentConfig(roomId, roomEntity) {
    if (!this.hass || !roomId || !roomEntity) {
      return;
    }

    const environment_config = this._buildRoomEnvironmentConfig(roomId, roomEntity);

    try {
      const windows = this._getDraftWindows(roomId, roomEntity);

      this._savingRoomId = roomId;
      this._render();

      await this._callService(
        "asset_intelligence",
        "set_room_environment",
        {
          area_id: roomId,
          environment_config,
          windows   // âœ… separate field
        }
      );



      // Clear all draft state after successful save
      this._draftMetrics = {};
      delete this._draftWindows[roomId];

      // Exit edit mode
      this._editingMetric = null;
      this._editingWindowIndex = null;

      // Reload storage + registries and re-render
      await this._load();

      await this._callService("persistent_notification", "create", {
        title: "Asset Intelligence",
        message: "Room configuration updated",
        notification_id: `asset_intelligence_room_config_${roomId}`
      });

    } catch (err) {
      console.error("Failed to save room environment config", err);
    }
    this._savingRoomId = null;
    this._render();
  }

  _getAreaIdForEntity(entityId) {
    const reg = this._getEntityRegistryEntry(entityId);
    if (!reg) return null;

    // Direct mapping
    if (reg.area_id) return reg.area_id;

    // Device mapping
    if (reg.device_id) {
      const device = (this._deviceRegistry || []).find(d => d.id === reg.device_id);
      if (device?.area_id) return device.area_id;
    }

    return null;
  }

  _displayValueWithUnit(value, unit) {
    if (value === null || value === undefined || value === "") return "-";
    if (typeof value === "object") return this._escapeHtml(JSON.stringify(value));

    const num = Number(value);
    let text;

    if (!Number.isNaN(num)) {
      // Smart rounding rules
      if (Math.abs(num) >= 100) {
        text = num.toFixed(0);
      } else if (Math.abs(num) >= 10) {
        text = num.toFixed(1);
      } else {
        text = num.toFixed(2);
      }
    } else {
      text = this._normalizeDisplayText(value).trim();
    }

    if (!text) return "-";

    const normalizedUnit = this._normalizeDisplayText(unit || "").trim();
    const needsSpace = /^[a-zA-Z]/.test(normalizedUnit);
    const formatted = normalizedUnit
      ? (needsSpace ? `${text} ${normalizedUnit}` : `${text}${normalizedUnit}`)
      : text;

    return this._escapeHtml(formatted);
  }

  _getEnvironmentConfig(roomEntity) {
    return roomEntity?.attributes?.environment_config || {};
  }


  _getAssetIcon(assetType, labels) {
    const type = String(assetType || "").toLowerCase();

    if (type.includes("painting") || labels?.includes("artwork")) return "mdi:image";
    if (type.includes("piano") || type.includes("instrument")) return "mdi:piano";
    if (type.includes("drawing")) return "mdi:draw";
    if (type.includes("sculpture")) return "mdi:shape";
    
    return "mdi:package-variant";
  }

  _getConfiguredSensorForMetric(roomEntity, fieldPath) {
    if (!roomEntity) return null;

    const [category, metric] = String(fieldPath).split(".");

    // --------------------------------------------------
    // âœ… 1. Check environment_config (new model)
    // --------------------------------------------------
    const envConfig = roomEntity?.attributes?.environment_config;

    const envSources = envConfig?.[category]?.[metric]?.source_entities;
    if (Array.isArray(envSources) && envSources.length > 0) {
      return envSources[0];
    }

    // --------------------------------------------------
    // âœ… 2. Check source_status.details (current HA pattern)
    // --------------------------------------------------
    const details = roomEntity?.attributes?.source_status?.details || {};
    const metricDetail = details[fieldPath];

    if (metricDetail) {
      if (Array.isArray(metricDetail.entities) && metricDetail.entities.length > 0) {
        return metricDetail.entities[0];
      }

      if (metricDetail.entity_id) {
        return metricDetail.entity_id;
      }

      if (metricDetail.source_entity) {
        return metricDetail.source_entity;
      }

      if (Array.isArray(metricDetail.source_entities) && metricDetail.source_entities.length > 0) {
        return metricDetail.source_entities[0];
      }
    }

    // --------------------------------------------------
    // âœ… 3. LAST CHANCE: try direct attribute binding (defensive)
    // --------------------------------------------------
    const direct = roomEntity?.attributes?.[category]?.[metric];

    if (typeof direct === "string" && direct.startsWith("sensor.")) {
      return direct;
    }

    return null;
  }

  _getCurrentRoomMetricValue(roomEntity, fieldPath) {
    const [category, metric] = String(fieldPath).split(".");
    return roomEntity?.attributes?.[category]?.[metric] ?? null;
  }

  _getFormattedRoomMetricValue(roomEntity, fieldPath) {
    const value = this._getCurrentRoomMetricValue(roomEntity, fieldPath);

    if (value === null || value === undefined || value === "") {
      return "-";
    }

    if (typeof value === "boolean") {
      return value ? "Detected" : "Clear";
    }

    const unitDefaults = {
      "climate.temperature": " degF",
      "climate.humidity": " %",
      "climate.dew_point": " degF",
      "light.lux": " lx",
      "air_quality.voc": " ppb",
      "air_quality.formaldehyde": " ppb",
      "air_quality.ozone": " ppb",
      "air_quality.no2": " ppb",
      "particulates.pm2_5": " ug/m3",
      "particulates.pm10": " ug/m3",
      "structural.pressure": " hPa",
      "structural.vibration": " mm/s",
      "context.noise": " dB",
      "control_context.co2": " ppm",
    };

    const fallbackUnit = unitDefaults[fieldPath] || "";
    const actualUnit = this._getUnitForRoomField(roomEntity, fieldPath, fallbackUnit);

    return actualUnit
      ? this._displayValueWithUnit(value, actualUnit)
      : this._displayValue(value);
  }

  _getRoomSensorsForMetric(roomId, metricDef, showAll = false) {
    if (!this._hass?.states) return [];

    const entityDomain = metricDef?.entityDomain || "sensor";
    const requiredPrefix = `${entityDomain}.`;

    const nameIncludes = Array.isArray(metricDef?.nameIncludes)
      ? metricDef.nameIncludes.map((v) => String(v).toLowerCase())
      : [];

    const unitIncludes = Array.isArray(metricDef?.unitIncludes)
      ? metricDef.unitIncludes.map((v) => String(v).toLowerCase())
      : [];

    const requiredDeviceClass = metricDef?.deviceClass || null;

    return Object.values(this._hass.states)
      .filter((entity) => {
        if (!entity?.entity_id?.startsWith(requiredPrefix)) {
          return false;
        }

        // âœ… ALWAYS keep room scoping
        const entityAreaId = this._getAreaIdForEntity(entity.entity_id);
        if (entityAreaId !== roomId) return false;

        // âœ… "Show all room sensors" = all same-room entities in the correct domain
        if (showAll) return true;

        const attrs = entity.attributes || {};
        const deviceClass = String(attrs.device_class || "").toLowerCase();
        const unit = String(attrs.unit_of_measurement || "").toLowerCase();
        const text = `${entity.entity_id} ${attrs.friendly_name || ""}`.toLowerCase();

        // âœ… documented / locked device classes
        if (requiredDeviceClass) {
          return deviceClass === requiredDeviceClass;
        }

        // âœ… semantic fallback for untyped metrics
        const nameMatch =
          nameIncludes.length > 0 &&
          nameIncludes.some((token) => text.includes(token));

        const unitMatch =
          unitIncludes.length > 0 &&
          unitIncludes.some((token) => unit.includes(token));

        if (nameIncludes.length > 0 || unitIncludes.length > 0) {
          return nameMatch || unitMatch;
        }

        return true;
      })
      .map((entity) => entity.entity_id)
      .sort((a, b) => a.localeCompare(b));
  }

  _getActiveLoanOuts(loans) {
    if (!Array.isArray(loans)) return [];

    return loans.filter((loan) => {
      if (!loan || typeof loan !== "object") return false;
      const direction = String(loan.direction || "").toLowerCase();
      const state = String(loan.state || "").toLowerCase();
      return direction === "out" && state === "active";
    });
  }

  _formatDateTimeLocalInput(value, fallbackNow = false) {
    const source = value
      ? new Date(value)
      : (fallbackNow ? new Date() : null);

    if (!source || Number.isNaN(source.getTime())) {
      return "";
    }

    const year = source.getFullYear();
    const month = String(source.getMonth() + 1).padStart(2, "0");
    const day = String(source.getDate()).padStart(2, "0");
    const hour = String(source.getHours()).padStart(2, "0");
    const minute = String(source.getMinutes()).padStart(2, "0");

    return `${year}-${month}-${day}T${hour}:${minute}`;
  }

  _openCustodyWorkflowDialog(assetId, workflow) {
    if (!assetId || !this._hass) return;

    const asset = this._getAssetEntities().find((entry) => entry.attributes?.asset_id === assetId);
    if (!asset) return;

    const attrs = asset.attributes || {};
    const custody = attrs.custody && typeof attrs.custody === "object"
      ? attrs.custody
      : {};
    const loans = Array.isArray(attrs.loans) ? attrs.loans : [];
    const activeLoanOuts = this._getActiveLoanOuts(loans);

    const mode = String(workflow || "").trim().toLowerCase();
    if (!mode) return;

    if (mode === "loan_in" && !activeLoanOuts.length) {
      alert("No active outgoing loan is available to check in.");
      return;
    }

    const modeConfig = {
      set_status: {
        title: "Update custody",
        service: "set_custody_status",
        submitLabel: "Save custody",
      },
      loan_out: {
        title: "Check out / Loan out",
        service: "record_loan_out",
        submitLabel: "Record loan out",
      },
      loan_in: {
        title: "Check in / Loan in",
        service: "record_loan_in",
        submitLabel: "Record loan in",
      },
    }[mode];

    if (!modeConfig) return;

    const activeLoanOptions = activeLoanOuts
      .map((loan) => {
        const loanId = String(loan.loan_id || "").trim();
        const counterparty = String(loan.counterparty || "Unknown counterparty").trim();
        const started = this._formatLocalDateTime(loan.start_date || loan.recorded_at || "");
        const fallbackLabel = loanId ? `${loanId} - ${counterparty}` : counterparty;
        return {
          loanId,
          label: started && started !== "â€”"
            ? `${counterparty} (${started})`
            : fallbackLabel,
        };
      })
      .filter((entry) => entry.loanId);

    const defaultLoanId = activeLoanOptions.length === 1 ? activeLoanOptions[0].loanId : "";

    const setStatusFields = `
      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-custody-status">Status</label>
        <select id="ai-custody-status" class="ai-dialog-select" name="status" required>
          ${["owned_on_site", "on_loan_out", "in_transit", "in_storage", "unknown"].map((statusValue) => `
            <option
              value="${this._escapeHtml(statusValue)}"
              ${String(custody.status || "owned_on_site") === statusValue ? "selected" : ""}
            >
              ${this._escapeHtml(this._titleCase(statusValue.replaceAll("_", " ")))}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-custody-holder">Holder</label>
        <input id="ai-custody-holder" class="ai-dialog-input" name="holder" type="text" value="${this._escapeHtml(String(custody.holder || ""))}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-custody-location-detail">Location detail</label>
        <input id="ai-custody-location-detail" class="ai-dialog-input" name="location_detail" type="text" value="${this._escapeHtml(String(custody.location_detail || ""))}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-custody-effective-at">Effective at</label>
        <input id="ai-custody-effective-at" class="ai-dialog-input" name="effective_at" type="datetime-local" value="${this._escapeHtml(this._formatDateTimeLocalInput(custody.effective_at, true))}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-custody-notes">Notes</label>
        <textarea id="ai-custody-notes" class="ai-dialog-input" style="min-height: 84px; resize: vertical;" name="notes">${this._escapeHtml(String(custody.notes || ""))}</textarea>
      </div>
    `;

    const loanOutFields = `
      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-counterparty">Counterparty</label>
        <input id="ai-loan-counterparty" class="ai-dialog-input" name="counterparty" type="text" required />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-start-date">Start date</label>
        <input id="ai-loan-start-date" class="ai-dialog-input" name="start_date" type="datetime-local" value="${this._escapeHtml(this._formatDateTimeLocalInput(null, true))}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-expected-return-date">Expected return date</label>
        <input id="ai-loan-expected-return-date" class="ai-dialog-input" name="expected_return_date" type="datetime-local" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-purpose">Purpose</label>
        <input id="ai-loan-purpose" class="ai-dialog-input" name="purpose" type="text" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-location-detail">Location detail</label>
        <input id="ai-loan-location-detail" class="ai-dialog-input" name="location_detail" type="text" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-agreement-uri">Agreement URI</label>
        <input id="ai-loan-agreement-uri" class="ai-dialog-input" name="agreement_uri" type="text" placeholder="media-source://..." />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-insurance">Insurance responsibility</label>
        <input id="ai-loan-insurance" class="ai-dialog-input" name="insurance_responsibility" type="text" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-notes">Notes</label>
        <textarea id="ai-loan-notes" class="ai-dialog-input" style="min-height: 84px; resize: vertical;" name="notes"></textarea>
      </div>
    `;

    const loanInFields = `
      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-in-loan-id">Loan to close</label>
        <select id="ai-loan-in-loan-id" class="ai-dialog-select" name="loan_id">
          <option value="">Auto-select active loan</option>
          ${activeLoanOptions.map((entry) => `
            <option value="${this._escapeHtml(entry.loanId)}" ${entry.loanId === defaultLoanId ? "selected" : ""}>
              ${this._escapeHtml(entry.label)}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-in-actual-return-date">Actual return date</label>
        <input id="ai-loan-in-actual-return-date" class="ai-dialog-input" name="actual_return_date" type="datetime-local" value="${this._escapeHtml(this._formatDateTimeLocalInput(null, true))}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-in-return-status">Return status</label>
        <select id="ai-loan-in-return-status" class="ai-dialog-select" name="return_status">
          ${["owned_on_site", "in_storage", "in_transit"].map((statusValue) => `
            <option value="${this._escapeHtml(statusValue)}" ${statusValue === "owned_on_site" ? "selected" : ""}>
              ${this._escapeHtml(this._titleCase(statusValue.replaceAll("_", " ")))}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-in-return-location-detail">Return location detail</label>
        <input id="ai-loan-in-return-location-detail" class="ai-dialog-input" name="return_location_detail" type="text" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-loan-in-notes">Notes</label>
        <textarea id="ai-loan-in-notes" class="ai-dialog-input" style="min-height: 84px; resize: vertical;" name="notes"></textarea>
      </div>
    `;

    const fieldsHtml = mode === "set_status"
      ? setStatusFields
      : mode === "loan_out"
        ? loanOutFields
        : loanInFields;

    const dialog = document.createElement("ha-dialog");
    dialog.open = true;
    dialog.setAttribute("header-title", modeConfig.title);
    dialog.setAttribute("type", "alert");
    dialog.scrimClickAction = true;
    dialog.escapeKeyAction = true;

    dialog.innerHTML = `
      <style>
        .ai-dialog-shell {
          min-width: 520px;
          max-width: 640px;
        }

        .ai-dialog-body {
          display: flex;
          flex-direction: column;
          gap: 14px;
          padding: 16px 24px;
        }

        .ai-dialog-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .ai-dialog-field-label {
          font-size: 12px;
          font-weight: 600;
          color: var(--secondary-text-color);
          letter-spacing: 0.02em;
        }

        .ai-dialog-input {
          width: 100%;
          min-height: 48px;
          box-sizing: border-box;
          padding: 10px 12px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 14px;
          outline: none;
        }

        .ai-dialog-select {
          width: 100%;
          min-height: 48px;
          box-sizing: border-box;
          padding: 0 12px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 14px;
          outline: none;
          appearance: auto;
        }

        .ai-dialog-actions {
          display: flex;
          justify-content: flex-end;
          align-items: center;
          gap: 10px;
          padding: 8px 24px 20px;
        }
      </style>

      <div class="ai-dialog-shell">
        <form class="ai-dialog-body" data-custody-form>
          ${fieldsHtml}
        </form>

        <div class="ai-dialog-actions">
          <button class="ai-secondary-button" type="button" data-custody-dialog-cancel>
            Cancel
          </button>
          <button class="ai-primary-button" type="button" data-custody-dialog-submit>
            ${this._escapeHtml(modeConfig.submitLabel)}
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    let settled = false;
    const closeDialog = () => {
      if (settled) return;
      settled = true;
      try { dialog.open = false; } catch (e) {}
      dialog.remove();
    };

    const form = dialog.querySelector("[data-custody-form]");
    const submitBtn = dialog.querySelector("[data-custody-dialog-submit]");
    const cancelBtn = dialog.querySelector("[data-custody-dialog-cancel]");

    const readValue = (name) => {
      const field = form?.querySelector(`[name="${name}"]`);
      return String(field?.value || "").trim();
    };

    const buildPayload = () => {
      if (mode === "set_status") {
        const status = readValue("status");
        if (!status) {
          throw new Error("Status is required.");
        }

        const payload = {
          asset_id: assetId,
          status,
        };

        const holderValue = readValue("holder");
        const locationDetailValue = readValue("location_detail");
        const effectiveAtValue = readValue("effective_at");
        const notesValue = readValue("notes");

        if (holderValue) payload.holder = holderValue;
        if (locationDetailValue) payload.location_detail = locationDetailValue;
        if (effectiveAtValue) payload.effective_at = effectiveAtValue;
        if (notesValue) payload.notes = notesValue;

        return payload;
      }

      if (mode === "loan_out") {
        const counterparty = readValue("counterparty");
        if (!counterparty) {
          throw new Error("Counterparty is required.");
        }

        const payload = {
          asset_id: assetId,
          counterparty,
        };

        const optionalFields = [
          "start_date",
          "expected_return_date",
          "purpose",
          "location_detail",
          "agreement_uri",
          "insurance_responsibility",
          "notes",
        ];

        optionalFields.forEach((fieldName) => {
          const value = readValue(fieldName);
          if (value) payload[fieldName] = value;
        });

        return payload;
      }

      const payload = {
        asset_id: assetId,
      };

      const loanIdValue = readValue("loan_id");
      if (loanIdValue) {
        payload.loan_id = loanIdValue;
      }

      [
        "actual_return_date",
        "return_status",
        "return_location_detail",
        "notes",
      ].forEach((fieldName) => {
        const value = readValue(fieldName);
        if (value) payload[fieldName] = value;
      });

      return payload;
    };

    cancelBtn?.addEventListener("click", () => {
      closeDialog();
    });

    submitBtn?.addEventListener("click", async () => {
      let payload;
      try {
        payload = buildPayload();
      } catch (err) {
        alert(err?.message || "Please complete required fields.");
        return;
      }

      submitBtn.disabled = true;
      try {
        await this._callService("asset_intelligence", modeConfig.service, payload);
        closeDialog();
        await this._load();
      } catch (err) {
        console.error("Custody workflow failed", err);
        alert("Unable to complete custody workflow. Please review inputs and try again.");
      } finally {
        if (!settled) {
          submitBtn.disabled = false;
        }
      }
    });

    dialog.addEventListener("closed", () => {
      closeDialog();
    });
  }

  _getAssetEntityByAssetId(assetId) {
    const normalizedAssetId = String(assetId || "").trim();
    if (!normalizedAssetId) return null;
    return this._getAssetEntities().find((entry) => entry.attributes?.asset_id === normalizedAssetId) || null;
  }

  _getDocumentRecordForAsset(assetId, documentId) {
    const asset = this._getAssetEntityByAssetId(assetId);
    const docs = Array.isArray(asset?.attributes?.documents) ? asset.attributes.documents : [];
    const normalizedDocumentId = String(documentId || "").trim();
    if (!normalizedDocumentId) return null;
    return docs.find((doc) => String(doc?.document_id || "") === normalizedDocumentId) || null;
  }

  _createClientDocumentId() {
    try {
      if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
        return String(globalThis.crypto.randomUUID());
      }
    } catch (err) {}

    const suffix = Math.random().toString(16).slice(2, 10);
    return `doc_${Date.now()}_${suffix}`;
  }

  _normalizeCsvToList(rawValue) {
    const text = String(rawValue || "").trim();
    if (!text) return [];
    return text
      .split(",")
      .map((entry) => String(entry || "").trim())
      .filter((entry) => !!entry);
  }

  _arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = "";

    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }

    return btoa(binary);
  }

  async _readFileInputAsBase64(form, fieldName, options = {}) {
    const required = !!options.required;
    const maxBytes = Number(options.maxBytes || MAX_BROWSER_DOCUMENT_UPLOAD_BYTES);
    const input = form?.querySelector(`input[name="${fieldName}"]`);
    const file = input?.files?.[0];

    if (!file) {
      if (required) {
        throw new Error("Please choose a document file to upload.");
      }
      return null;
    }

    if (file.size > maxBytes) {
      const mbLimit = Math.round(maxBytes / (1024 * 1024));
      throw new Error(`Selected file exceeds ${mbLimit} MB limit.`);
    }

    const buffer = await file.arrayBuffer();
    return {
      filename: file.name || "",
      mimeType: file.type || "",
      sizeBytes: Number(file.size || 0),
      contentBase64: this._arrayBufferToBase64(buffer),
    };
  }

  async _callServiceWithResponse(domain, service, data = {}) {
    if (this._hass?.callWS) {
      const response = await this._hass.callWS({
        type: "call_service",
        domain,
        service,
        service_data: data,
        return_response: true,
      });

      if (Array.isArray(response) && response.length) {
        const first = response[0];
        if (first && typeof first === "object" && first.service_response !== undefined) {
          return first.service_response;
        }
      }

      if (response && typeof response === "object") {
        if (response.service_response !== undefined) {
          return response.service_response;
        }
        if (response.response && typeof response.response === "object") {
          return response.response;
        }
      }
    }

    throw new Error(`No response-capable service client available for ${domain}.${service}`);
  }

  async _callService(domain, service, data = {}) {
    if (this._hass?.callWS) {
      await this._hass.callWS({
        type: "call_service",
        domain,
        service,
        service_data: data,
      });
      return;
    }

    if (this._hass?.callService) {
      await this._hass.callService(domain, service, data);
      return;
    }

    throw new Error(`No service client available for ${domain}.${service}`);
  }

  _extractErrorMessage(err) {
    if (!err) return "";

    const direct = String(err?.message || "").trim();
    if (direct) return direct;

    const nestedCandidates = [
      err?.error?.message,
      err?.body?.message,
      err?.result?.message,
      err?.data?.message,
      err?.error,
    ];

    for (const candidate of nestedCandidates) {
      const text = String(candidate || "").trim();
      if (text) return text;
    }

    try {
      const serialized = JSON.stringify(err);
      return String(serialized || "").trim();
    } catch (serializeErr) {
      return "";
    }
  }

  _openDocumentWorkflowDialog(assetId, mode) {
    const asset = this._getAssetEntityByAssetId(assetId);
    if (!asset || !this._hass) return;

    const attrs = asset.attributes || {};
    const modeText = String(mode || "").toLowerCase();
    if (modeText !== "upload" && modeText !== "attach") return;

    const isUpload = modeText === "upload";
    const title = isUpload ? "Upload document" : "Attach external document";
    const submitLabel = isUpload ? "Upload" : "Attach";
    const defaultType = "insurance_policy";
    const generatedDocumentId = this._createClientDocumentId();

    const uploadFields = `
      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-type">Document type</label>
        <select id="ai-doc-type" class="ai-dialog-select" name="type" required>
          ${DOCUMENT_TYPES.map((docType) => `
            <option value="${this._escapeHtml(docType)}" ${docType === defaultType ? "selected" : ""}>
              ${this._escapeHtml(this._titleCase(docType.replaceAll("_", " ")))}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-document-file">Document file</label>
        <input id="ai-doc-document-file" class="ai-dialog-input" name="document_file" type="file" required />
        <div style="font-size:12px; color:var(--secondary-text-color);">
          Choose the file directly from your browser instead of entering a Home Assistant path.
          <br/><strong>Maximum file size: 3 MB</strong>
        </div>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-filename">Filename override (optional)</label>
        <input id="ai-doc-filename" class="ai-dialog-input" name="filename" type="text" placeholder="policy_2026.pdf" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-title">Title</label>
        <input id="ai-doc-title" class="ai-dialog-input" name="title" type="text" placeholder="Insurance Policy 2026" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-date">Document date</label>
        <input id="ai-doc-date" class="ai-dialog-input" name="date" type="date" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-tags">Tags (comma separated)</label>
        <input id="ai-doc-tags" class="ai-dialog-input" name="tags" type="text" placeholder="insurance, policy" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-notes">Notes</label>
        <textarea id="ai-doc-notes" class="ai-dialog-input" style="min-height:84px; resize:vertical;" name="notes"></textarea>
      </div>
    `;

    const attachFields = `
      <input type="hidden" name="document_id" value="${this._escapeHtml(generatedDocumentId)}" />

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-type">Document type</label>
        <select id="ai-doc-type" class="ai-dialog-select" name="type" required>
          ${DOCUMENT_TYPES.map((docType) => `
            <option value="${this._escapeHtml(docType)}" ${docType === defaultType ? "selected" : ""}>
              ${this._escapeHtml(this._titleCase(docType.replaceAll("_", " ")))}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-title">Title</label>
        <input id="ai-doc-title" class="ai-dialog-input" name="title" type="text" placeholder="Insurance Policy 2026" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-provider-document-id">Document URL / Reference</label>
        <input id="ai-doc-provider-document-id" class="ai-dialog-input" name="provider_document_id" type="text" placeholder="https://vault.example.com/policies/policy_2026.pdf" required />
        <div style="font-size:12px; color:var(--secondary-text-color);">Link to the document location (URL, path, or reference ID)</div>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-location">External location reference</label>
        <input id="ai-doc-location" class="ai-dialog-input" name="location" type="text" placeholder="Bank archive reference" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-date">Document date</label>
        <input id="ai-doc-date" class="ai-dialog-input" name="date" type="date" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-tags">Tags (comma separated)</label>
        <input id="ai-doc-tags" class="ai-dialog-input" name="tags" type="text" placeholder="insurance, policy" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-notes">Notes</label>
        <textarea id="ai-doc-notes" class="ai-dialog-input" style="min-height:84px; resize:vertical;" name="notes"></textarea>
      </div>
    `;

    const physicalFields = `
      <div style="border-top:1px solid var(--divider-color); margin-top:4px; padding-top:12px;"></div>
      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-physical-location">Physical original location (optional)</label>
        <select id="ai-doc-physical-location" class="ai-dialog-select" name="physical_location">
          <option value="">No physical location to record</option>
          ${PHYSICAL_DOCUMENT_LOCATIONS.map((locationValue) => `
            <option value="${this._escapeHtml(locationValue)}">
              ${this._escapeHtml(this._titleCase(locationValue.replaceAll("_", " ")))}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-physical-notes">Physical location notes</label>
        <input id="ai-doc-physical-notes" class="ai-dialog-input" name="physical_notes" type="text" placeholder="Safe in closet / Bank box #12" />
      </div>
    `;

    const dialog = document.createElement("ha-dialog");
    dialog.open = true;
    dialog.setAttribute("header-title", title);
    dialog.setAttribute("type", "alert");
    dialog.scrimClickAction = true;
    dialog.escapeKeyAction = true;

    dialog.innerHTML = `
      <style>
        .ai-dialog-shell { min-width: 560px; max-width: 700px; }
        .ai-dialog-body { display:flex; flex-direction:column; gap:12px; padding:16px 24px; max-height:68vh; overflow:auto; }
        .ai-dialog-field { display:flex; flex-direction:column; gap:6px; }
        .ai-dialog-field-label { font-size:12px; font-weight:600; color:var(--secondary-text-color); letter-spacing:0.02em; }
        .ai-dialog-input { width:100%; min-height:44px; box-sizing:border-box; padding:10px 12px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font-size:14px; outline:none; }
        .ai-dialog-select { width:100%; min-height:44px; box-sizing:border-box; padding:0 12px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font-size:14px; outline:none; appearance:auto; }
        .ai-dialog-actions { display:flex; justify-content:flex-end; align-items:center; gap:10px; padding:10px 24px 20px; }
      </style>

      <div class="ai-dialog-shell">
        <form class="ai-dialog-body" data-document-workflow-form>
          ${isUpload ? uploadFields : attachFields}
          ${physicalFields}
        </form>
        <div class="ai-dialog-actions">
          <button class="ai-secondary-button" type="button" data-document-workflow-cancel>Cancel</button>
          <button class="ai-primary-button" type="button" data-document-workflow-submit>${this._escapeHtml(submitLabel)}</button>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    let settled = false;
    const closeDialog = () => {
      if (settled) return;
      settled = true;
      try { dialog.open = false; } catch (e) {}
      dialog.remove();
    };

    const form = dialog.querySelector("[data-document-workflow-form]");
    const submitBtn = dialog.querySelector("[data-document-workflow-submit]");
    const cancelBtn = dialog.querySelector("[data-document-workflow-cancel]");

    const readValue = (name) => {
      const field = form?.querySelector(`[name="${name}"]`);
      return String(field?.value || "").trim();
    };

    cancelBtn?.addEventListener("click", closeDialog);

    if (isUpload) {
      const fileInput = form?.querySelector('[name="document_file"]');
      const maxSizeBytes = MAX_BROWSER_DOCUMENT_UPLOAD_BYTES;
      const maxSizeMB = (maxSizeBytes / (1024 * 1024)).toFixed(1);

      let fileSizeWarning = document.createElement("div");
      fileSizeWarning.id = "ai-file-size-warning";
      fileSizeWarning.style.cssText = "display:none; padding:8px 10px; margin-top:4px; background:#fff3cd; border:1px solid #ffc107; border-radius:4px; color:#856404; font-size:13px;";
      fileInput?.parentElement?.appendChild(fileSizeWarning);

      fileInput?.addEventListener("change", (e) => {
        if (e.target.files && e.target.files[0]) {
          const fileSize = e.target.files[0].size;
          if (fileSize > maxSizeBytes) {
            fileSizeWarning.textContent = `File size (${(fileSize / (1024 * 1024)).toFixed(1)} MB) exceeds maximum of ${maxSizeMB} MB. Please select a smaller file.`;
            fileSizeWarning.style.display = "block";
            submitBtn.disabled = true;
          } else {
            fileSizeWarning.style.display = "none";
            submitBtn.disabled = false;
          }
        }
      });
    }

    submitBtn?.addEventListener("click", async () => {
      const type = readValue("type");
      if (!type) {
        alert("Document type is required.");
        return;
      }

      const physicalLocation = readValue("physical_location");
      const physicalNotes = readValue("physical_notes");

      submitBtn.disabled = true;
      try {
        if (isUpload) {
          const selectedDocument = await this._readFileInputAsBase64(form, "document_file", {
            required: true,
            maxBytes: MAX_BROWSER_DOCUMENT_UPLOAD_BYTES,
          });

          const uploadPayload = {
            asset_id: assetId,
            type,
            content_base64: selectedDocument.contentBase64,
            uploaded_filename: selectedDocument.filename,
          };

          const filename = readValue("filename");
          const titleValue = readValue("title");
          const dateValue = readValue("date");
          const notesValue = readValue("notes");
          const tags = this._normalizeCsvToList(readValue("tags"));

          if (selectedDocument.mimeType) uploadPayload.mime_type = selectedDocument.mimeType;
          if (selectedDocument.sizeBytes > 0) uploadPayload.size_bytes = selectedDocument.sizeBytes;
          if (filename) uploadPayload.filename = filename;
          if (titleValue) uploadPayload.title = titleValue;
          if (dateValue) uploadPayload.date = dateValue;
          if (notesValue) uploadPayload.notes = notesValue;
          if (tags.length) uploadPayload.tags = tags;

          const canUseHttpApi = typeof this._hass?.callApi === "function";
          if (!canUseHttpApi && selectedDocument.sizeBytes > 750 * 1024) {
            throw new Error("File is too large for this connection mode. Please use a smaller file or configure path-based upload.");
          }

          await this._callService("asset_intelligence", "upload_document", uploadPayload);
          await this._load();

          if (physicalLocation) {
            const refreshedAsset = this._getAssetEntityByAssetId(assetId);
            const refreshedDocs = Array.isArray(refreshedAsset?.attributes?.documents)
              ? refreshedAsset.attributes.documents
              : [];

            const docByLastId = refreshedDocs.find((doc) => String(doc?.document_id || "") === String(refreshedAsset?.attributes?.last_document_id || ""));
            const fallbackDoc = refreshedDocs.length ? refreshedDocs[refreshedDocs.length - 1] : null;
            const targetDoc = docByLastId || fallbackDoc;

            await this._callService("asset_intelligence", "add_physical_document_location", {
              asset_id: assetId,
              type,
              location: physicalLocation,
              notes: physicalNotes || "",
              document_id: targetDoc?.document_id || null,
              provider_document_id: targetDoc?.provider_document_id || null,
              title: targetDoc?.title || titleValue || null,
            });
            await this._load();
          }
        } else {
          const providerDocumentId = readValue("provider_document_id");
          if (!providerDocumentId) {
            throw new Error("Provider document ID is required for external attach.");
          }

          const attachPayload = {
            asset_id: assetId,
            document_id: readValue("document_id") || generatedDocumentId,
            type,
            provider_document_id: providerDocumentId,
          };

          const optionalTextFields = [
            "title",
            "location",
            "date",
            "notes",
          ];

          optionalTextFields.forEach((fieldName) => {
            const value = readValue(fieldName);
            if (value) attachPayload[fieldName] = value;
          });

          const sizeBytesValue = readValue("size_bytes");
          if (sizeBytesValue) {
            const numericSize = Number(sizeBytesValue);
            if (!Number.isNaN(numericSize) && numericSize >= 0) {
              attachPayload.size_bytes = numericSize;
            }
          }

          const tags = this._normalizeCsvToList(readValue("tags"));
          if (tags.length) attachPayload.tags = tags;

          await this._callService("asset_intelligence", "attach_document", attachPayload);

          if (physicalLocation) {
            await this._callService("asset_intelligence", "add_physical_document_location", {
              asset_id: assetId,
              type,
              location: physicalLocation,
              notes: physicalNotes || "",
              document_id: attachPayload.document_id,
              provider_document_id: attachPayload.provider_document_id,
              title: attachPayload.title || null,
            });
          }

          await this._load();
        }

        closeDialog();
      } catch (err) {
        console.error("Document workflow failed", err);
        const detailedMessage = this._extractErrorMessage(err);
        alert(detailedMessage || "Document workflow failed. Verify fields and try again.");
      } finally {
        if (!settled) {
          submitBtn.disabled = false;
        }
      }
    });

    dialog.addEventListener("closed", closeDialog);
  }

  _openPhysicalDocumentDialog(assetId, documentId) {
    const doc = this._getDocumentRecordForAsset(assetId, documentId);
    if (!doc || !this._hass) {
      alert("Document not found for this asset.");
      return;
    }

    const asset = this._getAssetEntityByAssetId(assetId);
    const physicalLocations = Array.isArray(asset?.attributes?.physical_documents)
      ? asset.attributes.physical_documents
      : [];
    const existingPhysical = this._resolvePhysicalDocumentLocation(doc, physicalLocations) || {};
    const initialLocation = String(existingPhysical?.location || "").trim();
    const initialNotes = String(existingPhysical?.notes || "").trim();

    const docType = String(doc.type || "other");
    const docTitle = String(doc.title || doc.filename || doc.document_id || "Document");

    const dialog = document.createElement("ha-dialog");
    dialog.open = true;
    dialog.setAttribute("header-title", "Edit physical document location");
    dialog.setAttribute("type", "alert");
    dialog.scrimClickAction = true;
    dialog.escapeKeyAction = true;

    dialog.innerHTML = `
      <style>
        .ai-dialog-shell { min-width: 520px; max-width: 640px; }
        .ai-dialog-body { display:flex; flex-direction:column; gap:12px; padding:16px 24px; }
        .ai-dialog-field { display:flex; flex-direction:column; gap:6px; }
        .ai-dialog-field-label { font-size:12px; font-weight:600; color:var(--secondary-text-color); letter-spacing:0.02em; }
        .ai-dialog-input { width:100%; min-height:44px; box-sizing:border-box; padding:10px 12px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font-size:14px; outline:none; }
        .ai-dialog-select { width:100%; min-height:44px; box-sizing:border-box; padding:0 12px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font-size:14px; outline:none; appearance:auto; }
        .ai-dialog-actions { display:flex; justify-content:flex-end; align-items:center; gap:10px; padding:10px 24px 20px; }
      </style>

      <div class="ai-dialog-shell">
        <div class="ai-dialog-body">
          <div class="ai-readout-muted">${this._escapeHtml(docTitle)}</div>

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label" for="ai-physical-location">Location</label>
            <select id="ai-physical-location" class="ai-dialog-select">
              ${PHYSICAL_DOCUMENT_LOCATIONS.map((locationValue) => `
                <option value="${this._escapeHtml(locationValue)}" ${locationValue === initialLocation ? "selected" : ""}>
                  ${this._escapeHtml(this._titleCase(locationValue.replaceAll("_", " ")))}
                </option>
              `).join("")}
            </select>
          </div>

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label" for="ai-physical-notes">Notes</label>
            <input id="ai-physical-notes" class="ai-dialog-input" type="text" placeholder="Safe in closet / Bank box #12" value="${this._escapeHtml(initialNotes)}" />
          </div>
        </div>

        <div class="ai-dialog-actions">
          <button class="ai-secondary-button" type="button" data-physical-cancel>Cancel</button>
          <button class="ai-primary-button" type="button" data-physical-save>Save</button>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    let settled = false;
    const closeDialog = () => {
      if (settled) return;
      settled = true;
      try { dialog.open = false; } catch (e) {}
      dialog.remove();
    };

    const locationInput = dialog.querySelector("#ai-physical-location");
    const notesInput = dialog.querySelector("#ai-physical-notes");
    const saveBtn = dialog.querySelector("[data-physical-save]");

    dialog.querySelector("[data-physical-cancel]")?.addEventListener("click", closeDialog);

    saveBtn?.addEventListener("click", async () => {
      const location = String(locationInput?.value || "").trim();
      if (!location) {
        alert("Location is required.");
        return;
      }

      saveBtn.disabled = true;
      try {
        await this._callService("asset_intelligence", "add_physical_document_location", {
          asset_id: assetId,
          type: docType,
          location,
          notes: String(notesInput?.value || "").trim(),
          document_id: doc.document_id,
          provider_document_id: doc.provider_document_id,
          title: doc.title || null,
        });
        await this._load();
        closeDialog();
      } catch (err) {
        console.error("Failed to save physical document location", err);
        alert(err?.message || "Failed to save physical document location.");
      } finally {
        if (!settled) {
          saveBtn.disabled = false;
        }
      }
    });

    dialog.addEventListener("closed", closeDialog);
  }

  async _showDocumentInfoDialog(assetId, documentId) {
    const localDoc = this._getDocumentRecordForAsset(assetId, documentId);
    if (!localDoc) {
      alert("Document not found.");
      return;
    }

    let serviceInfo = null;
    try {
      serviceInfo = await this._callServiceWithResponse("asset_intelligence", "get_document_info", {
        asset_id: assetId,
        document_id: documentId,
      });
    } catch (err) {
      console.warn("get_document_info response unavailable; using local document record", err);
    }

    const info = serviceInfo && typeof serviceInfo === "object" ? serviceInfo : {};
    const lines = [
      `Title: ${localDoc.title || localDoc.filename || "-"}`,
      `Type: ${this._titleCase(String(localDoc.type || "other").replaceAll("_", " "))}`,
      `Document ID: ${localDoc.document_id || "-"}`,
      `Provider: ${info.provider || localDoc.provider || "-"}`,
      `Provider document ID: ${info.provider_document_id || localDoc.provider_document_id || "-"}`,
      `Filename: ${info.filename || localDoc.filename || "-"}`,
      `MIME type: ${info.mime_type || localDoc.mime_type || "-"}`,
      `Size (bytes): ${info.size_bytes ?? localDoc.size_bytes ?? "-"}`,
      `Available: ${info.available === true ? "Yes" : info.available === false ? "No" : "Unknown"}`,
      `Exists: ${info.exists === true ? "Yes" : info.exists === false ? "No" : "Unknown"}`,
    ];

    window.alert(lines.join("\n"));
  }

  async _checkDocumentAvailability(assetId, documentId) {
    const localDoc = this._getDocumentRecordForAsset(assetId, documentId);
    if (!localDoc) {
      alert("Document not found.");
      return;
    }

    try {
      const response = await this._callServiceWithResponse("asset_intelligence", "check_document_availability", {
        asset_id: assetId,
        document_id: documentId,
      });

      const available = response && typeof response === "object"
        ? response.available
        : undefined;
      const exists = response && typeof response === "object"
        ? response.exists
        : undefined;

      const providerText = response?.provider || localDoc.provider || "â€”";
      const availabilityText = available === true ? "Available" : available === false ? "Unavailable" : "Unknown";
      const existsText = exists === true ? "Exists" : exists === false ? "Missing" : "Unknown";

      window.alert(
        `Availability check\n\nDocument: ${localDoc.title || localDoc.filename || localDoc.document_id || "â€”"}\nProvider: ${providerText}\nStatus: ${availabilityText}\nStorage file: ${existsText}`
      );
    } catch (err) {
      console.error("Document availability check failed", err);
      alert(err?.message || "Failed to check document availability.");
    }
  }

  async _deleteDocument(assetId, documentId) {
    const localDoc = this._getDocumentRecordForAsset(assetId, documentId);
    if (!localDoc) {
      alert("Document not found.");
      return;
    }

    const docName = localDoc.title || localDoc.filename || localDoc.document_id || "this document";
    const confirmed = await this._showConfirmDialog(
      `Delete ${docName}? This removes it from the asset and deletes stored file data when present.`,
      {
        title: "Delete document",
        confirmText: "Delete",
        dismissText: "Cancel",
        destructive: true,
      }
    );

    if (!confirmed) return;

    try {
      await this._callService("asset_intelligence", "delete_document", {
        asset_id: assetId,
        document_id: documentId,
        delete_storage: true,
      });
      await this._load();
    } catch (err) {
      console.error("Failed to delete document", err);
      alert(err?.message || "Failed to delete document.");
    }
  }

  async _viewDocument(assetId, documentId) {
    const localDoc = this._getDocumentRecordForAsset(assetId, documentId);
    if (!localDoc) {
      alert("Document not found.");
      return;
    }

    let url = localDoc?.url || localDoc?.preview_url || localDoc?.image_url || null;

    if (!url && localDoc?.provider_document_id && /^https?:\/\//i.test(String(localDoc.provider_document_id))) {
      url = String(localDoc.provider_document_id);
    }

    if (!url) {
      url = this._resolveDocumentImageUrl(assetId, localDoc);
    }

    if (url) {
      const isLocalProtectedApi = String(url).startsWith("/api/asset_intelligence/document/");

      if (isLocalProtectedApi) {
        const token = this._hass?.auth?.data?.access_token;

        if (!token) {
          window.open(url, "_blank");
          return;
        }

        try {
          const response = await fetch(url, {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          });

          if (!response.ok) {
            throw new Error(`Failed to open document (${response.status})`);
          }

          const blob = await response.blob();
          const blobUrl = URL.createObjectURL(blob);
          window.open(blobUrl, "_blank");

          // Keep the object URL alive briefly so the new tab can fully load.
          setTimeout(() => {
            try {
              URL.revokeObjectURL(blobUrl);
            } catch (e) {}
          }, 60000);
          return;
        } catch (err) {
          console.error("Failed to open protected local document URL", err);
          alert(this._extractErrorMessage(err) || "Failed to open document.");
          return;
        }
      }

      window.open(url, "_blank");
    } else {
      alert("No accessible document URL found. Document may be stored externally without a direct link.");
    }
  }

  async _editDocumentMetadata(assetId, documentId) {
    const localDoc = this._getDocumentRecordForAsset(assetId, documentId);
    if (!localDoc) {
      alert("Document not found.");
      return;
    }

    // Open the existing document upload/attach dialog in edit mode
    // We'll reuse the attach document dialog but pre-populate with existing data
    this._openDocumentEditDialog(assetId, documentId, localDoc);
  }

  _openDocumentEditDialog(assetId, documentId, existingDoc) {
    if (!this._hass) return;

    const title = "Edit document metadata";
    const submitLabel = "Update";

    const editFields = `
      <input type="hidden" name="document_id" value="${this._escapeHtml(documentId)}" />

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-type">Document type</label>
        <select id="ai-doc-type" class="ai-dialog-select" name="type" required>
          ${DOCUMENT_TYPES.map((docType) => `
            <option value="${this._escapeHtml(docType)}" ${docType === existingDoc.type ? "selected" : ""}>
              ${this._escapeHtml(this._titleCase(docType.replaceAll("_", " ")))}
            </option>
          `).join("")}
        </select>
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-title">Title</label>
        <input id="ai-doc-title" class="ai-dialog-input" name="title" type="text" placeholder="Document title" value="${this._escapeHtml(existingDoc.title || "")}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-date">Document date</label>
        <input id="ai-doc-date" class="ai-dialog-input" name="date" type="date" value="${this._escapeHtml(existingDoc.date || existingDoc?.metadata?.date || "")}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-tags">Tags (comma separated)</label>
        <input id="ai-doc-tags" class="ai-dialog-input" name="tags" type="text" placeholder="tag1, tag2" value="${this._escapeHtml((existingDoc.tags || []).join(", "))}" />
      </div>

      <div class="ai-dialog-field">
        <label class="ai-dialog-field-label" for="ai-doc-notes">Notes</label>
        <textarea id="ai-doc-notes" class="ai-dialog-input" style="min-height:84px; resize:vertical;" name="notes">${this._escapeHtml(existingDoc.notes || existingDoc?.metadata?.notes || "")}</textarea>
      </div>
    `;

    const dialog = document.createElement("ha-dialog");
    dialog.open = true;
    dialog.setAttribute("header-title", title);
    dialog.setAttribute("type", "alert");
    dialog.scrimClickAction = true;
    dialog.escapeKeyAction = true;

    dialog.innerHTML = `
      <style>
        .ai-dialog-shell { min-width: 560px; max-width: 700px; }
        .ai-dialog-body { display:flex; flex-direction:column; gap:12px; padding:16px 24px; max-height:68vh; overflow:auto; }
        .ai-dialog-field { display:flex; flex-direction:column; gap:6px; }
        .ai-dialog-field-label { font-size:12px; font-weight:600; color:var(--secondary-text-color); letter-spacing:0.02em; }
        .ai-dialog-input { width:100%; min-height:44px; box-sizing:border-box; padding:10px 12px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font-size:14px; outline:none; }
        .ai-dialog-select { width:100%; min-height:44px; box-sizing:border-box; padding:0 12px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); font-size:14px; outline:none; appearance:auto; }
        .ai-dialog-actions { display:flex; justify-content:flex-end; align-items:center; gap:10px; padding:10px 24px 20px; }
      </style>

      <div class="ai-dialog-shell">
        <form class="ai-dialog-body" data-document-edit-form>
          ${editFields}
        </form>
        <div class="ai-dialog-actions">
          <button class="ai-secondary-button" type="button" data-document-edit-cancel>Cancel</button>
          <button class="ai-primary-button" type="button" data-document-edit-submit>${this._escapeHtml(submitLabel)}</button>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    let settled = false;
    const closeDialog = () => {
      if (settled) return;
      settled = true;
      try { dialog.open = false; } catch (e) {}
      dialog.remove();
    };

    const form = dialog.querySelector("[data-document-edit-form]");
    const submitBtn = dialog.querySelector("[data-document-edit-submit]");
    const cancelBtn = dialog.querySelector("[data-document-edit-cancel]");

    const readValue = (name) => {
      const field = form?.querySelector(`[name="${name}"]`);
      return String(field?.value || "").trim();
    };

    cancelBtn.onclick = () => closeDialog();

    submitBtn.onclick = async () => {
      if (settled) return;
      submitBtn.disabled = true;

      try {
        const type = readValue("type");
        const tags = this._normalizeCsvToList(readValue("tags"));
        
        if (!type) throw new Error("Document type is required");

        const updatePayload = {
          asset_id: assetId,
          document_id: documentId,
          type,
          title: readValue("title") || null,
          date: readValue("date") || null,
          notes: readValue("notes") || null,
          tags,
        };

        await this._callService("asset_intelligence", "update_document_metadata", updatePayload);
        await this._load();

        closeDialog();
      } catch (err) {
        console.error("Document edit failed", err);
        const detailedMessage = this._extractErrorMessage(err);
        alert(detailedMessage || "Failed to update document metadata.");
      } finally {
        if (!settled) {
          submitBtn.disabled = false;
        }
      }
    };

    dialog.addEventListener("closed", closeDialog);
  }

  _showConfirmDialog(message, options = {}) {
    const text = String(message || "").trim();
    const title = String(options.title || "").trim() || "Confirm action";
    const confirmText = String(options.confirmText || "").trim() || "OK";
    const dismissText = String(options.dismissText || "").trim() || "Cancel";
    const destructive = options.destructive === true;
    // Always use the local fallback dialog. In this custom panel runtime,
    // native dialog-box registration can be inconsistent and may render blank.
    return this._showFallbackConfirmDialog({
      title,
      text,
      confirmText,
      dismissText,
      destructive,
    });
  }

  _showUnsavedChangesDialog() {
    return this._showChoiceDialog({
      title: "Unsaved changes",
      text: "You have unsaved changes in this asset. Save them before leaving this page?",
      primaryText: "Save",
      secondaryText: "Cancel",
      primaryVariant: "brand",
      secondaryValue: "discard",
      defaultValue: "stay",
    });
  }

  _showChoiceDialog(options = {}) {
    const title = String(options.title || "Confirm").trim();
    const text = String(options.text || "").trim();
    const primaryText = String(options.primaryText || "OK").trim();
    const secondaryText = String(options.secondaryText || "Cancel").trim();
    const secondaryValue = String(options.secondaryValue || "cancel").trim() || "cancel";
    const tertiaryText = String(options.tertiaryText || "").trim();
    const primaryVariant = String(options.primaryVariant || "brand").trim() || "brand";
    const defaultValue = String(options.defaultValue || "cancel").trim() || "cancel";

    if (!window.customElements?.get?.("ha-dialog")) {
      const promptText = title ? `${title}\n\n${text}` : text;
      const confirmed = window.confirm(promptText);
      return Promise.resolve(confirmed ? "save" : defaultValue);
    }

    return new Promise((resolve) => {
      const dialog = document.createElement("ha-dialog");
      dialog.setAttribute("header-title", title);
      dialog.setAttribute("type", "alert");
      dialog.open = true;
      dialog.scrimClickAction = true;
      dialog.escapeKeyAction = true;

      dialog.innerHTML = `
        <div style="padding:16px; font-size:14px; line-height:1.5; white-space:normal;">
          ${this._escapeHtml(text)}
        </div>
        <div style="display:flex; justify-content:flex-end; gap:8px; padding:0 16px 16px;">
          ${tertiaryText ? `
            <ha-button appearance="plain" data-choice="discard">
              ${this._escapeHtml(tertiaryText)}
            </ha-button>
          ` : ""}
          <ha-button appearance="plain" data-choice="${this._escapeHtml(secondaryValue)}">
            ${this._escapeHtml(secondaryText)}
          </ha-button>
          <ha-button variant="${this._escapeHtml(primaryVariant)}" data-choice="save">
            ${this._escapeHtml(primaryText)}
          </ha-button>
        </div>
      `;

      document.body.appendChild(dialog);

      let settled = false;
      const closeWith = (value) => {
        if (settled) return;
        settled = true;
        try { dialog.open = false; } catch (e) {}
        dialog.remove();
        resolve(value || defaultValue);
      };

      dialog.querySelectorAll("[data-choice]").forEach((btn) => {
        btn.addEventListener("click", () => {
          closeWith(btn.getAttribute("data-choice") || defaultValue);
        });
      });

      dialog.addEventListener("closed", (e) => {
        const action = e.detail?.action;
        if (action === "confirm") {
          closeWith("save");
          return;
        }
        closeWith(defaultValue);
      });
    });
  }

  _showFallbackConfirmDialog({ title, text, confirmText, dismissText, destructive }) {
    if (!window.customElements?.get?.("ha-dialog")) {
      const promptText = title ? `${title}\n\n${text}` : text;
      return Promise.resolve(window.confirm(promptText));
    }

    return new Promise((resolve) => {
      const dialog = document.createElement("ha-dialog");

      dialog.setAttribute("header-title", String(title || ""));
      dialog.setAttribute("type", "alert");
      dialog.open = true;
      dialog.scrimClickAction = true;
      dialog.escapeKeyAction = true;

      const confirmVariant = destructive ? "danger" : "brand";

      dialog.innerHTML = `
        <div style="padding:16px; font-size:14px; line-height:1.5; white-space:normal;">
          ${this._escapeHtml(text)}
        </div>

        <ha-dialog-footer slot="footer">
          <ha-button slot="secondaryAction" appearance="plain" data-action="cancel">
            ${this._escapeHtml(dismissText)}
          </ha-button>
          <ha-button slot="primaryAction" variant="${confirmVariant}" data-action="confirm">
            ${this._escapeHtml(confirmText)}
          </ha-button>
        </ha-dialog-footer>
      `;

      document.body.appendChild(dialog);

      const closeWith = (confirmed) => {
        try { dialog.open = false; } catch (e) {}
        dialog.remove();
        resolve(confirmed === true);
      };

      const cancelBtn = dialog.querySelector('[data-action="cancel"]');
      const confirmBtn = dialog.querySelector('[data-action="confirm"]');

      cancelBtn?.addEventListener("click", () => closeWith(false));
      confirmBtn?.addEventListener("click", () => closeWith(true));

      dialog.addEventListener("closed", (e) => {
        const action = e.detail?.action;
        if (action === "confirm") {
          closeWith(true);
          return;
        }
        closeWith(false);
      });
    });
  }

  _showActivityItemDialog(item) {
    const safeItem = item && typeof item === "object" ? item : {};
    const title = String(safeItem.title || "Activity details");
    const details = (safeItem.details && typeof safeItem.details === "object")
      ? safeItem.details
      : {};
    const normalizedFieldChanges = this._normalizeActivityFieldChanges(details, safeItem);

    if (!window.customElements?.get?.("ha-dialog")) {
      const fallbackText = [
        `Type: ${String(safeItem.kind || "Unknown")}`,
        `When: ${String(safeItem.meta || "â€”")}`,
        `Summary: ${String(safeItem.copy || safeItem.title || "â€”")}`,
        "",
        "Details:",
        JSON.stringify(details, null, 2),
      ].join("\n");
      window.alert(fallbackText);
      return;
    }

    const baseRows = [
      ["Type", this._titleCase(String(safeItem.kind || "unknown").replaceAll("_", " "))],
      ["When", String(safeItem.meta || "â€”")],
      ["Title", String(safeItem.title || "â€”")],
      ["Summary", String(safeItem.copy || "â€”")],
    ];

    const detailRows = Object.entries(details)
      .filter(([key]) => (
        key !== "title"
        && key !== "message"
        && key !== "summary"
        && key !== "profile"
        && key !== "field_changes"
        && key !== "changed_fields"
        && key !== "environment_requirements"
        && key !== "room_environment"
      ))
      .map(([key, value]) => [
        this._titleCase(String(key).replaceAll("_", " ")),
        value,
      ]);

    const changedFields = (() => {
      if (normalizedFieldChanges && typeof normalizedFieldChanges === "object") {
        const keys = Object.keys(normalizedFieldChanges);
        if (keys.length) return keys;
      }
      const explicit = Array.isArray(details?.changed_fields)
        ? details.changed_fields.filter((entry) => typeof entry === "string" && entry.trim())
        : [];
      return explicit;
    })();
    const changedFieldsHtml = changedFields.length
      ? `
        <div style="margin-top:12px; font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.04em;">Changed fields</div>
        <div style="margin-top:6px; border:1px solid var(--divider-color); border-radius:8px; padding:10px 12px;">
          <ul style="margin:0; padding-left:18px; display:flex; flex-direction:column; gap:4px;">
            ${changedFields.map((fieldName) => `<li>${this._escapeHtml(this._formatAuditFieldPath(fieldName))}</li>`).join("")}
          </ul>
        </div>
      `
      : "";

    const fieldChangesHtml = this._renderActivityFieldChanges(normalizedFieldChanges);
    const measurementProfileHtml = this._renderMeasurementProfile(details?.profile);

    const hasChangeSections = !!changedFields.length || !!fieldChangesHtml;

    const rowsHtml = [...baseRows, ...(hasChangeSections ? [] : detailRows)]
      .map(([label, value]) => {
        return `
          <div style="display:grid; grid-template-columns: 140px minmax(0,1fr); gap:10px; padding:8px 0; border-bottom:1px solid rgba(0,0,0,0.08); align-items:start;">
            <div style="font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.04em;">${this._escapeHtml(String(label || "Field"))}</div>
            <div style="font-size:14px; color:var(--primary-text-color); line-height:1.45; min-width:0; word-break:break-word;">${this._renderActivityDialogValue(value)}</div>
          </div>
        `;
      })
      .join("");

    const dialog = document.createElement("ha-dialog");
    dialog.setAttribute("header-title", this._escapeHtml(title));
    dialog.setAttribute("type", "alert");
    dialog.open = true;
    dialog.scrimClickAction = true;
    dialog.escapeKeyAction = true;

    dialog.innerHTML = `
      <div style="padding:16px; max-height:65vh; overflow:auto;">
        <div style="font-size:14px; font-weight:700; margin-bottom:8px; color:var(--primary-text-color);">Activity details</div>
        <div style="display:flex; flex-direction:column; gap:0;">
          ${rowsHtml}
        </div>
        ${changedFieldsHtml}
        ${measurementProfileHtml}
        ${fieldChangesHtml
          ? `
            <div style="margin-top:12px; font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.04em;">Field changes</div>
            <div style="margin-top:6px; border:1px solid var(--divider-color); border-radius:8px; overflow:hidden;">
              ${fieldChangesHtml}
            </div>
          `
          : ""
        }
      </div>
      <ha-dialog-footer slot="footer">
        <ha-button slot="primaryAction" variant="brand" data-action="close">Close</ha-button>
      </ha-dialog-footer>
    `;

    document.body.appendChild(dialog);

    const close = () => {
      try { dialog.open = false; } catch (e) {}
      dialog.remove();
    };

    dialog.querySelector('[data-action="close"]')?.addEventListener("click", close);
    dialog.addEventListener("closed", close);
  }

  _renderMeasurementProfile(profile) {
    if (!profile || typeof profile !== "object") {
      return "";
    }

    const baseline = profile.baseline && typeof profile.baseline === "object"
      ? profile.baseline
      : {};
    const metrics = Array.isArray(profile.metrics)
      ? profile.metrics
      : [];

    const observationPeriod = Number(baseline.observation_period || 0);
    const formatDuration = (seconds) => {
      if (!Number.isFinite(seconds) || seconds <= 0) return "â€”";
      const total = Math.floor(seconds);
      const hh = String(Math.floor(total / 3600)).padStart(2, "0");
      const mm = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
      const ss = String(total % 60).padStart(2, "0");
      return `${hh}:${mm}:${ss}`;
    };

    const baselineRows = [
      ["Observation count", baseline.observation_count],
      ["Observation start", baseline.observation_start ? this._formatLocalDateTime(baseline.observation_start) : "â€”"],
      ["Observation end", baseline.observation_end ? this._formatLocalDateTime(baseline.observation_end) : "â€”"],
      ["Observation period", formatDuration(observationPeriod)],
      ["Confidence", baseline.confidence || "â€”"],
    ];

    if (baseline.avg_temperature !== undefined && baseline.avg_temperature !== null) {
      baselineRows.push(["Average temperature", baseline.avg_temperature]);
    }
    if (baseline.avg_humidity !== undefined && baseline.avg_humidity !== null) {
      baselineRows.push(["Average humidity", baseline.avg_humidity]);
    }
    if (baseline.avg_lux !== undefined && baseline.avg_lux !== null) {
      baselineRows.push(["Average lux", baseline.avg_lux]);
    }
    if (baseline.avg_uv !== undefined && baseline.avg_uv !== null) {
      baselineRows.push(["Average UV", baseline.avg_uv]);
    }

    const baselineHtml = baselineRows
      .map(([label, value]) => `
        <div style="display:grid; grid-template-columns: 180px minmax(0,1fr); gap:10px; padding:7px 0; border-bottom:1px solid rgba(0,0,0,0.06);">
          <div style="font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.03em;">${this._escapeHtml(String(label))}</div>
          <div style="font-size:14px; color:var(--primary-text-color);">${this._escapeHtml(String(value ?? "â€”"))}</div>
        </div>
      `)
      .join("");

    const metricRows = metrics
      .slice(0, 120)
      .map((metric) => {
        if (!metric || typeof metric !== "object") return "";
        const name = String(metric.name || metric.key || "Metric");
        const unit = metric.unit ? String(metric.unit) : "";
        const avg = metric.avg ?? "â€”";
        const min = metric.min ?? "â€”";
        const max = metric.max ?? "â€”";
        const last = metric.last ?? "â€”";
        const samples = metric.samples ?? "â€”";
        const suffix = unit ? ` ${unit}` : "";
        return `
          <div style="padding:8px 0; border-bottom:1px solid rgba(0,0,0,0.05);">
            <div style="font-size:13px; font-weight:700; color:var(--primary-text-color); margin-bottom:4px;">${this._escapeHtml(name)}</div>
            <div style="font-size:13px; color:var(--secondary-text-color); line-height:1.45;">
              Average: <strong>${this._escapeHtml(String(avg))}${this._escapeHtml(suffix)}</strong>
              â€¢ Min: ${this._escapeHtml(String(min))}${this._escapeHtml(suffix)}
              â€¢ Max: ${this._escapeHtml(String(max))}${this._escapeHtml(suffix)}
              â€¢ Last: ${this._escapeHtml(String(last))}${this._escapeHtml(suffix)}
              â€¢ Samples: ${this._escapeHtml(String(samples))}
            </div>
          </div>
        `;
      })
      .filter((row) => !!row)
      .join("");

    const sensorsUsed = Array.isArray(baseline.sensors_used) ? baseline.sensors_used : [];
    const sensorsUsedHtml = sensorsUsed.length
      ? `
        <div style="margin-top:10px; font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.04em;">Sensors used</div>
        <div style="margin-top:6px; border:1px solid var(--divider-color); border-radius:8px; padding:10px 12px;">
          ${sensorsUsed.map((sensor) => `<div style="font-size:13px; color:var(--primary-text-color); line-height:1.45;">${this._escapeHtml(String(sensor))}</div>`).join("")}
        </div>
      `
      : "";

    return `
      <div style="margin-top:12px; font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.04em;">Measurement profile</div>
      <div style="margin-top:6px; border:1px solid var(--divider-color); border-radius:8px; padding:10px 12px;">
        ${baselineHtml}
        ${metricRows ? `<div style="margin-top:10px; font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase; letter-spacing:0.04em;">Metrics</div><div style="margin-top:6px;">${metricRows}</div>` : ""}
      </div>
      ${sensorsUsedHtml}
    `;
  }

  _renderActivityDialogValue(value) {
    if (value === null || value === undefined || value === "") {
      return `<span style="color:var(--secondary-text-color);">â€”</span>`;
    }

    if (Array.isArray(value)) {
      if (!value.length) {
        return `<span style="color:var(--secondary-text-color);">[]</span>`;
      }
      return `<ul style="margin:0; padding-left:18px;">${value.map((entry) => `<li>${this._renderActivityDialogValue(entry)}</li>`).join("")}</ul>`;
    }

    if (typeof value === "object") {
      const json = JSON.stringify(value, null, 2);
      return `<pre style="margin:0; font-size:12px; line-height:1.35; white-space:pre-wrap; word-break:break-word;">${this._escapeHtml(json)}</pre>`;
    }

    return this._escapeHtml(String(value));
  }

  _renderActivityFieldChanges(fieldChanges) {
    if (!fieldChanges || typeof fieldChanges !== "object") return "";

    const entries = Object.entries(fieldChanges);
    if (!entries.length) return "";

    return entries.map(([fieldName, change]) => {
      const beforeValue = change && typeof change === "object" ? change.before : undefined;
      const afterValue = change && typeof change === "object" ? change.after : undefined;

      return `
        <div style="padding:10px 12px; border-bottom:1px solid rgba(0,0,0,0.08);">
          <div style="font-size:13px; font-weight:700; margin-bottom:6px; color:var(--primary-text-color);">${this._escapeHtml(this._formatAuditFieldPath(fieldName))}</div>
          <div style="display:grid; grid-template-columns: 64px minmax(0,1fr); gap:6px 10px; align-items:start;">
            <div style="font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase;">Before</div>
            <div style="font-size:13px; line-height:1.4; min-width:0; word-break:break-word;">${this._renderActivityDialogValue(beforeValue)}</div>
            <div style="font-size:12px; font-weight:700; color:var(--secondary-text-color); text-transform:uppercase;">After</div>
            <div style="font-size:13px; line-height:1.4; min-width:0; word-break:break-word;">${this._renderActivityDialogValue(afterValue)}</div>
          </div>
        </div>
      `;
    }).join("");
  }

  _normalizeActivityFieldChanges(details, item) {
    if (details?.field_changes && typeof details.field_changes === "object" && Object.keys(details.field_changes).length) {
      return this._pruneRedundantActivityFieldChanges(details.field_changes);
    }

    const derived = this._deriveActivityFieldChanges(details, item);
    if (Object.keys(derived).length) {
      return this._pruneRedundantActivityFieldChanges(derived);
    }

    const changedFields = Array.isArray(details?.changed_fields)
      ? details.changed_fields.filter((entry) => typeof entry === "string" && entry.trim())
      : [];

    if (!changedFields.length) {
      return {};
    }

    const fallback = {};
    changedFields.forEach((field) => {
      fallback[field] = {
        before: "Unknown",
        after: "Updated",
      };
    });
    return this._pruneRedundantActivityFieldChanges(fallback);
  }

  _pruneRedundantActivityFieldChanges(fieldChanges) {
    if (!fieldChanges || typeof fieldChanges !== "object") return {};

    const pruned = { ...fieldChanges };
    const keys = Object.keys(pruned);
    const keySet = new Set(keys);

    keys.forEach((key) => {
      const text = String(key || "");
      if (!text.startsWith("debounce.source.")) return;

      const suffix = text.slice("debounce.source.".length);
      const baseKey = `debounce.${suffix}`;

      if (keySet.has(baseKey)) {
        delete pruned[text];
      }
    });

    return pruned;
  }

  _deriveActivityFieldChanges(details, item) {
    if (!details || typeof details !== "object") return {};

    const output = {};
    const setChange = (field, before, after) => {
      const key = String(field || "").trim();
      if (!key) return;
      output[key] = { before, after };
    };

    Object.keys(details).forEach((key) => {
      if (!key.startsWith("from_")) return;
      const suffix = key.slice(5);
      const toKey = `to_${suffix}`;
      if (!(toKey in details)) return;
      setChange(suffix, details[key], details[toKey]);
    });

    Object.keys(details).forEach((key) => {
      if (!key.startsWith("old_")) return;
      const suffix = key.slice(4);
      const newKey = `new_${suffix}`;
      if (!(newKey in details)) return;
      setChange(suffix, details[key], details[newKey]);
    });

    Object.keys(details).forEach((key) => {
      if (!key.startsWith("before_")) return;
      const suffix = key.slice(7);
      const afterKey = `after_${suffix}`;
      if (!(afterKey in details)) return;
      setChange(suffix, details[key], details[afterKey]);
    });

    const actionText = String(
      details?.action
      || item?.title
      || item?.copy
      || ""
    ).toLowerCase();

    if (actionText.includes("add_tracker") && details?.entity_id) {
      setChange("tracker_entity_id", null, details.entity_id);
    }

    if (actionText.includes("remove_tracker") && details?.entity_id) {
      setChange("tracker_entity_id", details.entity_id, null);
    }

    if (actionText.includes("link_to_device") && (details?.device_id || details?.linked_device_id)) {
      setChange("linked_device_id", details?.previous_device_id ?? null, details?.device_id ?? details?.linked_device_id);
    }

    if (actionText.includes("unlink_from_device") && (details?.device_id || details?.linked_device_id)) {
      setChange("linked_device_id", details?.device_id ?? details?.linked_device_id, null);
    }

    if (actionText.includes("create_asset")) {
      if (details?.name) setChange("name", null, details.name);
      if (details?.asset_id) setChange("asset_id", null, details.asset_id);
    }

    if (actionText.includes("add_physical_document_location")) {
      if (details?.type) setChange("physical_document_type", null, details.type);
      if (details?.location) setChange("physical_document_location", null, details.location);
      if (details?.description) setChange("physical_document_description", null, details.description);
    }

    if (actionText.includes("tracker_state_update") && details?.new_state !== undefined) {
      setChange("tracker_state", details?.previous_state ?? null, details.new_state);
    }

    return output;
  }

  _formatAuditFieldPath(fieldPath) {
    const text = String(fieldPath || "").trim();
    if (!text) return "Field";

    const parts = text
      .split(".")
      .filter(Boolean)
      .map((part) => this._titleCase(String(part).replaceAll("_", " ")));

    return parts.length ? parts.join(" > ") : this._titleCase(text.replaceAll("_", " "));
  }

  _flattenAuditValuePaths(value, prefix = "") {
    if (value === null || value === undefined) {
      return { [prefix || "$"]: null };
    }

    if (Array.isArray(value)) {
      if (!value.length) {
        return { [prefix || "$"]: [] };
      }

      const out = {};
      value.forEach((entry, index) => {
        const nextPrefix = prefix ? `${prefix}.${index}` : String(index);
        Object.assign(out, this._flattenAuditValuePaths(entry, nextPrefix));
      });
      return out;
    }

    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (!keys.length) {
        return { [prefix || "$"]: {} };
      }

      const out = {};
      keys.forEach((key) => {
        const nextPrefix = prefix ? `${prefix}.${key}` : key;
        Object.assign(out, this._flattenAuditValuePaths(value[key], nextPrefix));
      });
      return out;
    }

    return { [prefix || "$"]: value };
  }

  _buildAuditFieldChanges(beforeValue, afterValue) {
    const beforeFlat = this._flattenAuditValuePaths(beforeValue);
    const afterFlat = this._flattenAuditValuePaths(afterValue);
    const keys = Array.from(new Set([...Object.keys(beforeFlat), ...Object.keys(afterFlat)])).sort();

    const changes = {};
    keys.forEach((key) => {
      const beforeLeaf = beforeFlat[key];
      const afterLeaf = afterFlat[key];
      if (JSON.stringify(beforeLeaf) === JSON.stringify(afterLeaf)) return;

      changes[key] = {
        before: beforeLeaf,
        after: afterLeaf,
      };
    });

    return changes;
  }

  _normalizeEnvironmentEventDetails(evt, previousRoomSnapshot) {
    const base = evt && typeof evt === "object" ? { ...evt } : { raw: evt };
    const currentSnapshot = base?.room_environment && typeof base.room_environment === "object"
      ? base.room_environment
      : null;

    const explicitFieldChanges = base?.field_changes && typeof base.field_changes === "object"
      ? base.field_changes
      : null;

    if (!explicitFieldChanges && previousRoomSnapshot && currentSnapshot) {
      const derived = this._buildAuditFieldChanges(previousRoomSnapshot, currentSnapshot);
      if (Object.keys(derived).length) {
        base.field_changes = derived;
        base.changed_fields = Object.keys(derived);
      }
    }

    const eventType = String(base?.type || "").toLowerCase();
    if (eventType === "environment_risk_state_changed") {
      const prior = base?.prior_state;
      const next = base?.new_state;
      if (prior !== undefined || next !== undefined) {
        const riskDiff = {
          before: prior ?? "Unknown",
          after: next ?? "Unknown",
        };

        const currentFieldChanges = base.field_changes && typeof base.field_changes === "object"
          ? { ...base.field_changes }
          : {};

        if (!currentFieldChanges.risk_state) {
          currentFieldChanges.risk_state = riskDiff;
        }

        base.field_changes = currentFieldChanges;
        const currentChanged = Array.isArray(base.changed_fields)
          ? base.changed_fields.filter((entry) => typeof entry === "string")
          : [];
        if (!currentChanged.includes("risk_state")) {
          currentChanged.unshift("risk_state");
        }
        base.changed_fields = currentChanged;

        if (!base.summary && prior !== next) {
          base.summary = `Risk changed from ${prior ?? "Unknown"} to ${next ?? "Unknown"}`;
        }
      }
    }

    return base;
  }

  _openAddAssetDialog(roomId) {
    if (!roomId) return;

    const defaultLabelIds = this._getDefaultLabelIds();

    this._assetDraft = {
      name: "",
      area_id: roomId,
      device_id: null,
      label_ids: [...defaultLabelIds],
      labels_touched: false,
    };

    const dialog = document.createElement("ha-dialog");
    dialog.open = true;

    dialog.innerHTML = `
      <style>
        .ai-dialog-shell {
          min-width: 520px;
          max-width: 640px;
        }

        .ai-dialog-title {
          font-size: 18px;
          font-weight: 700;
          padding: 20px 24px 8px 24px;
          color: var(--primary-text-color);
        }

        .ai-dialog-body {
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 8px 24px 16px 24px;
        }

        .ai-dialog-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .ai-dialog-field-label {
          font-size: 12px;
          font-weight: 600;
          color: var(--secondary-text-color);
          letter-spacing: 0.02em;
        }

        .ai-dialog-input {
          width: 100%;
          min-height: 52px;
          box-sizing: border-box;
          padding: 14px 16px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 16px;
          outline: none;
        }

        .ai-dialog-select {
          width: 100%;
          min-height: 52px;
          box-sizing: border-box;
          padding: 0 16px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 16px;
          outline: none;
          appearance: auto;
        }

        .ai-dialog-select:focus {
          border-color: var(--primary-color);
          box-shadow: 0 0 0 1px var(--primary-color);
        }

        .ai-dialog-actions {
          display: flex;
          justify-content: flex-end;
          align-items: center;
          gap: 12px;
          padding: 8px 24px 24px 24px;
        }

        .ai-dialog-secondary-btn {
          appearance: none;
          border: none;
          background: transparent;
          color: var(--primary-color);
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          padding: 10px 4px;
        }

        .ai-dialog-primary-btn {
          appearance: none;
          border: none;
          border-radius: 20px;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          padding: 10px 18px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,0.2));
        }

        .ai-dialog-primary-btn:disabled {
          opacity: 0.55;
          cursor: default;
        }

      </style>

      <div class="ai-dialog-shell">
        <div class="ai-dialog-title">Add Asset</div>

        <div class="ai-dialog-body">

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label" for="ai-asset-name">Name</label>
            <input
              id="ai-asset-name"
              class="ai-dialog-input"
              type="text"
              placeholder="Enter asset name"
              autocomplete="off"
            />
          </div>

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label">Asset Type</label>
            <select id="ai-asset-type" class="ai-dialog-select">
              <option value="">Select asset type</option>
              <option value="artwork">Artwork</option>
              <option value="rare_book">Rare Book</option>
              <option value="collectable">Collectable</option>
              <option value="electronics">Electronics</option>
              <option value="infrastructure">Infrastructure</option>
              <option value="furniture">Furniture</option>
              <option value="instrument">Instrument</option>
            </select>
          </div>

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label" for="ai-asset-area">Room</label>
            <ha-area-picker id="ai-asset-area"></ha-area-picker>
          </div>

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label" for="ai-asset-device">Existing Device (optional)</label>
            <select id="ai-asset-device" class="ai-dialog-select">
              <option value="">None</option>
            </select>
          </div>

          <div class="ai-dialog-field">
            <label class="ai-dialog-field-label" for="ai-asset-labels">Labels</label>
            <ha-labels-picker id="ai-asset-labels"></ha-labels-picker>
          </div>

        </div>

        <div class="ai-dialog-actions">
          <button type="button" id="ai-cancel" class="ai-dialog-secondary-btn">
            Cancel
          </button>

          <button type="button" id="ai-save" class="ai-dialog-primary-btn" disabled>
            Create Asset
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    setTimeout(() => {
      const nameInput = dialog.querySelector("#ai-asset-name");
      const typeSelect = dialog.querySelector("#ai-asset-type");
      const areaPicker = dialog.querySelector("#ai-asset-area");
      const devicePicker = dialog.querySelector("#ai-asset-device");
      const labelPicker = dialog.querySelector("#ai-asset-labels");
      const saveBtn = dialog.querySelector("#ai-save");
      const cancelBtn = dialog.querySelector("#ai-cancel");

      if (!nameInput || !typeSelect || !areaPicker || !devicePicker || !labelPicker || !saveBtn || !cancelBtn) {
        console.error("Add Asset dialog failed to initialize required controls");
        return;
      }

      // Attach hass to HA-native controls
      areaPicker.hass = this._hass;
      devicePicker.hass = this._hass;
      labelPicker.hass = this._hass;
      labelPicker._labels = this._labelRegistry || [];
      labelPicker.value = [...defaultLabelIds];

      // Default room
      areaPicker.value = roomId;

      // Initial device list
      this._populateDeviceSelect(devicePicker, roomId);
      devicePicker.value = null;   // âœ… REQUIRED for ha-combo-box to render

      const updateSaveState = () => {
        const rawName = String(nameInput.value || "").trim();
        const selectedType = String(typeSelect.value || "").trim();

        const hasName = !!rawName;
        const hasType = !!selectedType;
        const duplicateName = hasName && this._isDuplicateAssetName(rawName);

        // Keep draft state synchronized with actual UI values
        this._assetDraft.name = rawName;
        this._assetDraft.asset_type = selectedType || null;

        saveBtn.disabled = !hasName || !hasType;

        nameInput.setCustomValidity(
          duplicateName ? "An asset with this name already exists" : ""
        );

        // Optional but very helpful while testing
        console.log("Add Asset validation", {
          rawName,
          selectedType,
          hasName,
          hasType,
          duplicateName,
          disabled: saveBtn.disabled
        });
      };

      // Name binding
      nameInput.addEventListener("input", () => {
        updateSaveState();
      });

      typeSelect.addEventListener("change", () => {
        updateSaveState();
      });

      // Area change -> refresh devices
      areaPicker.addEventListener("value-changed", (ev) => {
        const newArea = ev.detail?.value || roomId;
        this._assetDraft.area_id = newArea;

        this._populateDeviceSelect(devicePicker, newArea);

        const devices = this._getDevicesForArea(newArea);
        if (!devices.find((d) => d.value === this._assetDraft.device_id)) {
          this._assetDraft.device_id = null;
          devicePicker.value = "";
        }
      });

      // Device selection
      devicePicker.addEventListener("change", (e) => {
        const selectedId = e.target.value || null;
        this._assetDraft.device_id = selectedId;

        // Auto-fill name if empty
        if (!String(nameInput.value || "").trim() && selectedId) {
          const selected = this._getDevicesForArea(this._assetDraft.area_id)
            .find((d) => d.value === selectedId);

          if (selected) {
            nameInput.value = selected.label;
            updateSaveState();
          }
        }
      });

      // Labels
      labelPicker.addEventListener("value-changed", (e) => {
        this._assetDraft.labels_touched = true;
        this._assetDraft.label_ids = e.detail?.value || [];
      });

      cancelBtn.onclick = () => dialog.remove();

      saveBtn.onclick = async () => {
        await this._handleCreateAsset(dialog);
      };

      updateSaveState();
      nameInput.focus();

      this._applyLabelRegistryToPickers(dialog);
    }, 0);

    dialog.addEventListener("closed", () => {
      dialog.remove();
    });
  }

  _getDevicesForArea(areaId) {
    return (this._deviceRegistry || [])
      .filter(d => d.area_id === areaId)
      .map(d => ({
        value: d.id,
        label: d.name_by_user || d.name || d.id
      }));
  }

  _populateDeviceSelect(selectEl, areaId) {
    if (!selectEl) return;

    const devices = this._getDevicesForArea(areaId);

    selectEl.innerHTML = `
      <option value="">None</option>
      ${devices.map((d) => `
        <option value="${this._escapeHtml(d.value)}">
          ${this._escapeHtml(d.label)}
        </option>
      `).join("")}
    `;
  }  

  /* ===========================
  ASSET ID / NAME HELPERS
  =========================== */

  _slugifyAssetId(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/__+/g, "_");
  }

  _getExistingAssetNames() {
    return this._getAssetEntities()
      .map((entity) => String(entity.attributes?.name || "").trim().toLowerCase())
      .filter(Boolean);
  }

  _getExistingAssetIds() {
    return this._getAssetEntities()
      .map((entity) => String(entity.attributes?.asset_id || "").trim().toLowerCase())
      .filter(Boolean);
  }

  _generateUniqueAssetIdFromName(name) {
    const base = this._slugifyAssetId(name);
    if (!base) return "";

    const existingIds = new Set(this._getExistingAssetIds());

    if (!existingIds.has(base)) {
      return base;
    }

    let suffix = 2;
    while (existingIds.has(`${base}_${suffix}`)) {
      suffix += 1;
    }

    return `${base}_${suffix}`;
  }

  _isDuplicateAssetName(name) {
    const normalized = String(name || "").trim().toLowerCase();
    if (!normalized) return false;

    const existingNames = new Set(this._getExistingAssetNames());
    return existingNames.has(normalized);
  }

  _formatLocalDateTime(value) {
    if (!value) return "â€”";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return String(value);

    try {
      return dt.toLocaleString();
    } catch (e) {
      return String(value);
    }
  }

  _stateColor(value) {
    const normalized = String(value || "").toUpperCase();
    if (normalized === "GOOD" || normalized === "GREEN") return "#2e7d32";
    if (normalized === "PARTIAL" || normalized === "YELLOW" || normalized === "AMBER") return "#f9a825";
    if (normalized === "RED") return "#c62828";
    if (normalized === "UNCONFIGURED") return "#9e9e9e";
    if (normalized === "STALE") return "#9e9e9e";
    return "#777";
  }

  _confidenceColor(value) {
    const normalized = String(value || "").toUpperCase();
    if (normalized === "HIGH") return "#2e7d32";
    if (normalized === "MEDIUM") return "#f9a825";
    if (normalized === "GOOD") return "#2e7d32";
    if (normalized === "PARTIAL") return "#f9a825";
    if (normalized === "LOW") return "#ef6c00";
    if (normalized === "STALE") return "#c62828";
    return "#777";
  }

  _compactReason(value) {
    const text = String(value || "").trim().replace(/\.$/, "");
    if (!text) return "Environmental Risk";
    return text.length > 32 ? `${text.slice(0, 29)}â€¦` : text;
  }


  _titleCase(value) {
    return String(value || "").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  _escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
};

globalThis.AssetIntelligenceApp = AssetIntelligenceApp;

if (!customElements.get("asset-intelligence-app")) {
  customElements.define("asset-intelligence-app", AssetIntelligenceApp);
}
