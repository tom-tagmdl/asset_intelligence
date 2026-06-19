<img width="1536" height="1024" alt="banner_dark" src="https://github.com/user-attachments/assets/b3dd3107-7fea-4daa-8ec1-8ce304e6b985" />


What if your home didn’t just monitor conditions…
but understood what those conditions affect?**

Home Assistant is excellent at modeling devices, entities, areas, and people.

But homes are not defined only by devices.

They are defined by what they contain —  
the objects, collections, systems, documents, and people the home exists to support, protect, and preserve.

**Asset Intelligence** introduces **Assets** as a first-class concept in Home Assistant, enabling the home to understand what it contains, evaluate whether current conditions are appropriate, preserve documentation and history, track custody and movement, and surface information in ways appropriate to guests, owners, insurers, and future Concierge voice experiences. 


## ✨ At a Glance

Asset Intelligence enables your home to:

- Understand what it contains (assets as first-class entities)
- Protect those assets through environmental awareness
- Maintain documentation, provenance, and insurance records
- Track custody, movement, and loan history
- Provide audience-aware descriptions (guest, owner, insurance)
- Evaluate whether conditions are safe for both assets and people
- Present information through room-aware Concierge voice interactions

---

## 🧠 The Missing Piece in Smart Homes

Today’s smart homes answer questions like:

- “What is the temperature?”
- “Is the light on?”
- “Is anyone home?”
- “Which device is in this room?”

But homes also need to answer:

- **“Are the conditions appropriate for what is in this room?”**
- **“Is anything at risk right now?”**
- **“Where is this item, and who has custody of it?”**
- **“Do I have the documents, appraisal, and insurance references for this?”**
- **“Is my home environment safe for me?”**

Asset Intelligence expands Home Assistant so the home can answer those questions with structure, context, and memory. 
---

## 🧾 What Is an Asset?

An **Asset** is anything in the home that has value, meaning, importance, or operational relevance.

### Device-backed assets
Examples:

- Televisions
- Sonos speakers
- Networking equipment
- NAS systems
- UPS battery backups
- Appliances

### Non-device assets
Examples:

- Artwork
- Antiques
- Rare books
- Musical instruments
- Furniture
- Collections
- Documents and provenance records

An asset may be linked to one or more Home Assistant devices and entities, but it is **not limited to the device model**. It adds meaning, stewardship, requirements, records, and history that go beyond “what entity reports data.” The service layer already supports device linking / unlinking, tracker association, and asset updates through the Home Assistant integration surface. 
---

## 🏛️ Stewardship & Governance for the Home

Asset Intelligence brings governance patterns normally associated with:

- museums
- libraries
- archives
- private collections
- estate inventories

into the home.

Those institutions do not simply store objects — they **document, classify, preserve, track, and govern them over time**.

Asset Intelligence applies the same principles locally inside Home Assistant:

- structured asset inventory
- environmental stewardship
- document and media attachment
- lifecycle audit trail
- custody tracking
- loan workflows
- inventory export
- insurance readiness

This is not just automation. It is **stewardship**. 
---

## 📚 A Centralized Home Asset System of Record

Asset Intelligence is designed to become the home’s **central system of record** for what matters.

Each asset can hold:

- identity and classification
- area / room location
- optional device linkage
- multiple descriptions for different audiences
- environmental requirements
- attached files and media references
- appraisal / insurance references
- physical document locations
- custody and loan status
- audit history
- exportable inventory data

The existing service surface already supports asset creation and updates, document attachment and upload, physical document location recording, environment requirement setting, room environment configuration, custody updates, loan out / loan in, and inventory export. 

---

## 🧠 Audience-Specific Descriptions

Not every description should be shown to every audience.

Your design notes explicitly call for **three description layers**:

- **Guest Description** — safe-to-share story text
- **Owner Description** — personal meaning and private context
- **Insurance / Legal Description** — factual and documentary record

That means the same asset can be:

- welcoming and informative for guests
- useful and personal for owners
- precise and claim-ready for insurance or legal needs

