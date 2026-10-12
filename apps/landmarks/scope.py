from atrue_core.establishment_scope import EstablishmentScope
from .models import Ticket


def _ticket_landmark_ids(pk):
    return set(
        Ticket.objects.filter(pk=pk, destination_id__isnull=False)
        .values_list('destination_id', flat=True)
    )


landmark_scope = EstablishmentScope(
    establishment_type='LANDMARK',
    module='landmarks',
    list_views={'manage', 'bookings'},
    platform_views=set(),
    id_resolvers={'booking_id': _ticket_landmark_ids},
    allowed_attr='allowed_landmark_ids',
    assignment_attr='assigned_landmark_assignment',
    query_param='landmark',
    entity_label='landmark',
)
