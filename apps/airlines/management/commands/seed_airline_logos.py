"""Attach each airline's official logo to its record.

The twenty logos ship with the app (``airlines/logo_assets``); this command
copies the one belonging to each seeded airline into the airline's primary
:class:`~airlines.models.AirlinePhoto`. Run it after seeding or restoring a
database that was created before the logos existed::

    python manage.py seed_airline_logos
    python manage.py seed_airline_logos --replace

It is idempotent - an airline that already has a photo is left alone unless
``--replace`` is given - so it is safe to run on every deploy.
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from airlines.logo_data import seed_airline_logos
from airlines.models import Airline, AirlinePhoto


class Command(BaseCommand):
    help = "Attach the bundled official logos to the seeded airlines."

    def add_arguments(self, parser):
        parser.add_argument(
            '--replace', action='store_true',
            help='Replace existing photos, including ones uploaded by an operator.')

    def handle(self, *args, **options):
        created, kept = seed_airline_logos(
            Airline, AirlinePhoto, default_storage,
            replace=options['replace'], write=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(
            f"Airline logo seed complete: {created} attached, "
            f"{kept} kept their existing photo."))