This supports a calm and security-aware posture: the home can speak about what something is without exposing value, storage details, or sensitive metadata to the wrong audience. Your OneNote design notes explicitly describe these three built-in descriptions and tie them to an owner-vs-guest safety posture. 

---

## 🧑‍⚕️ Environmental Intelligence — for Assets and for People

Asset Intelligence introduces a canonical environmental model so the same language is used consistently across:

- room sensing
- room configuration
- environmental evaluation
- asset requirements
- advisories and warnings

That model includes environmental domains such as climate, light, air quality, particulates, biological conditions, structural context, control context, and external environment. Your current validation and environment design materials explicitly describe a structured room environment model, confidence scoring, and environment-driven evaluation behavior. 

This enables two new classes of questions:

### For assets
- Is this environment safe for artwork, instruments, antiques, books, electronics, or infrastructure?

### For people
- Is the air quality appropriate?
- Is CO₂ elevated?
- Are VOCs or pollutants creating an unhealthy environment?

Asset Intelligence is designed to let the home evaluate conditions in context — not only whether a sensor crossed a number, but **what that number means for what and who is in the room**. The environmental intelligence design documents explicitly describe confidence handling, graceful degradation for missing signals, and evaluation of room conditions against asset requirements. 
---

## 🔬 What Makes This Different

### Assets define environmental needs
Each asset can define a proper operating or preservation environment.

### Rooms define how conditions are measured
Each room can be configured with the sensors, signal sources, and aggregation rules used to construct its environment model.

### The home can compare the two
Asset Intelligence can then ask:

> **“Are these conditions appropriate for what this room contains?”**

And when they are not, the system can raise:

- warnings
- advisories
- risk state changes
- event history

That is the difference between a home that simply reports data and a home that understands consequences. Your room configuration and asset requirement services are explicitly part of the current service contract, and your design materials describe environment confidence, evaluation, and event-driven policy behavior. 

---

## 🚨 Alerts, Warnings, and Tolerance Awareness

Asset Intelligence is built so that rooms and assets can move **into** and **out of** tolerance in a structured, explainable way.

That means the system can surface:

- room conditions that are incomplete, degraded, or outside expected ranges
- assets that are currently at risk
- environmental changes that matter over time
- warnings that are informative instead of noisy
- advisories that suggest proportionate action

This is not designed as “alert spam.” It is designed as **calm, explainable awareness** — aligned with a “Homes That Behave Well” philosophy. The architecture applies deterministic evaluation, environment risk state tracking, explainability, and keeps the advisory logic separate from raw sensing. 

---

## 🧾 Documentation, Provenance, and Insurance Readiness

Assets are not only physical things. They are accompanied by evidence and history.

Asset Intelligence already supports:

- attaching document references
- uploading files into Home Assistant media storage
- recording physical document locations
- rebuilding document summaries
- exporting inventory

This makes it possible to centralize:

- receipts
- appraisals
- manuals
- warranties
- insurance policy references
- loan agreements
- provenance records
- condition reports
- installation instructions
- maintenance history

Document management is handled through NAS storage attached to Home Assistant and isn't available if NAS storage isn't available.  Asset Intelligence builds a human readable folder structure enabling easy access to these digital documents.

That means the home can become a trusted place not only to monitor what an asset experiences, but also to retain the records needed to:

- prove ownership
- support claims
- answer appraiser questions
- prepare estate or insurance inventories
- document preservation choices over time

---

## 🔐 Custody, Chain of Custody, and Loan Workflows

Some assets remain in the home.  
Some are stored off-site.  
Some are loaned out.  
Some return.

Asset Intelligence already includes the service surface to support that governance model.

The current service contract includes:

- **Set Custody Status**
- **Record Loan Out**
- **Record Loan In**
- supporting fields such as holder, location detail, effective date, agreement URI, insurance responsibility, expected return date, and return notes. 

This means the system can track:

- whether an item is owned on-site
- who currently has custody
- whether it is in storage, on loan, in transit, or returned
- what agreement governs the movement
- what insurance responsibility applies while it is away

For collectors, heirs, households with high-value objects, and anyone who lends or stores items, this is a foundational capability.

