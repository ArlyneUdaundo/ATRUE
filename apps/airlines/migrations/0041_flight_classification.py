from django.db import migrations, models


def _country_code(airport):
    return (getattr(airport, 'country_code', '') or '').strip().upper()


def _country_name(airport):
    return ' '.join((getattr(airport, 'country', '') or '').split()).casefold()


def _route_scope(airports):
    airports = list(airports)
    if not airports or any(airport is None for airport in airports):
        return None

    codes = [_country_code(airport) for airport in airports]
    if all(codes):
        return 'DOMESTIC' if len(set(codes)) == 1 else 'INTERNATIONAL'

    names = [_country_name(airport) for airport in airports]
    if all(names):
        return 'DOMESTIC' if len(set(names)) == 1 else 'INTERNATIONAL'

    return None


def backfill_flight_classification(apps, schema_editor):
    Flight = apps.get_model('airlines', 'Flight')
    FlightItinerary = apps.get_model('airlines', 'FlightItinerary')

    for itinerary in FlightItinerary.objects.all().iterator():
        legs = list(
            Flight.objects.filter(itinerary_id=itinerary.pk)
            .select_related('origin_airport', 'destination_airport')
            .order_by('segment_order', 'pk')
        )
        if not legs:
            continue

        airports = []
        for leg in legs:
            airports.extend((leg.origin_airport, leg.destination_airport))

        scope = _route_scope(airports)
        if not scope:
            continue

        if itinerary.route_scope != scope:
            itinerary.route_scope = scope
            itinerary.save(update_fields=['route_scope'])
        Flight.objects.filter(pk__in=[leg.pk for leg in legs]).update(
            flight_classification=scope)

    standalone = (
        Flight.objects.filter(itinerary__isnull=True)
        .select_related('origin_airport', 'destination_airport')
    )
    for flight in standalone.iterator():
        scope = _route_scope((flight.origin_airport, flight.destination_airport))
        if scope and flight.flight_classification != scope:
            Flight.objects.filter(pk=flight.pk).update(
                flight_classification=scope)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0040_flight_offer_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='flight',
            name='flight_classification',
            field=models.CharField(
                blank=True,
                choices=[('DOMESTIC', 'Domestic'), ('INTERNATIONAL', 'International')],
                db_index=True,
                default='',
                help_text=(
                    'Whether every airport on this journey is in one country '
                    '(domestic) or the journey crosses a border (international).'
                ),
                max_length=15,
                verbose_name='Flight classification',
            ),
        ),
        migrations.RunPython(
            backfill_flight_classification,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
