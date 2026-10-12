from django.db import migrations, models
import atrue_core.models


def _ref(prefix="ACTIVITY"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def populate_booking_reference_forward(apps, schema_editor):
    Booking = apps.get_model("activities", "Booking")
    for obj in Booking.objects.all():
        if not obj.booking_reference:
            obj.booking_reference = _ref("ACTIVITY")
            obj.save(update_fields=["booking_reference"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("activities", "0006_remove_booking_booking_reference"),
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
        migrations.RemoveField(model_name="booking", name="age"),
        migrations.RemoveField(model_name="booking", name="contact_number"),
        migrations.RemoveField(model_name="booking", name="email"),
        migrations.RemoveField(model_name="booking", name="emergency_contact_name"),
        migrations.RemoveField(model_name="booking", name="emergency_contact_number"),
        migrations.RemoveField(model_name="booking", name="emergency_contact_relationship"),
        migrations.RemoveField(model_name="booking", name="first_name"),
        migrations.RemoveField(model_name="booking", name="gender"),
        migrations.RemoveField(model_name="booking", name="last_name"),
        migrations.RemoveField(model_name="booking", name="middle_name"),
        migrations.RemoveField(model_name="booking", name="primary_participant_name"),
        migrations.AddField(model_name="activity", name="location", field=models.CharField(default="", max_length=255)),
        migrations.AddField(model_name="activity", name="location_barangay", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="activity", name="location_municipality", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="activity", name="location_province", field=models.CharField(blank=True, default="", max_length=100)),
    ]