---

## 🧱 Architecture Overview

Asset Intelligence is built as a Home Assistant custom integration with a local-first architecture.

Core elements include:

- Home Assistant-native storage using `Store`
- service layer for asset and room operations
- Home Assistant device and entity registry linkage
- room environment configuration
- canonical environmental model
- coordinator-driven runtime evaluation
- audit and event-oriented state updates
- media-backed document attachment

The system is architected with  `__init__.py` as the service orchestration layer, the store as the system of record, and the coordinator as the runtime orchestration layer. 
---

## 🔌 Leverages Existing Home Assistant Integrations

Asset Intelligence does not require inventing a new sensing ecosystem.

Instead, it is designed to leverage the rich set of sensors and integrations already present in Home Assistant, such as:

- room temperature and humidity sensors
- light and UV sensors
- air quality sensors
- particulate sensors
- leak sensors
- weather and sun integrations
- device-linked telemetry from existing platforms

Room environment configuration is service-based and maps existing Home Assistant entities into the canonical room model using configured sensor lists and aggregation rules. Your room-environment service and validation serve as a room setup backend that persists sensor sources and aggregates them into normalized room state. 

That means you can benefit from Asset Intelligence without replacing the sensors and integrations you already trust.

---

## 🗂️ Example Asset (Complete Stewardship Model)

