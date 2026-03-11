# ADR 0001: Dashboard Realtime Transport (Short-Polling vs WebSocket)

- **Status:** Proposed (requires architecture + operations approval)
- **Date:** 2026-03-11
- **Decision Owners:** Application Architecture, SRE/Operations, Product Engineering
- **Related Docs:** `ARCHITECTURE.md`

## Context
The current production system uses browser short-polling with synchronous Gunicorn workers on Cloud Run for dashboard refreshes. This is an explicit architecture standard because it keeps request lifecycles bounded, stateless, and operationally predictable.

A proposal was raised to introduce WebSocket-based realtime updates (for example, via Socket.IO). That proposal conflicts with the current standard and introduces changes in connection lifecycle, instance behavior, and scaling assumptions.

## Current Standard (Baseline)
1. **Transport:** Short-polling over standard HTTP.
2. **Server model:** Synchronous Gunicorn workers only.
3. **Runtime:** Cloud Run autoscaling with stateless request handling.
4. **Client behavior:** Periodic dashboard refresh calls returning compact JSON payloads.

## Conflict & Implications of WebSocket Migration
Moving to WebSockets is not a drop-in library swap. It changes operational behavior in several ways:

### 1) Cloud Run connection behavior
- Long-lived socket connections can keep instances warm and alter concurrency utilization.
- Connection-heavy workloads may require different min/max instance strategy than short, bursty HTTP polling.
- Readiness/health and graceful shutdown behavior need validation for active socket drains.

### 2) Scaling and capacity planning
- Polling scales by request rate; WebSockets scale by concurrent connection count and message fan-out.
- Need connection budget estimates (per instance/per worker) and load test targets before rollout.
- Autoscaler reactions may differ because open connections are not equivalent to short HTTP requests.

### 3) Session/state strategy
- Socket transport often encourages in-memory subscription state that breaks stateless assumptions.
- Must define authoritative state source and reconnect semantics (resume, replay, idempotency).
- Multi-instance fan-out may require shared pub/sub infrastructure if broadcast semantics are needed.

### 4) Reliability and failure domains
- Must define fallback behavior when websocket upgrade fails or disconnects.
- Must confirm no regression in delivery guarantees for operational dashboard data.
- Need explicit timeout/retry/backoff model for reconnect storms.

### 5) Cost profile
- Persistent connections can increase baseline resource consumption.
- Cost model must compare polling request volume vs persistent connection overhead under expected peak load.

## Decision
**Do not introduce Socket.IO/WebSockets into production at this time.**

Adopt a gated path:
1. Keep current short-polling behavior unchanged in production until formal sign-off.
2. Require an approval package (acceptance criteria below) before any transport migration PR.
3. If not approved, continue with short-polling optimization work only.

## Approval Acceptance Criteria (Gate)
Approval requires all criteria below to be met and documented:

1. **Operations readiness**
   - Updated runbook for deployment, rollback, and incident response.
   - Connection lifecycle handling documented (startup, drain, shutdown).

2. **Reliability evidence**
   - Load test proving target SLO under expected peak concurrent clients.
   - Reconnect storm test and degraded network test results.
   - Demonstrated fallback path to short-polling.

3. **Cost analysis**
   - 30-day projected cost comparison: current polling vs websocket architecture.
   - Explicit max-cost threshold accepted by stakeholders.

4. **Scaling plan**
   - Connection-per-instance budget and autoscaling configuration.
   - Multi-instance message distribution strategy (if broadcast required).

5. **Security/compliance**
   - Authentication and authorization model for realtime channel.
   - Idle timeout and abuse controls (rate limits / connection caps).

6. **Migration safety**
   - Feature-flagged rollout with canary plan.
   - Defined rollback trigger and rollback execution steps.

## Implementation Path

### Path A: Approved for transport migration
Create a **separate implementation PR** that is strictly scoped to transport changes and includes:
- feature flag defaulting to current polling behavior,
- incremental enablement plan,
- observability updates (connection count, disconnect rate, message lag),
- rollback checklist.

### Path B: Not approved (default)
Optimize the existing short-polling stack without transport changes:
- tune polling intervals by dashboard view criticality,
- add conditional fetch support (`ETag` / `If-None-Match`) to reduce payload transfer,
- minimize payload fields and avoid redundant nested data,
- instrument p95 latency and payload size trends.

## Consequences
- Preserves stable synchronous Gunicorn + Cloud Run production posture immediately.
- Prevents unreviewed architectural drift toward stateful connection management.
- Creates a clear decision gate with measurable approval criteria.
