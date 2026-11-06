"""Automatic logo lookup when a new airline record is committed."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Airline


@receiver(post_save, sender=Airline, dispatch_uid='airlines.store_logo_on_create')
def store_airline_logo_on_create(sender, instance, created, raw=False, **kwargs):
    if raw:
        return

    # Retry a temporary lookup failure on the next airline save.
    from .models import AirlinePhoto
    if not created and AirlinePhoto.objects.filter(
            airline_id=instance.pk, is_locked_logo=True).exists():
        return

    airline_id = instance.pk

    def store_logo():
        from .logo_service import ensure_airline_logo
        ensure_airline_logo(airline_id)

    transaction.on_commit(store_logo)
