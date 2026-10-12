"""Create an establishment for every existing Activity and Tour Package row.

Activities and tour packages are assigned per resource, so each one needs its
own ``ACTIVITY`` / ``TOUR_PACKAGE`` establishment for the instructor's picker.
The auto-establish signal covers rows created from now on; rows that already
exist (seeded or instructor-created before this deploy) are wrapped here.
"""

from django.db import migrations


def backfill_linked_establishments(apps, schema_editor):
    Establishment = apps.get_model('establishments', 'Establishment')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    linked = (
        ('ACTIVITY', 'activities', 'Activity'),
        ('TOUR_PACKAGE', 'tour_package', 'TourPackage'),
    )

    for establishment_type, app_label, model_name in linked:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover - both apps are installed
            continue

        content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
        for row in model.objects.all().iterator():
            if Establishment.objects.filter(
                    entity_type=content_type, entity_id=row.pk).exists():
                continue

            Establishment.objects.create(
                name=(row.name or '')[:150],
                type=establishment_type,
                status='ACTIVE' if getattr(row, 'status', '') == 'ACTIVE' else 'INACTIVE',
                entity_type=content_type,
                entity_id=row.pk,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('establishments', '0003_backfill_new_linked_establishments'),
        ('activities', '0001_initial'),
        ('tour_package', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_linked_establishments, migrations.RunPython.noop),
    ]