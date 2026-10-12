"""Centralized ``Establishment`` registry for the A TRUE simulation.

Section 8 of the requirements asks for ONE establishment concept that covers all
five business categories (hotel, airline, travel agency, tour operator,
transportation agency) so an instructor can pick "Hotel ABC" once and the
transaction engine can then route work to whichever students are assigned there.

The registry deliberately does not *copy* the platform's existing hotel, airline
and transport records (Section 8.1: "Do not duplicate establishment records
unnecessarily"). An :class:`Establishment` of type HOTEL/AIRLINE/TRANSPORTATION
carries a foreign key onto the existing ``hotels.Hotel``, ``airlines.Airline`` or
``transportation.Agency`` row, so there is still exactly one record for each real
business. Travel agencies and tour operators have no pre-existing table in this
project, so those two establishment types own their descriptive fields directly
(name/address/contact) - see the type docstring below.

Two lookup helpers keep the per-app code readable and stop ``Establishment``
growing a fifth nullable foreign key every time a new category is added:

* :func:`establishment_for_instance` - wrap an existing catalogue row,
* :func:`resolve_establishment` - the write path used by the simulation engine.
"""

from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction as db_transaction
from django.utils import timezone


class Establishment(models.Model):
    """One simulated business: a hotel, airline, agency, tour operator, etc.

    ``entity_type``/``entity_id`` is the link to the existing catalogue row for
    the three categories that already have one. It is deliberately a generic
    relation rather than three nullable columns so the model does not have to
    change every time a category is introduced, and so the "which catalogue row
    does this establishment represent?" question has exactly one answer.
    """

    class Type(models.TextChoices):
        HOTEL = 'HOTEL', 'Hotel'
        RESORT = 'RESORT', 'Resort'
        RESTAURANT = 'RESTAURANT', 'Restaurant'
        STAYCATION = 'STAYCATION', 'Staycation'
        LANDMARK = 'LANDMARK', 'Landmark'
        AIRLINE = 'AIRLINE', 'Airline'
        TRAVEL_AGENCY = 'TRAVEL_AGENCY', 'Travel Agency'
        TOUR_OPERATOR = 'TOUR_OPERATOR', 'Tour Operator'
        TRANSPORTATION = 'TRANSPORTATION', 'Transportation Agency'
        #: One establishment per individual Activity / Tour Package, so the
        #: instructor can assign a student to a single activity or package the
        #: same way a hotel assignment names one hotel (Section 6.4).
        ACTIVITY = 'ACTIVITY', 'Activity'
        TOUR_PACKAGE = 'TOUR_PACKAGE', 'Tour Package'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    #: Category -> {app_label, model_name} of the existing catalogue row this
    #: establishment type wraps. TRAVEL_AGENCY and TOUR_OPERATOR have no
    #: pre-existing catalogue table in this project, so they own their own
    #: descriptive fields instead of pointing at one.
    LINKED_TYPES = {
        Type.HOTEL: ('hotels', 'Hotel'),
        Type.RESORT: ('resorts', 'Resort'),
        Type.RESTAURANT: ('restaurants', 'Restaurant'),
        Type.STAYCATION: ('staycations', 'Staycation'),
        Type.LANDMARK: ('landmarks', 'Landmark'),
        Type.AIRLINE: ('airlines', 'Airline'),
        Type.TRANSPORTATION: ('transportation', 'Agency'),
        Type.ACTIVITY: ('activities', 'Activity'),
        Type.TOUR_PACKAGE: ('tour_package', 'TourPackage'),
    }

    name = models.CharField(max_length=150)
    establishment_id = models.CharField(
        max_length=12, unique=True, editable=False, null=True,
        verbose_name='Establishment ID')
    type = models.CharField(max_length=20, choices=Type.choices, db_index=True)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.ACTIVE, db_index=True)

    #: Link onto the existing catalogue row (Hotel / Airline / Agency). Null for
    #: TRAVEL_AGENCY and TOUR_OPERATOR, which have no catalogue table.
    entity_type = models.ForeignKey(
        'contenttypes.ContentType', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['type', 'name']
        indexes = [
            models.Index(fields=['type', 'status'], name='est_type_status_idx'),
        ]
        constraints = [
            # The same catalogue row may not back two establishments (that would
            # silently split an establishment's transactions in two). NULL entity
            # ids (travel agencies / tour operators) are exempt, since several of
            # those legitimately have no catalogue row.
            models.UniqueConstraint(
                fields=['entity_type', 'entity_id'],
                condition=models.Q(entity_id__isnull=False),
                name='unique_establishment_per_entity',
            ),
        ]

    # -- lifecycle ------------------------------------------------------------

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.establishment_id:
            self.establishment_id = f'EST-{self.pk:05d}'
            Establishment.objects.filter(pk=self.pk).update(
                establishment_id=self.establishment_id)

    def clean(self):
        super().clean()
        expected = self.LINKED_TYPES.get(self.type)
        if expected is None:
            # A category with no catalogue table: an entity link would point at
            # a row of the wrong app entirely.
            if self.entity_id:
                raise ValidationError({
                    'type': f'{self.get_type_display()} establishments do not link to a '
                            'catalogue record.',
                })
            return
        app_label, model_name = expected
        from django.apps import apps as django_apps

        try:
            model = django_apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover - app always installed
            return
        if self.entity_id and (self.entity_type_id is None
                               or self.entity_type.model_class() is not model):
            raise ValidationError({
                'entity_id': f'A {self.get_type_display()} establishment must link to a '
                              f'{app_label}.{model_name} record.',
            })

    # -- convenience ----------------------------------------------------------

    @property
    def entity(self):
        """The existing catalogue row this establishment represents, or None."""
        if not (self.entity_type_id and self.entity_id):
            return None
        model = self.entity_type.model_class()
        if model is None:  # pragma: no cover - content type was purged
            return None
        return model.objects.filter(pk=self.entity_id).first()

    @property
    def accepts_operations(self):
        return self.status == self.Status.ACTIVE

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'


# --------------------------------------------------------------------------- #
# Lookup helpers
# --------------------------------------------------------------------------- #

def linked_model_for(establishment_type):
    """Return the catalogue model an establishment *type* wraps, or None."""
    target = Establishment.LINKED_TYPES.get(str(establishment_type))
    if target is None:
        return None
    from django.apps import apps as django_apps

    app_label, model_name = target
    try:
        return django_apps.get_model(app_label, model_name)
    except LookupError:  # pragma: no cover - app always installed
        return None


def establishment_for_instance(instance, *, create=False, defaults=None):
    """Return the :class:`Establishment` wrapping ``instance``, optionally creating it.

    Used by the seeding commands and by tests so a `Hotel` row and its
    establishment never drift apart. Returns None when ``create`` is False and
    no establishment has been created yet - callers that need one must ask for
    ``create=True`` rather than silently getting None.
    """
    if instance is None:
        return None
    model = instance.__class__
    establishment_type = {
        'hotels.Hotel': Establishment.Type.HOTEL,
        'resorts.Resort': Establishment.Type.RESORT,
        'restaurants.Restaurant': Establishment.Type.RESTAURANT,
        'staycations.Staycation': Establishment.Type.STAYCATION,
        'landmarks.Landmark': Establishment.Type.LANDMARK,
        'airlines.Airline': Establishment.Type.AIRLINE,
        'transportation.Agency': Establishment.Type.TRANSPORTATION,
        'activities.Activity': Establishment.Type.ACTIVITY,
        'tour_package.TourPackage': Establishment.Type.TOUR_PACKAGE,
    }.get(f'{model._meta.app_label}.{model.__name__}')
    if establishment_type is None:
        return None

    content_type = ContentType.objects.get_for_model(model)
    existing = Establishment.objects.filter(
        entity_type=content_type, entity_id=instance.pk).first()
    if existing is not None or not create:
        return existing

    fields = {'name': str(instance), 'type': establishment_type,
              'status': Establishment.Status.ACTIVE}
    fields.update(defaults or {})
    address = _address_for(instance)
    if address:
        fields['address'] = address
    for source, target in (('contact_number', 'contact_number'), ('email', 'email'),
                           ('description', 'description')):
        value = getattr(instance, source, '')
        if value:
            fields[target] = value
    with db_transaction.atomic():
        establishment = Establishment.objects.create(**fields)
        establishment.entity_type = content_type
        establishment.entity_id = instance.pk
        establishment.save(update_fields=['entity_type', 'entity_id'])
    return establishment


#: Geographic fields, least to most specific, used to build an address for a
#: catalogue row that has no single address column of its own.
_ADDRESS_PARTS = ('address', 'barangay', 'municipality', 'province', 'country')

#: ``Hotel.location`` returns this when no geographic field is filled in; it is
#: a display placeholder, not an address, so it must never be copied.
_LOCATION_PLACEHOLDER = 'Location not set'


def _address_for(instance):
    """Best available address text for a catalogue row, or '' if it has none."""
    location = getattr(instance, 'location', '')
    if location and location != _LOCATION_PLACEHOLDER:
        return location[:255]
    parts = [getattr(instance, name, '') or '' for name in _ADDRESS_PARTS]
    return ', '.join(part for part in parts if part)[:255]


def resolve_establishment(*, establishment=None, entity=None, establishment_type=None,
                          name=None, create=True):
    """The single lookup used by the simulation engine to name an establishment.

    Accepts whichever of the three handles the caller happens to hold - an
    ``Establishment``, a catalogue row (``Hotel``/``Airline``/``Agency``) or a
    bare ``(type, name)`` pair for travel agencies and tour operators - and
    always returns one row, creating it when ``create`` is True.
    """
    if establishment is not None:
        if establishment.pk is None:
            establishment.save()
        return establishment
    if entity is not None:
        found = establishment_for_instance(entity, create=create)
        if found is not None:
            return found
    if establishment_type and name:
        defaults = {}
        with db_transaction.atomic():
            found = Establishment.objects.filter(
                type=establishment_type, name=name).first()
            if found is not None:
                return found
            if not create:
                return None
            return Establishment.objects.create(
                name=name, type=establishment_type, **defaults)
    return None


def ensure_linked_establishments():
    """Create establishments for every existing catalogue row.

    Run after the initial migration so the instructor has something to assign
    students to without hand-building the catalogue. Returns the number created.
    """
    created = 0
    for establishment_type in Establishment.LINKED_TYPES:
        model = linked_model_for(establishment_type)
        if model is None:  # pragma: no cover - apps always installed
            continue
        for row in model.objects.all().iterator():
            content_type = ContentType.objects.get_for_model(model)
            if Establishment.objects.filter(
                    entity_type=content_type, entity_id=row.pk).exists():
                continue
            establishment_for_instance(row, create=True)
            created += 1
    return created