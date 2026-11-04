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

- `apps/` â€” Django applications and their migrations
- `atrue_core/` â€” project settings, routing, shared services, search, and e-ticket support
- `locations/` â€” location models, migrations, and seed data
- `templates/` â€” Django templates
- `static/` â€” CSS, JavaScript, and static images
- `manage.py` â€” Django management entry point
- `requirements.txt` â€” Python runtime dependencies

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

## Flight listings from Duffel

The flight search page can request provider offers from Duffel when `DUFFEL_ACCESS_TOKEN` is configured. Set `DUFFEL_MODE=test` and use a Duffel test token to try the integration. Test results are sandbox examples, not current airline schedules or fares. ATRUE stores each returned offer as a read-only `FlightOfferSnapshot` with its route, quoted total, currency, retrieval time, expiry, and provider payload; it does not add it to airline-managed inventory. Search results are labeled with their data source. This integration calls the search endpoint only: ATRUE's existing booking and simulated payment flow remains separate, and it does not create Duffel orders or payments.

Apply the new snapshot table with `python manage.py migrate`. Keep the Duffel token in the private environment configuration; never expose it in browser code or commit it. Live mode can be enabled only after obtaining Duffel live access; it returns provider offers for the requested route and date, not a permanent all-airline schedule feed. Prices and availability can change or expire.

## Flight search results preview

The flight results page at `/flights/` (view `airlines.views.flight_list`) is a front-end recreation of the ATRUE flight search interface. It renders a fixed 32-flight sample schedule from `apps/airlines/sample_flights.py` so the layout is always populated, and it labels those rows as sample data: times, fares and availability are illustrative and no reservation or payment is created from this page. The route codes come from the search form or the incoming `origin`/`destination` query parameters, and the page stamps them onto every sample row. Database-backed flight context and provider offer snapshots are still computed by the view, but the results grid itself is the sample schedule.

Run the site and open the page:

```powershell
python manage.py runserver
```

Then browse to `http://127.0.0.1:8000/flights/`. Trip type, route, dates and passengers update the results heading and trip summary in the browser; stop, airline, departure-window, duration and price filters, the four sort tabs, the sort-by select and the expandable flight details all run client-side with no further server request. Choosing a flight opens a two-step selection panel and confirms the choice without booking anything.

### Trip type and Domestic / International selector

The search panel's first row carries two compact pill groups: **trip type** (One Way, Round Trip, Multi-City) and **flight type** (Domestic, International), separated by a thin divider. The second row holds the route, dates, passengers and the Search Flights button in one horizontal band that stacks cleanly on small screens.

- **One Way** shows only the departure date; **Round Trip** adds the return date; **Multi-City** replaces the single route row with repeatable segments, each with its own origin, destination and departure date (two segments minimum, six maximum). Changing the trip type only toggles the fields it owns and keeps every other valid input.
- **Domestic** scopes the airport pickers to the country of the current route (the Philippines by default), so typing a city only suggests airports in that country. **International** searches the full worldwide airport list and the picker sends a `country` scope to `/flights/api/airports/` when a country is active.
- The origin and destination use the shared worldwide airport picker (`templates/search/_airport_field.html` and `static/js/airport-picker.js`), which stores the selected `Airport` id plus its city, country and ISO country code. The summary line and result cards relabel themselves from the chosen airports, including database airports that are not in the built-in shortlist.
- The browser checks the pair as soon as the airports or the flight type change and shows an inline message when a route contradicts the chosen flight type. The server does not trust that toggle: `airlines.views.flight_list` re-reads the origin and destination `Airport` rows and derives the real category from their country / country code, rejecting a mismatch with a clear message. Multi-city segments are validated one by one the same way, along with dates and passenger counts.

Search stays client-side for the sample results page; the parameters (`trip_type`, `flight_type`, `origin_airport`, `destination_airport`, `departure_date`, `return_date`, `passengers`, and for multi-city the repeated `leg_origin_airport` / `leg_destination_airport` / `leg_departure_date` lists) are the same ones the Django view already understands, so a bookmark or a shared link reproduces the search.

The page uses `templates/airlines/list.html`, the standalone `templates/airlines/search_base.html`, the component partials in `templates/airlines/search/`, `static/css/flight-search.css`, `static/js/flight-results.js`, and the vector artwork in `static/img/`. It does not load the dashboard stylesheets, so it is self-contained.

## Passenger details preview

The passenger details page at `/flights/passenger-details/` (view `airlines.views.passenger_details`) is a front-end recreation of the ATRUE booking step that follows flight selection. It is a prototype: everything lives in the browser's page state, nothing is written to the database, no booking is created and no payment is taken. The page says so on screen, and every price is labelled as a sample that would come from the airline's fare rules for the route and cabin in the real system.

Reach it from the results page: select a flight, confirm the selection, then **Continue to Passenger Details**. The link carries the route, the chosen sample row, the trip type, the dates and the traveller breakdown, so the page opens on the flight that was actually picked with the same number of adults, children and infants the search used.

The layout is three columns on desktop and stacked on mobile:

- **Left** â€” flight summary: airline and logo, class, departure and arrival airport, date and time, duration, stops, flight number, aircraft, checked and cabin baggage, meal and Wi-Fi.
- **Centre** â€” the flight type toggle, the traveller counters, one passenger form per traveller, the single **Select Seat** button, the baggage and insurance selectors, and the cancellation and refund policy card.
- **Right** â€” the fare summary with base fare, taxes and fees, passenger count, extra baggage, travel insurance, the total, **Continue to Review & Payment**, **Back to Flight Details** and the secure-booking note.

### Flight type, travellers and seats

- **Domestic Flight** hides the passport field and drops it from validation, with the note "Passport number is not required for domestic flights." **International Flight** shows it, makes it required on every passenger form, and says so. Switching between them happens in the page, without a reload, and clearing the type clears the passport error. The type is prefilled from the route: a route that leaves the Philippines opens on International.
- The traveller counters cover **adults (1â€“9)**, **children (2â€“11)** and **infants (under 2)**. Choosing a count generates that many passenger forms, each with full name, email, date of birth, gender, nationality, phone number with country code and, for international flights, passport number. A traveller can also be removed individually; a booking always keeps at least one adult and never has more infants than adults.
- **Exactly one Select Seat button** sits below all the passenger forms, never inside one. It opens an aircraft seat map with window, middle and aisle seats, occupied seats marked unavailable, a legend, a traveller assignment panel, **Confirm Seats** and **Cancel**. A seat already held by another traveller is refused rather than handed over silently, the number of seats can never exceed the number of travellers who occupy one, and a traveller without a seat blocks the confirmation. Reducing the traveller count keeps the assignments that still apply and clears the ones that no longer do. Infants travel on an adult's lap and are not given a seat.

### Baggage, insurance and the fare summary

- **Extra baggage** is sold in 5 kg blocks (0, 5, 10, 15, 20, 25 kg) with the price shown beside each option. The page states that the charge is per passenger and multiplies it by the traveller count.
- **Travel insurance** is optional: No Insurance, Basic (â‚±299), Standard (â‚±499) and Premium (â‚±799) per passenger, each with a short description of what it may cover and what it excludes, plus an expandable panel with the terms, conditions, claim requirements and coverage limits.
- The fare summary is always computed from the current state, never a fixed number: `base fare Ã— travellers + taxes and fees + extra baggage + insurance`, with the per-passenger average underneath. Baggage and insurance changes update it immediately. The prototype charges every traveller the same base fare; a real implementation would price children and infants on their own fare rules.
- **Continue to Review & Payment** validates every passenger, the flight type, the passport numbers for international flights, the seat assignments and the policy acknowledgement, and shows field-level errors where something is missing. Only then does it open the review, which lists the flight, every passenger with their seat, the baggage and insurance selections, the policy acknowledgement and the full price breakdown.

### Cancellation and refund policy

The policy card spells out the six-step process (submit the request, provide supporting documents, verify eligibility, review the request, determine the refund, process the approved refund), lists the possible request statuses (Submitted, Under Review, Additional Documents Required, Approved, Rejected, Refund Processing, Refunded) and has a **Learn More About Refunds** panel. It states plainly that travel insurance does not automatically guarantee a refund, that a claim has to meet the policy's conditions and exclusions, that airline refunds and insurance claims are handled separately, and that a request is never approved automatically just because a reason was entered. The policy text is a sample, written for the prototype, and is meant to be configurable.

The page is `templates/airlines/passenger_details.html` with the partials in `templates/airlines/booking/`, the sample data in `apps/airlines/passenger_details_sample.py`, the styles in `static/css/passenger-details.css` and the behaviour in `static/js/passenger-details.js`.

## Supabase image storage

The Django upload views keep their existing PostgreSQL image records and gallery relationships, while Django's maintained `django-storages` S3 backend stores the actual bytes in Supabase Storage. Public listing, room, airline, transportation, landmark, activity, and gallery images go to `establishment_images`; account profile pictures go to the separate private `profile_images` bucket and use short-lived signed URLs. No database schema change is needed for listing image paths. Production storage fails closed when its credentials are missing instead of reporting a successful upload to Render's temporary filesystem. Local development can still use `MEDIA_ROOT` when Supabase is not configured.

In Supabase, create `establishment_images` and mark it public so public listings can use stable public URLs. Create `profile_images` as a private bucket. Under **Storage > S3 Configuration**, enable S3 access and copy the endpoint, region, access key ID, and secret access key. These S3 access keys are server-only and bypass Storage RLS, so do not put them in browser JavaScript or commit them. The Django upload views enforce the existing manager and assignment permissions before saving files. The storage layer also checks the image bytes, permits JPEG and PNG, and caps uploads at 5 MB.

For local development, put the values in `.env` (copied from `.env.example`). In the Render dashboard, open the web service **Environment** page and add `SUPABASE_URL`, `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`, `SUPABASE_STORAGE_REGION`, `SUPABASE_STORAGE_BUCKET=establishment_images`, and `SUPABASE_PRIVATE_BUCKET=profile_images`. Add actual credentials as secret environment values there; use placeholders only in `.env.example`. Save and redeploy the service after configuring them.

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
