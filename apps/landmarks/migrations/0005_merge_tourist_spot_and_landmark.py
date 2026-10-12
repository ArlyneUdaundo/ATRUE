from django.db import migrations, models
import django.db.models.deletion


def forward_copy(apps, schema_editor):
    Landmark = apps.get_model('landmarks', 'Landmark')
    TouristSpot = apps.get_model('landmarks', 'TouristSpot')
    Ticket = apps.get_model('landmarks', 'Ticket')

    existing = set(Landmark.objects.values_list('name', flat=True))
    id_map = {}
    for spot in TouristSpot.objects.all().order_by('pk'):
        if spot.name in existing:
            dest = Landmark.objects.get(name=spot.name)
        else:
            dest = Landmark.objects.create(
                category='TOURIST_SPOT',
                name=spot.name,
                description=spot.description,
                country=spot.country,
                region=spot.region,
                province=spot.province,
                municipality=spot.municipality,
                barangay=spot.barangay,
                contact_number=spot.contact_number,
                open_hours=spot.open_hours,
                entry_fee=spot.entry_fee,
                capacity=spot.capacity,
                guided_tour_rate=spot.guided_tour_rate,
                private_tour_rate=spot.private_tour_rate,
                status=spot.status,
                created_at=spot.created_at,
            )
            existing.add(spot.name)
        id_map[spot.pk] = dest.pk

    for ticket in Ticket.objects.all():
        dest_id = id_map.get(ticket.tourist_spot_id) if ticket.tourist_spot_id else None
        if dest_id is None:
            dest_id = ticket.landmark_id
        ticket.destination_id = dest_id
        ticket.save(update_fields=['destination_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('landmarks', '0004_ticket_payer_contact_alter_ticket_payer_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='landmark',
            name='category',
            field=models.CharField(choices=[('TOURIST_SPOT', 'Tourist Spot'), ('LANDMARK', 'Landmark')], default='LANDMARK', max_length=15),
        ),
        migrations.AddField(
            model_name='ticket',
            name='destination',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='tickets', to='landmarks.landmark'),
        ),
        migrations.RunPython(forward_copy, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='ticket',
            name='landmark',
        ),
        migrations.RemoveField(
            model_name='ticket',
            name='tourist_spot',
        ),
        migrations.DeleteModel(
            name='TouristSpot',
        ),
    ]