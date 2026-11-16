from django.urls import reverse
from django import template

from ..cancellation import (
    booking_owner_id,
    can_request_cancellation,
    latest_cancellation_request,
    pending_cancellation_request,
)

register = template.Library()


@register.inclusion_tag('transactions/_cancellation_panel.html', takes_context=True)
def cancellation_panel(context, booking):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if booking is None or booking.pk is None:
        return {'booking': None}
    cancel_url = reverse(
        'transactions:request_cancellation',
        args=[booking._meta.app_label, booking._meta.model_name, booking.pk])
    return {
        'booking': booking,
        'cancel_url': cancel_url,
        'pending_cancellation': pending_cancellation_request(booking),
        'latest_cancellation': latest_cancellation_request(booking),
        'can_request': bool(
            user is not None and user.is_authenticated
            and booking_owner_id(booking) == user.pk
            and can_request_cancellation(booking, user)),
    }
