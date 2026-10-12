from django.db import migrations, models
import atrue_core.models


def _ref(prefix="TICKET"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def populate_booking_reference_forward(apps, schema_editor):
    Ticket = apps.get_model("landmarks", "Ticket")
    for obj in Ticket.objects.all():
        if not obj.booking_reference:
            obj.booking_reference = _ref("TICKET")
            obj.save(update_fields=["booking_reference"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("landmarks", "0006_remove_ticket_ticket_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
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
            model_name="ticket",
            name="booking_reference",
            field=models.CharField(
                max_length=30, unique=True, editable=False,
                default=atrue_core.models.make_booking_reference,
                help_text="Unique booking reference (BR-017, BR-033, BR-090)",
            ),
        ),
        migrations.RemoveField(model_name="ticket", name="contact_number"),
        migrations.RemoveField(model_name="ticket", name="primary_guest_name"),
        migrations.RemoveField(model_name="ticket", name="visitor_age"),
        migrations.RemoveField(model_name="ticket", name="visitor_email"),
    ]
