"""Move the old preset-code columns aside so the real foreign keys can take
their names.

``Aircraft.aircraft_type`` was a body-class string and ``seat_layout`` a preset
key on three different models.  The new columns want those exact names, and a
field cannot be added and removed under one name inside a single migration
without Django losing track of which is which, so the old ones are renamed to
``legacy_*`` here and dropped in 0026/0027 once the data has been carried over.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0024_fleet_aircraft_types_and_seat_layouts'),
    ]

    operations = [
        migrations.RenameField(
            model_name='airline',
            old_name='seat_layout',
            new_name='legacy_seat_layout',
        ),
        migrations.RenameField(
            model_name='flight',
            old_name='seat_layout',
            new_name='legacy_seat_layout',
        ),
        migrations.RenameField(
            model_name='aircraft',
            old_name='model_name',
            new_name='legacy_model_name',
        ),
        migrations.RenameField(
            model_name='aircraft',
            old_name='aircraft_type',
            new_name='legacy_body_class',
        ),
        migrations.RenameField(
            model_name='aircraft',
            old_name='seat_layout',
            new_name='legacy_seat_layout',
        ),
    ]
