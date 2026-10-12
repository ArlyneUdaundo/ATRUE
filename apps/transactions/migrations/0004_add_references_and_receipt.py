from django.db import migrations, models
import django.db.models.deletion
import transactions.models
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
            field=models.CharField(default=transactions.models._bill_ref, max_length=30, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="additionaltransaction",
            name="transaction_reference",
            field=models.CharField(default=transactions.models._trx_ref, max_length=30, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="payment",
            name="payment_reference",
            field=models.CharField(default=transactions.models._pay_ref, max_length=30, unique=True, editable=False),
        ),
        migrations.CreateModel(
            name="Receipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("receipt_reference", models.CharField(default=transactions.models._rct_ref, editable=False, max_length=30, unique=True)),
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
