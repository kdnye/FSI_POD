# FSI Ecosystem Reference

This application is part of the FSI internal tools ecosystem. All 6 FSI apps share a single GCP Cloud SQL PostgreSQL instance.

## This App's Role

Proof of delivery capture for freight shipments. Drivers and ops staff use this to record POD events (photos, signatures, GPS coordinates). This app owns the `shipments`, `shipment_legs`, `pod_records`, and `shipment_leg_transitions` tables. It consumes `users` (owned by `kdnye/expenses`) as read-only for driver identity. Shipment state data is consumed by `kdnye/motive-dashboard` for fleet map dispatch correlation.

## Canonical Ecosystem Document

Full app portfolio, shared DB schema ownership, cross-app data flows, and future roadmap:

→ **[FSI_ECOSYSTEM.md in kdnye/lifecycle](https://github.com/kdnye/lifecycle/blob/main/FSI_ECOSYSTEM.md)**

## Governance Handbook

Complete technical standards (stack, migrations, deployment, email, secrets, UI):

→ **[FSI Application Architecture Standard](https://github.com/kdnye/lifecycle/blob/main/FSI%20Application%20Architecture%20Standard%3A%20Technical%20Governance%20Handbook)**

> When a dedicated `kdnye/fsi-docs` repository is created, update these links to point there.
