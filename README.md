# FSI Application

## Overview
This repository follows the **Freight Services Inc. (FSI) Application Architecture Standard** using Flask + SQLAlchemy and Cloud Run for runtime hosting.

## Local Development
### Prerequisites
- Python 3.10+
- PostgreSQL (or a compatible reachable database)

### Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` is maintained as a pinned baseline (`==`) for reproducible local, CI, and Cloud Run builds.

Create a local `.env` file (or export vars in your shell):
```env
APP_ENV=local
FSI_PRODUCTION=false
DEBUG=true
SECRET_KEY=dev-only-change-me
DATABASE_URL=postgresql+psycopg://localhost/fsi_app
PORT=8080
MAX_CONTENT_LENGTH_MB=16
```

Run locally with Flask's dev server:
```bash
python wsgi.py
```

## Testing and Coverage
Run tests with coverage (same command used in CI):
```bash
pytest --cov=app --cov=services --cov-report=term-missing
```

## Production Runtime (Cloud Run)
Production serving uses Gunicorn, not Flask's development server.

### Container
Build and run using the included `Dockerfile`:
- WSGI server: `gunicorn`
- App module: `wsgi:app`
- Bind: `0.0.0.0:$PORT`

### Cloud Build + Cloud Run Deploy
Use the included `cloudbuild.yaml`:
```bash
gcloud builds submit --config cloudbuild.yaml .
```

The pipeline:
1. Builds the container image.
2. Pushes image to Artifact Registry.
3. Executes the migration job (`flask db upgrade --directory alembic`) — this is the only approved schema rollout path.
4. Deploys to Cloud Run with required env + secrets wiring.

### Schema Migration Policy
Use Alembic only for schema rollouts:

```bash
flask db upgrade --directory alembic
```

Legacy SQL scripts in `migrations/` are retained for historical context only and are deprecated for execution.

### Legacy SQL to Alembic Mapping (Inventory)
| Legacy SQL file | Alembic replacement revision | Status |
|---|---|---|
| `migrations/20260303_add_is_ops_to_users.sql` | `alembic/versions/20260306_01_add_users_is_ops_flag.py` | Deprecated SQL; use Alembic |
| `migrations/20260303_decouple_pod_records.sql` | `alembic/versions/20260306_02_decouple_pod_records.py` | Deprecated SQL; use Alembic |
| `migrations/20260304_add_shipment_tables.sql` | `alembic/versions/20260306_03_add_shipment_tables.py` | Deprecated SQL; use Alembic |
| `migrations/20260304_add_pod_record_location_and_leg_fields.sql` | `alembic/versions/20260306_04_add_pod_record_location_and_leg_fields.py` | Deprecated SQL; use Alembic |
| `migrations/20260304_add_notification_settings_and_emails.sql` | `alembic/versions/20260306_05_add_notification_settings_and_emails.py` | Deprecated SQL; use Alembic |
| `migrations/20260304_add_load_board_mawb_number.sql` | `alembic/versions/20260304_02_add_load_board_mawb_number.py` | Deprecated SQL; use Alembic |

Recommended verification step after migration and before cutover:
```bash
curl -fsS https://<service-url>/readyz
```
If required columns are missing, `/readyz` returns `503` with actionable guidance listing missing schema elements.

## Required Runtime Environment Variables
These values are read by `app/config.py`.

| Variable | Required in Production | Description | Source |
|---|---:|---|---|
| `APP_ENV` | Yes | Set to `production` in Cloud Run deploy. | Cloud Run env var |
| `FSI_PRODUCTION` | Yes | Safety switch enabling strict env validation. | Cloud Run env var |
| `SECRET_KEY` | Yes | Flask secret key for signing sessions/CSRF. | Secret Manager (`fsi-secret-key`) |
| `DATABASE_URL` | Yes | SQLAlchemy DB URL (`postgresql+psycopg://...`). | Secret Manager (`fsi-database-url`) |
| `PORT` | Auto | HTTP listen port injected by Cloud Run. | Cloud Run runtime |
| `DEBUG` | No | Keep `false` in production. | Cloud Run env var |
| `SESSION_COOKIE_SECURE` | No | Defaults to `true` when production mode is enabled. | Optional env var |
| `REMEMBER_COOKIE_SECURE` | No | Defaults to `true` when production mode is enabled. | Optional env var |
| `MAX_CONTENT_LENGTH_MB` | No | Global request body cap in MB (default `16`, resulting in `MAX_CONTENT_LENGTH=16*1024*1024`). | Optional env var |

## Secret Manager Names
`cloudbuild.yaml` expects these secret names by default:
- `fsi-secret-key` → mounted as `SECRET_KEY`
- `fsi-database-url` → mounted as `DATABASE_URL`

Adjust via Cloud Build substitutions if your organization uses different naming.

## Entrypoint Guidance
- **Local development:** `python wsgi.py`
- **Production/container:** `gunicorn --bind 0.0.0.0:${PORT} wsgi:app`

The `wsgi.py` file keeps local bootstrap behavior while production execution is handled by the Docker `CMD`.

## Developer Notes
- Register every new database table name as a module-level constant in `models.py` using the `<TABLE_NAME_UPPER>_TABLE` naming convention before referencing it in SQLAlchemy models or migrations.
- Do not execute files in `migrations/*.sql` for schema rollout; they are deprecated historical references.

## Font Loading Strategy
The UI uses two branded web fonts at runtime:
- `Roboto` for body copy and controls
- `Bebas Neue` for display headings (`.fsi-display`)

Fonts are loaded in `templates/base.html` through Google Fonts with `preconnect` hints for `fonts.googleapis.com` and `fonts.gstatic.com` to reduce connection setup latency. CSS keeps resilient fallback stacks (`system-ui`, `sans-serif`) so pages still render predictably if the CDN is blocked or slow.

### Privacy and Performance Trade-offs
- **Current approach (Google Fonts CDN):** easiest maintenance, good global caching, and fast delivery in many regions. Trade-off: client browsers make requests to Google infrastructure, which may be a privacy concern in some compliance contexts.
- **Alternative (self-hosted fonts):** stronger privacy posture and full control over caching headers/versioning, but increases repo/deployment asset management and can reduce cache-hit sharing across sites.

If policy requirements change, migrate by placing font files under `static/fonts/` and defining `@font-face` rules in `static/css/fsi.css`, while keeping the same fallback stacks.

