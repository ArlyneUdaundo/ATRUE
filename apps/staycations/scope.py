"""Staycation-scoped access, wired from the generic establishment scope.

A student assigned a staycation role (``STAYCATION_MANAGER`` / reservation /
front desk) at ONE staycation is confined to that staycation: the management
lists filter to the assigned staycation, and an object-keyed view raises 403 as
soon as its staycation is not one of the student's. Instructors, administrators
and staff keep platform-wide access.
"""

from atrue_core.establishment_scope import EstablishmentScope

from .models import BlockOutDate, Reservation, Service


def _staycation_ids_from(pk):
    return set(BlockOutDate.objects.filter(pk=pk).values_list('staycation_id', flat=True))


def _service_ids_from(pk):
    return set(Service.objects.filter(pk=pk).values_list('staycation_id', flat=True))


def _booking_ids_from(pk):
    return set(Reservation.objects.filter(pk=pk).values_list('staycation_id', flat=True))


staycation_scope = EstablishmentScope(
    establishment_type='STAYCATION',
    module='staycations',
    list_views={'manage', 'services', 'bookings'},
    platform_views={'add_staycation'},
    id_resolvers={
        'staycation_id': lambda pk: {pk},
        'service_id': _service_ids_from,
        'block_id': _staycation_ids_from,
        'booking_id': _booking_ids_from,
    },
    allowed_attr='allowed_staycation_ids',
    assignment_attr='assigned_staycation_assignment',
    query_param='staycation',
    entity_label='staycation',
)