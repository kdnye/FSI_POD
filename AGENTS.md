# AI Agent & Developer Directives

## Purpose
This document establishes guardrails for AI coding assistants and developers contributing to the FSI repository. Preserve these patterns to maintain system stability and architectural alignment.

See also: [FSI_ECOSYSTEM.md](./FSI_ECOSYSTEM.md) for the full app portfolio and shared DB schema map.

## Architectural Directives

### 1. Frontend & Device APIs
* **DO NOT** suggest or implement React Native, Flutter, or Swift/Kotlin wrappers. 
* **DO** utilize standard HTML5 Web APIs for hardware access (Camera, GPS, Canvas).
* **DO** keep external JavaScript dependencies minimal and CDN-delivered.

### 2. Backend & Server Execution
* **DO NOT** implement WebSockets, Socket.IO, or async worker frameworks (e.g., Celery, Gevent) without explicit architectural review. The system must run on standard synchronous Gunicorn threads.
* **DO** use short-polling for real-time dashboard updates.
* **DO** keep data serialization lightweight. Return standard JSON from API endpoints.

### 3. Storage & Authentication
* **DO NOT** hardcode GCP Service Account JSON keys or pass them via `.env` for GCS authentication.
* **DO** rely entirely on Application Default Credentials (ADC) provided natively by the Google Cloud Run runtime environment.
* **DO** stream file uploads directly to storage from the `werkzeug.datastructures.FileStorage` object using `.seek(0)` and `.read()`. Do not save temporary files to the local container disk.

### 4. Database & Timezones
* **DO** store all timestamps in PostgreSQL as UTC `DateTime(timezone=True)`.
* **DO** apply application-level timezone conversions (specifically `America/Phoenix` / MST) when displaying data to the UI. Ensure Arizona's lack of Daylight Saving Time is respected using the standard `zoneinfo` module.

### 5. Code Style
* Write concise, pragmatic Python. Avoid unnecessary abstraction layers.
* Fail fast. Validate constraints (weight limits, file sizes, role access) at the top of the route or service function.

## Ecosystem Context

This application is part of the FSI shared infrastructure ecosystem. See [FSI_ECOSYSTEM.md](./FSI_ECOSYSTEM.md) for the full app portfolio and cross-app data flows.

**Shared DB role:** This app owns `shipments`, `shipment_legs`, `pod_records`, and `shipment_leg_transitions` tables. It consumes `users` (owned by `kdnye/expenses`) as read-only for driver identity.

**Schema ownership rule:** Never run structural migrations against `users`. When running `flask db migrate`, review generated revisions and remove any destructive operations on `users` before applying.

**Governance:** This app follows the [FSI Application Architecture Standard](https://github.com/kdnye/lifecycle/blob/main/FSI%20Application%20Architecture%20Standard%3A%20Technical%20Governance%20Handbook) in full.
