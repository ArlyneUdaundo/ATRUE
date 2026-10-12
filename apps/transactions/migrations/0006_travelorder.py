from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import transactions.models


class Migration(migrations.Migration):
    dependencies = [('transactions', '0005_alter_bill_items')]
    operations = [
        migrations.CreateModel(
            name='TravelOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_reference', models.CharField(default=transactions.models._order_ref, editable=False, max_length=30, unique=True)),
                ('status', models.CharField(choices=[('CART','Cart'),('PENDING','Pending Payment'),('CONFIRMED','Confirmed'),('CANCELLED','Cancelled'),('COMPLETED','Completed')], default='PENDING', max_length=15)),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('balance_due', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('payment_method', models.CharField(blank=True, choices=[('GCASH','GCash'),('BANK_TRANSFER','Bank Transfer'),('CREDIT_CARD','Credit Card'),('DEBIT_CARD','Debit Card'),('CASH','Cash'),('E_WALLET','E-Wallet')], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('bill', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='travel_order', to='transactions.bill')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='travel_orders', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='TravelOrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveBigIntegerField()),
                ('service', models.CharField(max_length=30)),
                ('description', models.CharField(max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='contenttypes.contenttype')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='transactions.travelorder')),
            ],
            options={'ordering': ['id']},
        ),
    ]
