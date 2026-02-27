# FSI Application Architecture

## Overview
The FSI Application is a monolithic Python web application hosted on Google Cloud Run. It handles employee paperwork batching and real-time Proof of Delivery (POD) event capture. The architecture prioritizes lightweight, browser-native capabilities over compiled mobile applications.

## Core Technology Stack
* **Runtime:** Python 3.11+, Gunicorn (WSGI).
* **Framework:** Flask.
* **Database:** PostgreSQL (via SQLAlchemy ORM).
* **Hosting:** Google Cloud Run (Managed).
* **Object Storage:** Google Cloud Storage (GCS) for transactional media; Couchdrop for legacy batch documents.

## System Components

### 1. Frontend Data Capture (Mobile Web)
* **QR Scanning:** Uses `html5-qrcode` to decode BOL/Reference IDs client-side.
* **Geolocation:** Uses HTML5 `navigator.geolocation` API.
* **Photo Capture:** Uses standard `<input type="file" capture="environment">` to trigger native device cameras.
* **Signature Capture:** Uses `signature_pad` on an HTML5 `<canvas>`, serialized to Base64 PNGs prior to submission.

### 2. Real-Time Operations Dashboard
* **Methodology:** Client-side asynchronous polling (`fetch()`) at 10-second intervals.
* **Rationale:** Bypasses the need for WebSockets/Server-Sent Events (SSE) to maintain compatibility with standard threaded Gunicorn workers and Cloud Run connection timeouts.

### 3. Data Models
* `User`: RBAC-enabled employee accounts (EMPLOYEE, SUPERVISOR, FINANCE, ADMIN).
* `PODEvent`: Transactional ledger of discrete pickup/delivery actions. Stores GCS URIs, GPS coordinates, and handles UTC-to-Arizona (MST) timezone translation natively.
* `ExpectedDelivery`: Groups reference IDs by batch/route to drive the active operations dashboard.

### 4. Storage Integration
* **Transactional (POD):** Direct stream to GCS using `google-cloud-storage`. Authenticates implicitly via the Cloud Run default service account IAM role (`roles/storage.objectAdmin`).
* **Batch (Legacy):** Streams multipart form data to Couchdrop via API token.
