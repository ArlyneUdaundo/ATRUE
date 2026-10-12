"""Give every seeded airline its official logo.

Each airline has to wear its own real mark rather than the generic plane, so the
search results, booking pages, tickets and management screens can tell the
operators apart at a glance. The logos ship with the app under
``airlines/logo_assets`` and are attached here as the airline's primary
:class:`~airlines.models.AirlinePhoto` - the image slot the ticket and search
readers already treat as the logo - so a restored database comes back branded
with no upload step and no network access.
"""

from django.core.files.storage import default_storage
from django.db import migrations

from airlines.logo_data import AIRLINE_LOGOS, PHOTO_DIR, seed_airline_logos


def attach_logos(apps, schema_editor):
    seed_airline_logos(
        apps.get_model('airlines', 'Airline'),
        apps.get_model('airlines', 'AirlinePhoto'),
        default_storage,
    )


def remove_logos(apps, schema_editor):
    """Drop the bundled photos again, leaving any operator upload untouched."""
    AirlinePhoto = apps.get_model('airlines', 'AirlinePhoto')
    bundled = [f'{PHOTO_DIR}/{name}' for name in AIRLINE_LOGOS.values()]
    (AirlinePhoto.objects
     .filter(airline__name__in=list(AIRLINE_LOGOS), image__in=bundled)
     .delete())


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0035_booking_assigned_to_booking_confirmed_at_and_more'),
    ]

    operations = [
        migrations.RunPython(attach_logos, remove_logos),
    ]