```yaml
asset:
  asset_id: art_rare_oil_painting_001
  name: "Rare Oil Painting, 17th Century"

  area_id: living_room

  labels:
    - artwork
    - framed
    - insured
    - high_value

  linked_device_id: null
  linked_entity_ids: []

  descriptions:
    guest: "A 17th-century oil painting in a period gold leaf frame."
    owner: "Purchased as part of the family collection and displayed in the living room."
    insurance: "Oil on canvas, 1600s, period gold leaf wood frame, appraised and insured."

  valuation:
    current_estimated_value: 250000
    valuation_date: "2026-05-01"
    appraisal_reference: "media-source://media_source/local/assets/art_rare_oil_painting_001/appraisal_2026.pdf"

  environment_requirements:
    climate:
      temperature:
        min: 65
        max: 72
      humidity:
        min: 45
        max: 55
    light:
      lux:
        min: 0
        max: 50
      uv:
        min: 0
        max: 0.5
    air_quality:
      voc:
        min: 0
        max: 200
      ozone:
        min: 0
        max: 5
      no2:
        min: 0
        max: 20
    particulates:
      pm2_5:
        min: 0
        max: 12
      pm10:
        min: 0
        max: 25

  documents:
    - type: appraisal
      uri: "media-source://media_source/local/assets/art_rare_oil_painting_001/appraisal_2026.pdf"
    - type: insurance_policy
      uri: "media-source://media_source/local/assets/art_rare_oil_painting_001/insurance_policy.pdf"
    - type: provenance_record
      uri: "media-source://media_source/local/assets/art_rare_oil_painting_001/provenance_record.pdf"

  physical_documents:
    - type: certificate_of_authenticity
      location: safe_deposit_box
      description: "Original certificate stored off-site"

  custody:
    status: owned_on_site
    holder: null
    location_detail: "Living Room – north wall"
    notes: null
    effective_at: "2026-05-24T14:30:00"

  loans: []

  audit:
    created_at: "2026-05-24T18:32:00"
    updated_at: "2026-06-03T17:30:00"
    created_by: "Tom Grounds"
    updated_by: "Tom Grounds"
````

This example reflects the combined themes already present in your service model and design notes: descriptions, document attachment, physical document references, environmental requirements, custody, and audit-oriented stewardship. 

***

## 🏡 Example Use Case: Protecting Artwork in the Living Room

A framed oil painting hangs in the living room.

Asset Intelligence models it as an asset with:

* environmental requirements
* documentation
* insurance references
* location and custody state

As the sun shifts in the afternoon:

* lux rises
* UV risk increases
* direct exposure aligns with the artwork’s placement
* the room environment drifts out of tolerance

The home now understands something deeper than “it is bright in here.”

It understands:

> **“This light is affecting an object that should be protected.”**

The system can then:

* evaluate that change against the painting’s tolerance
* surface a warning, advisory or start an automation
* log the environmental issue against the asset
* support a future guided explanation of what that work is and why it is being protected

That is a different class of smart home behavior.

***

## 🖥️ Example Use Case: Protecting Critical Infrastructure

A hallway closet contains:

* router
* switch
* NAS
* UPS

Those are not just “devices.” They are critical household infrastructure.

Asset Intelligence can assign them:

* environmental requirements
* labels like `network`, `critical`, `electronics`
* documentation references
* protective context

When heat rises in that closet, the home can move from:

> “The closet is warm”

to:

> **“Critical infrastructure is operating outside ideal conditions.”**

to:

> Turning on an exhaust fan

It can then warn proportionally, preserve the history, and support future operational and insurance documentation. 

***

## 🎸 Example Use Case: Preserving Musical Instruments

A music room contains:

* acoustic guitars
* a piano
* a violin

These are sensitive materials, not just possessions.

Asset Intelligence lets the home understand:

* swings in humidity
* preservation thresholds
* repeated seasonal drift
* what those conditions mean for specific assets

Instead of saying:

> “Humidity is low”

the home can understand:

> **“These instruments are being exposed to conditions that may degrade tone, structure, and longevity.”**

That creates a framework for quiet, intelligent stewardship and future guided explanations of the instruments themselves which can lead to informed automations to maintin the proper environment — what they are, why they matter, and what they require.

***

## 🧑‍⚕️ Example Use Case: Is My Home Safe for Me?

Environmental intelligence is not only for collectibles.

It also enables the home to ask:

> **“Is this room’s environment safe and healthy for the person in it?”**

Because the same room model can represent:

* CO₂
* VOCs
* particulates
* noise
* temperature and humidity
* broader air quality indicators

the home can move from reporting raw numbers to interpreting whether a room is becoming unhealthy or uncomfortable for human occupants.

This means the same foundation used to protect artwork or infrastructure can also help answer:

* is the air stale?
* is ventilation needed?
* is this room drifting into an unhealthy condition?

That broadens Asset Intelligence from preservation to **human environmental awareness**.

***

## 🎙️ Concierge Voice & Guided Tour Experience

Because each asset can hold structured descriptions, documentation references, and governance state, Asset Intelligence provides the foundation for rich room-aware voice experiences.

The broader design notes explicitly call out future support for voice / Concierge patterns such as:

* “What art/assets are in this room?”
* “What is valuable in this room?”
* room-safe listing for guests
* owner-only detail where appropriate

Your Concierge architecture already assumes room-aware, deterministic voice behavior and room-specific description of what the room can sense and do. The asset model gives Concierge something richer to present: **what the room contains and why it matters**.

That means the home can eventually become something like a guided museum tour:

* A guest might hear a safe description:
  * “This is a 17th-century oil painting in a period gold leaf frame.”
* An owner might ask for more:
  * provenance
  * appraisal reference
  * insurance notes
  * environmental status
* The home can tailor the story to the audience

This is one of the most distinctive outcomes of the model: the home is not only monitoring its contents — it can **present them thoughtfully**.

***

## 🧭 Homes That Behave Well

Asset Intelligence is designed as a core component of **Homes That Behave Well**.

That means a home that:

* knows what it contains
* understands what conditions mean
* tracks history and stewardship over time
* reduces noise and increases meaning
* acts with awareness of consequences

Most smart homes optimize for convenience.

Asset Intelligence introduces a different priority:

> **responsibility**

The home becomes not only more intelligent —  
it becomes more careful, more explainable, and more aligned with what matters.

***

## 🚀 What This Enables

Asset Intelligence transforms Home Assistant from:

> a system that monitors devices

into:

> **a system that understands the home**

That includes:

* environment-aware stewardship
* documentation and provenance management
* insurance and export readiness
* custody and loan governance
* room-aware and audience-aware storytelling
* alerts and warnings when assets or people are exposed to unsafe conditions

The result is not simply a smarter home.

It is a home that behaves with intention.

```
