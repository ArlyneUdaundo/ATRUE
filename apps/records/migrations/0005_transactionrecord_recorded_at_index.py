from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('records', '0004_alter_transactionrecord_record_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transactionrecord',
            name='recorded_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]