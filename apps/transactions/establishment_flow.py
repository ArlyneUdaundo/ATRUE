"""Per-establishment booking flow.

Bookings made from the same establishment are staged together without using
Trip Cart.  The guest can select another room/unit/table/flight/vehicle from
the same establishment and then pay once for the grouped booking.
"""
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

SESSION_KEY = 'atrue_establishment_booking'


def _booking_key(booking):
    ct = ContentType.objects.get_for_model(booking)
    return f'{ct.app_label}:{ct.model}:{booking.pk}'


def establishment_info(booking):
    app = booking._meta.app_label
    if app == 'hotels':
        room = booking.room_entries.select_related('room__hotel').first()
        est = room.room.hotel if room else None
        return ('hotels', getattr(est, 'pk', None), getattr(est, 'name', 'Hotel'), reverse('hotels:detail', args=[est.slug]) if est else reverse('hotels:list'))
    if app == 'resorts':
        est = booking.unit.resort
        return ('resorts', est.pk, est.name, reverse('resorts:detail', args=[est.slug]))
    if app == 'staycations':
        est = booking.staycation
        return ('staycations', est.pk, est.name, reverse('staycations:detail', args=[est.slug]))
    if app == 'restaurants':
        est = booking.table.restaurant
        return ('restaurants', est.pk, est.name, reverse('restaurants:detail', args=[est.slug]))
    if app == 'activities':
        est = booking.activity.provider
        return ('activities', est.pk, est.name, reverse('activities:list'))
    if app == 'tour_package':
        est = booking.package
        return ('tour_package', est.pk, est.name, reverse('tour_package:list'))
    if app == 'landmarks':
        est = booking.destination
        return ('landmarks', getattr(est, 'pk', None), getattr(est, 'name', 'Attraction'), reverse('landmarks:list'))
    if app == 'airlines':
        est = booking.flight.airline
        return ('airlines', est.pk, est.name, reverse('airlines:list'))
    if app == 'transportation':
        est = booking.vehicle.agency
        return ('transportation', est.pk, est.name, reverse('transportation:list'))
    return (app, None, app.replace('_', ' ').title(), reverse('home'))


def add_booking(request, booking):
    app, est_id, name, return_url = establishment_info(booking)
    existing = request.session.get(SESSION_KEY)
    if existing and (existing.get('app') != app or existing.get('establishment_id') != est_id):
        # Never mix different establishments in this flow. The guest must use
        # Trip Cart for that use case.
        raise ValueError('A different establishment is already being booked. Use Trip Cart to combine different establishments.')
    keys = list(existing.get('keys', [])) if existing else []
    key = _booking_key(booking)
    if key not in keys:
        keys.append(key)
    request.session[SESSION_KEY] = {
        'app': app,
        'establishment_id': est_id,
        'establishment_name': name,
        'return_url': return_url,
        'keys': keys,
    }
    request.session.modified = True


def clear(request):
    request.session.pop(SESSION_KEY, None)
    request.session.modified = True


def resolve(request):
    from django.apps import apps
    data = request.session.get(SESSION_KEY) or {}
    resolved = []
    valid = []
    for key in data.get('keys', []):
        try:
            app_label, model_name, object_id = key.split(':', 2)
            model = apps.get_model(app_label, model_name)
            booking = model.objects.get(pk=int(object_id))
            owner = getattr(booking, 'customer_id', getattr(booking, 'passenger_id', None))
            if owner != request.user.id:
                continue
            if str(getattr(booking, 'status', '')).upper() in {'CANCELLED', 'DECLINED', 'COMPLETED', 'USED'}:
                continue
            info = establishment_info(booking)
            if info[0] != data.get('app') or info[1] != data.get('establishment_id'):
                continue
            valid.append(key)
            resolved.append((key, booking))
        except Exception:
            continue
    if valid != data.get('keys', []):
        if valid:
            data['keys'] = valid
            request.session[SESSION_KEY] = data
        else:
            clear(request)
    return resolved, (data if valid else {})
