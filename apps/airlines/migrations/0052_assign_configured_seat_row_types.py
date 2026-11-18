"""Populate the 3-3 layout's priced row types without changing seat positions."""

from django.db import migrations


POSITION_TYPES = {
    'window': 'window',
    'middle': 'standard',
    'aisle': 'aisle',
}


def eligible_layouts(SeatLayout, Cabin, alias):
    for layout in SeatLayout.objects.using(alias).filter(seat_map='3-3').iterator():
        cabins = list(Cabin.objects.using(alias).filter(seat_layout_id=layout.pk))
        if (len(cabins) == 1 and cabins[0].blocks == [3, 3]
                and cabins[0].rows >= 11):
            yield layout


def promote_row_types(apps, schema_editor):
    alias = schema_editor.connection.alias
    SeatLayout = apps.get_model('airlines', 'SeatLayout')
    Cabin = apps.get_model('airlines', 'Cabin')
    Seat = apps.get_model('airlines', 'Seat')
    SeatType = apps.get_model('airlines', 'SeatType')
    type_ids = dict(SeatType.objects.using(alias).values_list('code', 'id'))
    required = {'standard', 'window', 'aisle', 'front_row',
                'extra_legroom', 'exit_row'}
    if not required.issubset(type_ids):
        return

    for layout in eligible_layouts(SeatLayout, Cabin, alias):
        exits = set()
        for row in layout.exit_rows or ():
            try:
                exits.add(int(row))
            except (TypeError, ValueError):
                continue
        special_rows = {1: 'front_row', 4: 'extra_legroom'}
        for row in exits:
            if row not in special_rows:
                special_rows[row] = 'exit_row'

        updates = []
        seats = (Seat.objects.using(alias).filter(seat_layout_id=layout.pk)
                 .select_related('seat_type').order_by('row_number', 'letter'))
        for seat in seats:
            base = POSITION_TYPES.get(seat.position, 'standard')
            current = seat.seat_type.code if seat.seat_type_id else None
            desired = special_rows.get(seat.row_number, base)
            if current not in (None, base) or current == desired:
                continue
            seat.seat_type_id = type_ids[desired]
            updates.append(seat)
        if updates:
            Seat.objects.using(alias).bulk_update(
                updates, ['seat_type'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0051_flight_seat_type_prices'),
    ]

    operations = [
        # Seat category assignments can be edited afterward; preserve them if
        # a developer later rolls migrations back.
        migrations.RunPython(promote_row_types, migrations.RunPython.noop),
    ]
