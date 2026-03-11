# FSI POD Application Architecture

## System Overview
FSI POD is a monolithic Flask application deployed on Google Cloud Run and served by synchronous Gunicorn workers. The platform supports Proof of Delivery (POD) capture, shipment progression, and operational visibility through short-polling dashboard updates.

Core design constraints:
- Browser-native mobile workflows using HTML5 device APIs (camera, geolocation, canvas).
- API-first server routes returning JSON payloads for dashboard and workflow actions.
- Direct object upload streaming from request file objects to cloud storage.
- UTC persistence in PostgreSQL with application-layer presentation in `America/Phoenix`.

Primary runtime components:
- Flask web app (routing, auth, business logic).
- PostgreSQL (transactional system of record).
- Google Cloud Storage for POD media artifacts.
- Workflow orchestration logic in `app/services/shipment_workflow.py`.

## Database Schema Blueprint
The POD workflow is modeled using normalized shipment entities and transition history.

### Core Tables

| Table | Purpose | Field Examples |
|---|---|---|
| `shipments` | Root shipment record and customer-facing identity. | `id`, `shipment_number`, `shipper_name`, `consignee_name`, `created_at_utc` |
| `shipment_legs` | Segment-level execution records for pickup, linehaul, and delivery activities. | `id`, `shipment_id`, `leg_type`, `status`, `assigned_driver_id`, `planned_departure_utc`, `actual_arrival_utc` |
| `pod_records` | Immutable proof artifacts captured at completion checkpoints. | `id`, `shipment_leg_id`, `event_type`, `signed_by`, `signature_image_uri`, `photo_uri`, `gps_latitude`, `gps_longitude`, `captured_at_utc` |
| `shipment_leg_transitions` | Auditable state transition log for each leg with actor and reason. | `id`, `shipment_leg_id`, `from_state`, `to_state`, `transition_reason`, `changed_by_user_id`, `changed_at_utc` |

### Relationship Notes
- `shipments` 1:N `shipment_legs`
- `shipment_legs` 1:N `pod_records`
- `shipment_legs` 1:N `shipment_leg_transitions`

### Time & Consistency Rules
- All timestamp columns are stored as timezone-aware UTC values.
- UI and reports convert to `America/Phoenix` at read-time.
- `shipment_leg_transitions` is append-only for traceability.

## Workflow Engine & State Machine
Shipment progression is enforced by the workflow service in `app/services/shipment_workflow.py`.

### Canonical Leg States
- `created`
- `dispatched`
- `in_transit`
- `arrived`
- `pod_captured`
- `completed`
- `exception`
- `cancelled`

### Allowed State Transitions
- `created` -> `dispatched`
- `dispatched` -> `in_transit`
- `in_transit` -> `arrived`
- `arrived` -> `pod_captured`
- `pod_captured` -> `completed`
- `created` -> `cancelled`
- `dispatched` -> `cancelled`
- `in_transit` -> `exception`
- `arrived` -> `exception`
- `exception` -> `in_transit`
- `exception` -> `cancelled`

### Transition Processing Contract
1. Validate requested `from_state` and `to_state` against allowed transitions.
2. Apply fail-fast guardrails (role checks, required POD artifacts, shipment leg ownership).
3. Persist leg status update in `shipment_legs`.
4. Append transition event to `shipment_leg_transitions` in the same transaction.
5. If transition reaches POD checkpoint, create corresponding `pod_records` entry.

## Integration Specifications

### Device & Browser Integration
- Camera capture via native file input with direct image upload.
- Signature capture via HTML5 canvas payload.
- Geolocation capture through browser geolocation API with explicit user permission.

### API Behavior
- JSON request/response contracts for shipment lookup, state transition, and dashboard refresh.
- Short-polling for operational status updates from browser clients.
- Deterministic HTTP error codes for invalid transitions and authorization failures.

### Storage Integration
- Upload streams are read from request file objects and sent directly to object storage.
- No temporary filesystem staging required for POD photos/signatures.
- Stored media URIs are persisted on `pod_records`.

## Deployment Specs

### Runtime Topology
- Single Flask service container running on Cloud Run.
- Gunicorn synchronous workers for predictable request handling.
- Horizontal autoscaling through Cloud Run instance scaling.

### Configuration & Security
- Application uses runtime-injected environment configuration.
- Cloud-native identity (Application Default Credentials) for storage access.
- Role-based access control enforced at route and service boundaries.

### Operational Requirements
- Health endpoints for readiness/liveness checks.
- Structured logs including shipment and leg identifiers for traceability.
- Database migrations applied before rollout when schema changes affect `shipment_legs`, `pod_records`, or `shipment_leg_transitions`.

## Realtime Transport Governance

### Production Standard (Current)
- Dashboard updates remain on short-polling HTTP requests.
- Runtime remains synchronous Gunicorn workers on Cloud Run.
- Production behavior is unchanged unless architecture review sign-off is completed.

### Proposed WebSocket/Socket.IO Changes
Any migration to WebSockets (including Socket.IO) is considered an architectural change request, not an implementation detail, because it impacts Cloud Run connection behavior, scaling assumptions, and state/session design.

Before implementation, teams must complete ADR review and satisfy the approval gate defined in `docs/adr/0001-dashboard-realtime-transport.md`.

### Gated Implementation Path
1. **Default path (no approval):** optimize short-polling only (interval tuning, `ETag`/conditional fetch, payload minimization).
2. **Approved path:** open a separate transport migration PR behind a feature flag with explicit rollback plan.

No production transport change is allowed before review sign-off.
