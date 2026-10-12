"""The official logo ATRUE shows for each airline it sells.

The carriers' own marks are downloaded once and shipped inside the app under
``logo_assets/`` rather than hot-linked, so the logo a page renders never
depends on a third party being reachable and never changes under our feet. Each
PNG is kept as an :class:`~airlines.models.AirlinePhoto` (the image store the
airline form and the search results already use), so an operator who uploads
their own mark through the airline form simply replaces the bundled one.

Logos are keyed by the airline's seeded name because that is the stable
identifier: ``Airline.airline_id`` is regenerated per row, but the twenty names
come straight from :mod:`airlines.fleet_data` and never change. Kept beside
``fleet_data`` for the same reason - both describe the same twenty airlines.
"""
from pathlib import Path

from django.core.files.base import File

#: Folder that ships with the app, next to this module.
LOGO_DIR = Path(__file__).resolve().parent / 'logo_assets'

#: Sub-folder under ``MEDIA_ROOT`` the photos are stored in (matches the
#: ``AirlinePhoto.image`` field's ``upload_to``).
PHOTO_DIR = 'airline_photos'

#: Seeded airline name -> bundled logo filename.
AIRLINE_LOGOS = {
    'Philippine Airlines': 'philippine-airlines.png',
    'Cebu Pacific': 'cebu-pacific.png',
    'Philippines AirAsia': 'philippines-airasia.png',
    'Singapore Airlines': 'singapore-airlines.png',
    'Cathay Pacific': 'cathay-pacific.png',
    'Japan Airlines': 'japan-airlines.png',
    'ANA': 'ana.png',
    'Korean Air': 'korean-air.png',
    'Malaysia Airlines': 'malaysia-airlines.png',
    'Thai Airways': 'thai-airways.png',
    'Vietnam Airlines': 'vietnam-airlines.png',
    'Emirates': 'emirates.png',
    'Qatar Airways': 'qatar-airways.png',
    'Etihad Airways': 'etihad-airways.png',
    'Saudia': 'saudia.png',
    'United Airlines': 'united-airlines.png',
    'Delta Air Lines': 'delta-air-lines.png',
    'American Airlines': 'american-airlines.png',
    'Turkish Airlines': 'turkish-airlines.png',
    'Air France': 'air-france.png',
}


def logo_file(name):
    """Open the bundled logo for an airline name, or ``None`` if not shipped.

    A fresh :class:`~django.core.files.base.File` is returned each call because
    saving a file consumes the handle.
    """
    filename = AIRLINE_LOGOS.get(name)
    if not filename:
        return None
    path = LOGO_DIR / filename
    if not path.exists():
        return None
    return File(path.open('rb'), name=filename)


def seed_airline_logos(Airline, AirlinePhoto, storage, *, replace=False, write=None):
    """Attach the bundled logo to every seeded airline.

    Idempotent by design: an airline that already owns a photo keeps it unless
    ``replace`` is set, so re-running the management command never clobbers a
    mark an operator uploaded, and a second run is a no-op. The image is written
    through ``storage`` so the row holds an ordinary media reference that
    survives a database backup/restore the same way any uploaded photo does.

    ``Airline`` / ``AirlinePhoto`` are passed in rather than imported so a data
    migration can hand over its historical model classes and reuse this logic.

    Returns ``(created, skipped)``.
    """
    created = skipped = 0
    for name in AIRLINE_LOGOS:
        for airline in Airline.objects.filter(name=name):
            existing = AirlinePhoto.objects.filter(airline=airline)
            if existing.exists():
                if not replace:
                    skipped += 1
                    continue
                existing.delete()

            handle = logo_file(name)
            if handle is None:
                continue

            # Reuse a file already on disk from an earlier run instead of
            # letting storage rename the second copy to ``..._XXXX.png``.
            target = f'{PHOTO_DIR}/{handle.name}'
            if not storage.exists(target):
                target = storage.save(target, handle)
            AirlinePhoto.objects.create(
                airline=airline, image=target, is_primary=True)
            created += 1
            if write is not None:
                write(f'  {name}: attached {handle.name}')

    return created, skipped
