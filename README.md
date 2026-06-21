<img width="1536" height="1024" alt="banner_light" src="https://github.com/user-attachments/assets/4cc5e06c-027b-4f5b-972a-d35df0e19410" />

## How It Works
<img width="1536" height="1024" alt="SystemFlowOverview2" src="https://github.com/user-attachments/assets/3dda4d61-1ca3-41c8-8a44-c799c40e7722" />


# Asset Intelligence

**What if your home didn’t just monitor conditions… but understood what those conditions affect?**

Asset Intelligence extends Home Assistant with a new concept:

👉 **Assets** — the things your home exists to support, protect, and preserve

This transforms your home from:

> monitoring devices  
into  
> **understanding what matters**

---

## 🚀 Start Here

To understand how the system works:

- 👉 [Concepts](https://github.com/tom-tagmdl/asset_intelligence/wiki/Concepts)
- 👉 [Getting Started](https://github.com/tom-tagmdl/asset_intelligence/wiki/Getting-Started)
- 👉 [System Flow Overview](https://github.com/tom-tagmdl/asset_intelligence/wiki/System-Flow-Overview)

---

## ✨ At a Glance

Asset Intelligence enables your home to:

- Understand what it contains (assets as first-class entities)
- Evaluate whether conditions are appropriate
- Track custody, movement, and loan history
- Maintain documents, provenance, and insurance records
- Provide explainable risk and advisory insights
- Support room-aware and audience-aware experiences

---

## 🧠 The Missing Piece in Smart Homes

Today’s smart homes answer:

- “What is the temperature?”
- “Is the light on?”
- “Which device is in this room?”

But not:

- **“Are conditions appropriate for what’s here?”**
- **“Is anything at risk?”**
- **“Where is this, and who has it?”**
- **“Do I have documentation for this?”**

Asset Intelligence enables your home to answer those questions.

---

## 🧩 The System Model

Asset Intelligence introduces a simple, powerful model:

- **Areas (Rooms)** → where things are  
- **Assets (Devices)** → what exists  
- **Labels** → what kind of things  
- **Environment** → what’s happening  
- **Risk & Advisory** → what it means  

---

## 🔄 How It Works

Sensors → Environment → Evaluation → Risk → Advisory → Activity → Automation

- Sensors capture conditions  
- The system evaluates those conditions against asset requirements  
- Risk is determined  
- Advisory explains what matters  
- Activity records what changed  
- Automations (optional) take action  

---

## 🧾 What Is an Asset?

An asset is anything that matters.

### Device-backed assets
- TVs, Sonos, networking gear, appliances

### Non-device assets
- Artwork, instruments, furniture, collections, documents

Each asset is implemented as a **Home Assistant device**, enriched with:

- environmental requirements  
- documentation and provenance  
- custody and governance  
- history and audit data  

---

## 🏛️ Stewardship, Not Just Automation

Asset Intelligence brings concepts from:

- museums  
- archives  
- collections  
- estate inventories  

into the home.

It introduces:

- structured asset inventory  
- environmental stewardship  
- audit and lifecycle tracking  
- custody and loan workflows  
- documentation and provenance  

This is not just automation.

👉 It is **stewardship**

---

## 🧠 Environmental Intelligence (Assets + People)

Asset Intelligence models the environment in a structured way across:

- climate  
- light  
- air quality  
- particulates  
- biological conditions  
- structural context  

This allows the home to evaluate:

### For assets
- Is this environment safe for artwork, instruments, electronics?

### For people
- Is air quality healthy?
- Is CO₂ elevated?
- Is the room becoming unsafe?

---

## 🔬 What Makes This Different

- Assets define what conditions matter  
- Rooms define how conditions are measured  
- The system compares the two  

> “Are these conditions appropriate for what is in this room?”

---

## 🚨 Calm, Explainable Awareness

Instead of alerts alone, the system provides:

- risk states (Green / Amber / Red)  
- advisory explanations  
- missing data warnings  
- event history  

This creates:

👉 **awareness, not noise**

---

## 📚 Documents, Provenance, Insurance

Each asset can hold:

- receipts and appraisals  
- manuals and warranties  
- insurance references  
- provenance records  
- physical document locations  

Documents are stored in **external storage (NAS recommended)** and linked into the system.

---

## 🔐 Custody and Movement

Track:

- ownership status  
- loans and returns  
- custody transfers  
- storage location  
- agreements and responsibility  

---

## 🧱 Architecture Overview

Asset Intelligence uses a layered architecture:

- **Environment** → sensing  
- **Evaluation** → decision engine  
- **Coordinator** → runtime state, events, advisory  
- **Entities** → read-only projections  

👉 See: ../../wiki/Architecture-Overview

---

## 🎙️ Concierge & Future Experience

Asset Intelligence enables:

- room-aware voice interactions  
- audience-specific descriptions  
- guided experiences  
- contextual explanations  

The home can eventually explain:

- what is in a room  
- why it matters  
- what is happening to it  

---

## 🏡 Homes That Behave Well

Asset Intelligence is built around:

> **homes that understand what matters and act accordingly**

Not just:

- convenience  
- automation  

But:

- awareness  
- responsibility  
- explanation  

---

## 🚀 What This Enables

Asset Intelligence transforms Home Assistant into:

- an environmental awareness system  
- an asset management system  
- a documentation system  
- a stewardship system  

---

The result:

> **A home that behaves with intention.**

---

## Repository Structure

| Path | Purpose |
|------|---------|
| `__init__.py` | Integration entry point. Registers all services, sets up config entries, and wires the coordinator, storage, and document view into HA. |
| `manifest.json` | HA integration metadata: domain, version, config flow flag, IoT class, and codeowner declaration. |
| `quality_scale.yaml` | Tracks which Home Assistant Quality Scale rules have been satisfied for Bronze → Platinum progression. |
| `const.py` | Shared constants used across the integration (domain name, signal names, service names). |
| `models.py` | Core data models: `Asset`, `CustodyRecord`, `LoanRecord`, and supporting types. |
| `coordinator.py` | `AssetIntelligenceCoordinator` — owns the runtime state, triggers refreshes, and dispatches change signals to entities. |
| `asset_entity.py` | Base entity class shared by sensors and binary sensors; resolves the asset from coordinator data. |
| `sensor.py` | Sensor entities: asset count, asset list, room environment readings. |
| `binary_sensor.py` | Binary sensor entities: risk state and advisory flags per asset. |
| `config_flow.py` | UI-driven config flow for setting up and reconfiguring the integration. |
| `storage.py` | `AssetStore` — reads and writes asset data to HA's persistent JSON storage. |
| `document_models.py` | Data classes for document records (receipts, appraisals, manuals, provenance). |
| `document_storage.py` | `DocumentStorage` — manages file-level operations for linked asset documents on NAS/share. |
| `environment.py` | Parses and normalises room environment sensor data into structured readings. |
| `evaluation.py` | Evaluates environmental conditions against per-asset requirements to produce risk states. |
| `advisory.py` | Generates human-readable advisory text from evaluation results. |
| `validation.py` | Input validation helpers used by service handlers to reject malformed payloads early. |
| `panel.py` | Registers the custom frontend panel with HA's HTTP layer. |
| `strings.json` | Translatable UI strings for the config flow and services. |
| `services.yaml` | HA service schema declarations (fields, descriptions) for all registered services. |
| `translations/en.json` | English translations for config flow, services, and entity states. |
| `helpers/document_resolver.py` | Resolves document paths and validates file availability against configured storage. |
| `services/document_retrieval.py` | Service handler for document fetch/download operations. |
| `frontend/panel_v5.js` | Compiled frontend panel served to the HA UI for asset management views. |
| `frontend/src/` | Source for the frontend panel (components, pages, views). |
| `docs/asset_intelligence.md` | End-user documentation: concepts, installation, removal, and supported actions. |
| `docs/asset_intelligence_examples.md` | Usage examples and automation patterns for common asset intelligence scenarios. |
| `docs/asset_intelligence_troubleshooting.md` | Troubleshooting guide for common setup and runtime issues. |
| `docs/quality_scale_audit.md` | Platinum audit log: evidence mapping for each Quality Scale requirement. |
| `brand/` | Integration branding assets (icons, banners, logos) for the HA brand registry. |
| `tests/conftest.py` | Shared pytest fixtures for all test modules. |
| `tests/test_config_flow.py` | Tests for UI config flow: setup, validation, and single-entry enforcement. |
| `tests/test_setup.py` | Tests for integration startup and platform loading. |
| `tests/test_unload.py` | Tests for config entry unloading and resource cleanup. |
| `tests/test_services.py` | Tests for service handlers: document upload, attach, delete, and asset mutations. |
| `tests/test_documents.py` | Unit tests for document record helpers and rebuild logic. |
| `tests/test_history.py` | Tests for asset history payload construction. |
| `tests/test_diagnostics.py` | Tests for the HA diagnostics payload output. |
| `tests/test_entity_metadata.py` | Tests for sensor and binary sensor entity metadata (name, unique ID, device class). |
| `tests/test_validation.py` | Tests for input validation helpers. |
| `tests/run_quality_gate.ps1` | PowerShell script that runs the full pytest suite with coverage gate (≥85%) and emits artifacts. |
| `tests/run_smoke_tests.ps1` | Lightweight smoke run targeting the most critical service tests only. |
| `tests/_validate_services.py` | Standalone script to validate `services.yaml` schema against registered service definitions. |
| `QUALITY_SCALE_CHECKLIST.md` | Working checklist tracking Bronze → Platinum progress with phase-by-phase implementation plan. |
