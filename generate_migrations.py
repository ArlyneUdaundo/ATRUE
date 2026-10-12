"""Generate proper migrations that handle SQLite's callable-default limitation."""
import os

MIGRATION_TEMPLATE = '''\
from django.db import migrations, models
import atrue_core.models


def _ref(prefix="{prefix}"):
    return f"{{prefix}}-{{uuid.uuid4().hex[:8].upper()}}"


def populate_booking_reference_forward(apps, schema_editor):
    {model} = apps.get_model("{app}", "{model_name}")
    for obj in {model}.objects.all():
        if not obj.booking_reference:
            obj.booking_reference = _ref("{prefix}")
            obj.save(update_fields=["booking_reference"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("{app}", "{dep}"),
    ]

    operations = [
        migrations.AddField(
            model_name="{model_name_lower}",
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
            model_name="{model_name_lower}",
            name="booking_reference",
            field=models.CharField(
                max_length=30, unique=True, editable=False,
                default=atrue_core.models.make_booking_reference,
                help_text="Unique booking reference (BR-017, BR-033, BR-090)",
            ),
        ),
{extra_ops}
    ]
'''

BOOKING_MODELS = [
    ("hotels", "Booking", "HOTEL", "0007_remove_booking_booking_reference", "0008"),
    ("resorts", "Reservation", "RESORT", "0006_remove_reservation_reservation_reference", "0007"),
    ("staycations", "Reservation", "STAY", "0006_remove_reservation_reservation_reference", "0007"),
    ("restaurants", "Reservation", "RESTO", "0006_remove_reservation_reservation_reference", "0007"),
    ("airlines", "Booking", "FLIGHT", "0007_remove_booking_booking_reference", "0008"),
    ("transportation", "Booking", "TRANS", "0005_remove_booking_booking_reference", "0006"),
    ("landmarks", "Ticket", "TICKET", "0006_remove_ticket_ticket_reference", "0007"),
    ("activities", "Booking", "ACTIVITY", "0006_remove_booking_booking_reference", "0007"),
    ("packages", "Booking", "PACKAGE", "0006_remove_booking_booking_reference", "0007"),
]

EXTRA_OPS = {
    "activities": """\
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
        migrations.AddField(model_name="activity", name="location_province", field=models.CharField(blank=True, default="", max_length=100)),""",
    "airlines": """\
        migrations.RemoveField(model_name="booking", name="contact_email"),
        migrations.RemoveField(model_name="booking", name="contact_number"),
        migrations.RemoveField(model_name="booking", name="primary_guest_name"),
        migrations.AddConstraint(model_name="bookingseat", constraint=models.UniqueConstraint(fields=["booking", "seat_number"], condition=models.Q(seat_number__gt=""), name="unique_seat_per_booking")),""",
    "hotels": """\
        migrations.RemoveField(model_name="booking", name="primary_guest_name"),""",
    "landmarks": """\
        migrations.RemoveField(model_name="ticket", name="contact_number"),
        migrations.RemoveField(model_name="ticket", name="primary_guest_name"),
        migrations.RemoveField(model_name="ticket", name="visitor_age"),
        migrations.RemoveField(model_name="ticket", name="visitor_email"),""",
    "packages": """\
        migrations.RemoveField(model_name="booking", name="contact_number"),
        migrations.RemoveField(model_name="booking", name="primary_traveler_name"),""",
    "resorts": """\
        migrations.RemoveField(model_name="reservation", name="primary_guest_name"),""",
    "restaurants": """\
        migrations.RemoveField(model_name="reservation", name="contact_number"),
        migrations.RemoveField(model_name="reservation", name="primary_guest_name"),""",
    "staycations": """\
        migrations.RemoveField(model_name="reservation", name="primary_guest_name"),""",
    "transportation": """\
        migrations.RemoveField(model_name="booking", name="primary_guest_name"),""",
}

for app, model, prefix, dep, migration_num in BOOKING_MODELS:
    migration_file = f"apps/{app}/migrations/{migration_num}_add_booking_reference.py"
    content = MIGRATION_TEMPLATE.format(
        app=app,
        model=model,
        model_name=model,
        model_name_lower=model.lower(),
        prefix=prefix,
        dep=dep,
        extra_ops=EXTRA_OPS.get(app, ""),
    )
    os.makedirs(f"apps/{app}/migrations", exist_ok=True)
    with open(migration_file, "w") as f:
        f.write(content)
    print(f"Created {migration_file}")

# Transactions migration (no callable-default issue for bill_reference etc since Bill may have rows too)
TRANS_CONTENT = '''\
from django.db import migrations, models
import django.db.models.deletion
import uuid


def _ref(prefix="TRX"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def populate_references(apps, schema_editor):
    Bill = apps.get_model("transactions", "Bill")
    for obj in Bill.objects.all():
        if not obj.bill_reference:
            obj.bill_reference = _ref("BILL")
            obj.save(update_fields=["bill_reference"])
    Payment = apps.get_model("transactions", "Payment")
    for obj in Payment.objects.all():
        if not obj.payment_reference:
            obj.payment_reference = _ref("PAY")
            obj.save(update_fields=["payment_reference"])
    AdditionalTransaction = apps.get_model("transactions", "AdditionalTransaction")
    for obj in AdditionalTransaction.objects.all():
        if not obj.transaction_reference:
            obj.transaction_reference = _ref("TRX")
            obj.save(update_fields=["transaction_reference"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0003_remove_additionaltransaction_original_booking_reference_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bill",
            name="bill_reference",
            field=models.CharField(default="", max_length=30, editable=False),
        ),
        migrations.AddField(
            model_name="bill",
            name="content_type",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="bill",
            name="object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="payment_reference",
            field=models.CharField(default="", max_length=30, editable=False),
        ),
        migrations.AddField(
            model_name="payment",
            name="content_type",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cancellation",
            name="content_type",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="cancellation",
            name="object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="additionaltransaction",
            name="transaction_reference",
            field=models.CharField(default="", max_length=30, editable=False),
        ),
        migrations.AddField(
            model_name="additionaltransaction",
            name="content_type",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="additionaltransaction",
            name="object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(populate_references, noop),
        migrations.AlterField(
            model_name="bill",
            name="bill_reference",
            field=models.CharField(default=_ref, max_length=30, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="payment",
            name="payment_reference",
            field=models.CharField(default=_ref, max_length=30, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="additionaltransaction",
            name="transaction_reference",
            field=models.CharField(default=_ref, max_length=30, unique=True, editable=False),
        ),
        migrations.CreateModel(
            name="Receipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("receipt_reference", models.CharField(editable=False, max_length=30, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("remark", models.CharField(blank=True, max_length=255)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("bill", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="receipts", to="transactions.bill")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="accounts.user")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="transactions.payment")),
            ],
            options={
                "ordering": ["-issued_at"],
            },
        ),
    ]
'''

with open("apps/transactions/migrations/0004_add_references_and_receipt.py", "w") as f:
    f.write(TRANS_CONTENT)
print("Created transactions migration")

print("\nAll migrations created!")

