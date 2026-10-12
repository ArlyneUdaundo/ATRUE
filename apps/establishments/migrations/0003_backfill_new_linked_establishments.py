"""Create establishments for every existing resort, restaurant, staycation and
landmark catalogue row.

Section 6.4 asks for one establishment registry across every establishment, and
the four new types follow the same linking pattern as hotels/airlines/transport:
the catalogue apps already own their rows, so an ``Establishment`` carries a
generic foreign key onto the existing ``resorts.Resort``,
``restaurants.Restaurant``, ``staycations.Staycation`` or ``landmarks.Landmark``
row. Linking them here means the instructor's establishment picker has something
to assign the three new operational roles to, immediately after a deploy.
"""

from django.db import migrations


def backfill_linked_establishments(apps, schema_editor):
    Establishment = apps.get_model('establishments', 'Establishment')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    linked = (
        ('RESORT', 'resorts', 'Resort', ('barangay', 'municipality', 'province', 'country')),
        ('RESTAURANT', 'restaurants', 'Restaurant', ('location', 'country')),
        ('STAYCATION', 'staycations', 'Staycation', ('barangay', 'municipality', 'province', 'country')),
        ('LANDMARK', 'landmarks', 'Landmark', ('barangay', 'municipality', 'province', 'country')),
    )

    for establishment_type, app_label, model_name, address_parts in linked:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover - all four apps are installed
            continue

        content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
        for row in model.objects.all().iterator():
            if Establishment.objects.filter(
                    entity_type=content_type, entity_id=row.pk).exists():
                continue

            status = 'ACTIVE' if getattr(row, 'status', '') == 'ACTIVE' else 'INACTIVE'

            Establishment.objects.create(
                name=(row.name or '')[:150],
                type=establishment_type,
                status=status,
                address=', '.join(
                    part for part in (getattr(row, name, '') or ''
                                      for name in address_parts) if part
                )[:255],
                contact_number=(getattr(row, 'contact_number', '') or '')[:20],
                email=(getattr(row, 'email', '') or '')[:254],
                entity_type=content_type,
                entity_id=row.pk,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('establishments', '0002_alter_establishment_type'),
        ('landmarks', '0001_initial'),
        ('resorts', '0001_initial'),
        ('restaurants', '0001_initial'),
        ('staycations', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_linked_establishments, migrations.RunPython.noop),
    ]