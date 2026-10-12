from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("hotels", "0015_booking_checked_in_at_booking_checked_out_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="HotelPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="hotel_photos/")),
                ("caption", models.CharField(blank=True, max_length=150)),
                ("is_primary", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("hotel", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="photos", to="hotels.hotel")),
            ],
            options={"ordering": ["-is_primary", "id"]},
        ),
    ]
