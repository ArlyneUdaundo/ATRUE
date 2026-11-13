from django.db import migrations


def mark_existing_rules_configured(apps, schema_editor):
    AirlineFareRule = apps.get_model('airlines', 'AirlineFareRule')
    AirlineFareRule.objects.filter(is_configured=False).update(is_configured=True)


class Migration(migrations.Migration):

    dependencies = [
        ('airlines', '0049_bookingseat_infant_fee_amount_and_more'),
    ]

    operations = [
        migrations.RunPython(mark_existing_rules_configured, migrations.RunPython.noop),
    ]
