from django.db import migrations


def seed_baguio_photo(apps, schema_editor):
    Hotel = apps.get_model('hotels', 'Hotel')
    HotelPhoto = apps.get_model('hotels', 'HotelPhoto')
    hotel = Hotel.objects.filter(name__iexact='Baguio Pinecrest Hotel').first()
    if hotel and not HotelPhoto.objects.filter(hotel=hotel).exists():
        HotelPhoto.objects.create(
            hotel=hotel,
            image='hotel_photos/baguio-pinecrest-placeholder.png',
            caption='Baguio Pinecrest Hotel property image',
            is_primary=True,
        )


def remove_baguio_photo(apps, schema_editor):
    HotelPhoto = apps.get_model('hotels', 'HotelPhoto')
    HotelPhoto.objects.filter(
        image='hotel_photos/baguio-pinecrest-placeholder.png'
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('hotels', '0016_hotelphoto')]
    operations = [migrations.RunPython(seed_baguio_photo, remove_baguio_photo)]
