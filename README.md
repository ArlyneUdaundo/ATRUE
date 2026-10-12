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
