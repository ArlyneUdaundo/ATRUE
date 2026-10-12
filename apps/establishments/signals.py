"""Keep each catalogue entry visible in the shared Establishment registry."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from activities.models import Activity
from airlines.models import Airline
from hotels.models import Hotel
from landmarks.models import Landmark
from restaurants.models import Restaurant
from resorts.models import Resort
from staycations.models import Staycation
from tour_package.models import TourPackage
from transportation.models import Agency

from .models import establishment_for_instance

ESTABLISHMENT_NAME_MAX_LENGTH = 150


def _maintain_wrapper(sender, instance, created, **kwargs):
    establishment = establishment_for_instance(instance, create=created)
    if establishment is None or created:
        return
    name = str(instance)[:ESTABLISHMENT_NAME_MAX_LENGTH]
    if establishment.name != name:
        establishment.name = name
        establishment.save(update_fields=['name'])


@receiver(post_save, sender=Activity)
@receiver(post_save, sender=TourPackage)
@receiver(post_save, sender=Hotel)
@receiver(post_save, sender=Resort)
@receiver(post_save, sender=Restaurant)
@receiver(post_save, sender=Staycation)
@receiver(post_save, sender=Landmark)
@receiver(post_save, sender=Airline)
@receiver(post_save, sender=Agency)
def auto_establish(sender, instance, created, **kwargs):
    if created:
        from .models import Establishment

        status = (Establishment.Status.ACTIVE if getattr(instance, 'status', '') == 'ACTIVE'
                  else Establishment.Status.INACTIVE)
        establishment_for_instance(instance, create=True, defaults={'status': status})
        return
    _maintain_wrapper(sender, instance, created, **kwargs)
