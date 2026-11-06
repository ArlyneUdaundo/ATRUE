"""Retry official logo lookups for airline records without a saved logo."""

from django.core.management.base import BaseCommand

from airlines.logo_service import ensure_airline_logo
from airlines.models import Airline, AirlinePhoto


class Command(BaseCommand):
    help = 'Fetch and store official logos for airlines that still use placeholders.'

    def handle(self, *args, **options):
        saved = missing = 0
        for airline_id in Airline.objects.order_by('pk').values_list('pk', flat=True):
            if AirlinePhoto.objects.filter(
                    airline_id=airline_id, is_locked_logo=True).exists():
                continue
            if ensure_airline_logo(airline_id):
                saved += 1
            else:
                missing += 1
        self.stdout.write(self.style.SUCCESS(
            f'Airline logo lookup complete: {saved} saved, {missing} still using placeholders.'))
