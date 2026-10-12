"""Ensure every existing establishment catalogue row is in the shared registry."""

from django.db import migrations


LINKED_MODELS = (
    ('HOTEL', 'hotels', 'Hotel'),
    ('RESORT', 'resorts', 'Resort'),
    ('RESTAURANT', 'restaurants', 'Restaurant'),
    ('STAYCATION', 'staycations', 'Staycation'),
    ('LANDMARK', 'landmarks', 'Landmark'),
    ('AIRLINE', 'airlines', 'Airline'),
    ('TRANSPORTATION', 'transportation', 'Agency'),
    ('ACTIVITY', 'activities', 'Activity'),
    ('TOUR_PACKAGE', 'tour_package', 'TourPackage'),
)


def backfill_catalogue_establishments(apps, schema_editor):
    Establishment = apps.get_model('establishments', 'Establishment')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    for establishment_type, app_label, model_name in LINKED_MODELS:
        model = apps.get_model(app_label, model_name)
        content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
        for row in model.objects.all().iterator():
            if Establishment.objects.filter(
                entity_type=content_type, entity_id=row.pk
            ).exists():
                continue

            establishment = Establishment.objects.create(
                name=(row.name or '')[:150],
                type=establishment_type,
                status='ACTIVE' if getattr(row, 'status', '') == 'ACTIVE' else 'INACTIVE',
                entity_type=content_type,
                entity_id=row.pk,
            )
            establishment.establishment_id = f'EST-{establishment.pk:05d}'
            establishment.save(update_fields=['establishment_id'])


class Migration(migrations.Migration):
    dependencies = [
        ('establishments', '0005_alter_establishment_type'),
        ('hotels', '0001_initial'),
        ('resorts', '0001_initial'),
        ('restaurants', '0001_initial'),
        ('staycations', '0001_initial'),
        ('landmarks', '0001_initial'),
        ('airlines', '0001_initial'),
        ('transportation', '0001_initial'),
        ('activities', '0001_initial'),
        ('tour_package', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_catalogue_establishments, migrations.RunPython.noop),
    ]
