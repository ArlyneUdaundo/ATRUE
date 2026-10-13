# ATRUE Travel and Tours Booking Platform

ATruE is a Django booking platform for travel and tourism establishments, built for simulation training. It includes booking and management workflows for hotels, resorts, staycations, restaurants, flights, land transportation, activities, landmarks, and tour packages.

## Features

- Establishment listings, details, search, and booking flows
- Passenger, guest, reservation, payment, and e-ticket workflows
- Transportation agencies, vehicles, drivers, and schedules
- Role-based simulation and establishment management
- Location hierarchy and geographic reference data
- Django admin, audit logs, and notifications
- Responsive templates and static assets

## Project structure

- `apps/` — Django applications and their migrations
- `atrue_core/` — project settings, routing, shared services, search, and e-ticket support
- `locations/` — location models, migrations, and seed data
- `templates/` — Django templates
- `static/` — CSS, JavaScript, and static images
- `manage.py` — Django management entry point
- `requirements.txt` — Python runtime dependencies

Uploaded user media, local databases, database exports, and local environment files are intentionally excluded from Git. They can contain private data or secrets.

## Requirements

- Python 3.12 or newer
- PostgreSQL for the normal development and production setup
- Git

## Local setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set a unique, private `SECRET_KEY` and the database connection values. Never commit `.env`.

Create the PostgreSQL database and user named in `.env`, then run:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

### Optional SQLite development database

For a machine without PostgreSQL, set `DB_ENGINE=sqlite` and `DB_NAME=db.sqlite3` in `.env`, then run the migrations. `DATABASE_URL`, if set, takes precedence over this option.

## Environment variables

See `.env.example` for the complete safe template. The required `SECRET_KEY` must be generated privately for each environment. Database settings can be supplied as `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`, or as `DATABASE_URL` on a hosted PostgreSQL service.

Email uses Django's console backend by default, which prints messages to the development console. To send email through Brevo SMTP, configure the SMTP host, login, and SMTP key in the environment and select Django's SMTP backend. Do not put a Brevo key in source code or commit it. This project does not include a direct Brevo HTTP API client.

## Supabase image storage

The Django upload views keep their existing PostgreSQL image records and gallery relationships, while Django's maintained `django-storages` S3 backend stores the actual bytes in Supabase Storage. Public listing, room, airline, transportation, landmark, activity, and gallery images go to `establishment-images`; account profile pictures go to the separate private `profile-images` bucket and use short-lived signed URLs. No database schema change is needed for listing image paths. Production storage fails closed when its credentials are missing instead of reporting a successful upload to Render's temporary filesystem. Local development can still use `MEDIA_ROOT` when Supabase is not configured.

In Supabase, create `establishment-images` and mark it public so public listings can use stable public URLs. Create `profile-images` as a private bucket. Under **Storage > S3 Configuration**, enable S3 access and copy the endpoint, region, access key ID, and secret access key. These S3 access keys are server-only and bypass Storage RLS, so do not put them in browser JavaScript or commit them. The Django upload views enforce the existing manager and assignment permissions before saving files. The storage layer also checks the image bytes, permits JPEG/PNG/WebP, and caps uploads at 10 MB.

For local development, put the values in `.env` (copied from `.env.example`). In the Render dashboard, open the web service **Environment** page and add `SUPABASE_URL`, `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_STORAGE_REGION`, `SUPABASE_STORAGE_BUCKET=establishment-images`, and `SUPABASE_PRIVATE_BUCKET=profile-images`. Add actual credentials as secret environment values there; use placeholders only in `.env.example`. Save and redeploy the service after configuring them.

After the environment variables and buckets are ready, run `python manage.py migrate_media_to_supabase` once in an environment that can access the existing media files and the target PostgreSQL database. The command keeps database file paths and skips objects already present. Files that have already disappeared from Render's ephemeral filesystem cannot be recovered by this command. Render can remain on the Free plan without a persistent disk; new uploads use Supabase once configured.

## Migrations and static files

All application migrations are stored in each app's `migrations/` directory and should be committed. Apply them with `python manage.py migrate`. For deployment, configure `STATIC_ROOT` and run `python manage.py collectstatic` as part of the hosting setup.

## Development checks

```powershell
python manage.py check
```

Application tests live in the Django apps and can be run with `python manage.py test`.

For optional role-demo accounts, set a private `ATRUE_DEMO_PASSWORD` in `.env` before running `python manage.py seed_roles`. The command intentionally has no built-in shared password.

## Security and Git exclusions

`.gitignore` excludes `.env`, virtual environments, Python caches, local databases and SQL backups, generated logs, uploaded `media/` files, IDE settings, and local troubleshooting scripts. Keep private credentials in environment variables and use `.env.example` only for placeholders.
