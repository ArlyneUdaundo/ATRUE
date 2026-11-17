from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0050_mark_existing_fare_rules_configured'),
    ]

    operations = [
        migrations.AddField(
            model_name='flight',
            name='seat_type_prices',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Per-flight seat type prices keyed by seat type code. "
                    "Blank types use the aircraft layout's configured price."
                ),
            ),
        ),
    ]
