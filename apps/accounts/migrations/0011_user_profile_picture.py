from django.db import migrations, models

import accounts.models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_alter_user_account_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_picture',
            field=models.ImageField(
                blank=True,
                upload_to=accounts.models.profile_picture_upload_to,
            ),
        ),
    ]
