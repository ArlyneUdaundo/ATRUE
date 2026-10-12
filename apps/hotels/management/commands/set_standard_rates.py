"""Backfill every room to the standard ATRUE rate for its room type.

Reports what would change and writes nothing unless ``--apply`` is passed,
because this rewrites live prices across every hotel.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from hotels import pricing
from hotels.models import Room


class Command(BaseCommand):
    help = (
        'Set each room\'s rate and additional guest charge to the standard ATRUE '
        'price for its room type. Use --apply to write; otherwise it only reports.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually write the changes. Without this flag the command is a dry run.')
        parser.add_argument(
            '--hotel', type=int, default=None,
            help='Limit to a single hotel id.')

    def handle(self, *args, **options):
        rooms = Room.objects.select_related('hotel').all().order_by('hotel_id', 'room_number')
        if options['hotel']:
            rooms = rooms.filter(hotel_id=options['hotel'])

        changes = []
        for room in rooms:
            new_rate = pricing.standard_rate(room.room_type)
            new_extra = pricing.standard_extra_guest_charge(room.room_type)
            if room.rate != new_rate or room.additional_guest_charge != new_extra:
                changes.append((room, new_rate, new_extra))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Standard rates: {len(pricing.RATE_BY_ROOM_TYPE)} room types'))
        for key, amount in pricing.RATE_BY_ROOM_TYPE.items():
            self.stdout.write(
                f'  {key:<7} {amount:>10,.2f}/night'
                f'   +{pricing.EXTRA_GUEST_CHARGE_BY_ROOM_TYPE[key]:,.2f} extra guest'
            )

        self.stdout.write('')
        self.stdout.write(f'{rooms.count()} room(s) examined, {len(changes)} would change')
        for room, new_rate, new_extra in changes:
            self.stdout.write(
                f'  {room.hotel.name} / {room.room_id} ({room.room_type})'
                f'  rate {room.rate:,.2f} -> {new_rate:,.2f}'
                f'  extra {room.additional_guest_charge:,.2f} -> {new_extra:,.2f}')

        if not options['apply']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Dry run. Re-run with --apply to save these prices.'))
            return

        with transaction.atomic():
            updated = 0
            for room, new_rate, new_extra in changes:
                # Update the money columns only; room_id is auto-generated in
                # Room.save() and must not be disturbed.
                Room.objects.filter(pk=room.pk).update(
                    rate=new_rate, additional_guest_charge=new_extra)
                updated += 1
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Updated {updated} room(s).'))
