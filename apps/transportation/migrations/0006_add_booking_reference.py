from django.db import migrations, models
import atrue_core.models


def _ref(prefix="TRANS"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def populate_booking_reference_forward(apps, schema_editor):
    Booking = apps.get_model("transportation", "Booking")
    for obj in Booking.objects.all():
        if not obj.booking_reference:
            obj.booking_reference = _ref("TRANS")
            obj.save(update_fields=["booking_reference"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("transportation", "0005_remove_booking_booking_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="booking_reference",
            field=models.CharField(
                max_length=30, default="", editable=False,
                help_text="Unique booking reference (BR-017, BR-033, BR-090)",
            ),
        ),
        migrations.RunPython(
            populate_booking_reference_forward, noop,
        ),
        migrations.AlterField(
            model_name="booking",
            name="booking_reference",
            field=models.CharField(
                max_length=30, unique=True, editable=False,
                default=atrue_core.models.make_booking_reference,
                help_text="Unique booking reference (BR-017, BR-033, BR-090)",
            ),
        ),
        migrations.RemoveField(model_name="booking", name="primary_guest_name"),
    ]
