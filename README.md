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
3. Deploys to Cloud Run with required env + secrets wiring.

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
- Register every new database table name as a constant in `models.py` (with the other `*_TABLE` constants) before referencing it in SQLAlchemy models or migrations.

## Font Loading Strategy
The UI uses two branded web fonts at runtime:
- `Roboto` for body copy and controls
- `Bebas Neue` for display headings (`.fsi-display`)

Fonts are loaded in `templates/base.html` through Google Fonts with `preconnect` hints for `fonts.googleapis.com` and `fonts.gstatic.com` to reduce connection setup latency. CSS keeps resilient fallback stacks (`system-ui`, `sans-serif`) so pages still render predictably if the CDN is blocked or slow.

### Privacy and Performance Trade-offs
- **Current approach (Google Fonts CDN):** easiest maintenance, good global caching, and fast delivery in many regions. Trade-off: client browsers make requests to Google infrastructure, which may be a privacy concern in some compliance contexts.
- **Alternative (self-hosted fonts):** stronger privacy posture and full control over caching headers/versioning, but increases repo/deployment asset management and can reduce cache-hit sharing across sites.

If policy requirements change, migrate by placing font files under `static/fonts/` and defining `@font-face` rules in `static/css/fsi.css`, while keeping the same fallback stacks.

