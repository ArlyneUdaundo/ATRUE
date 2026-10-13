from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from urllib.parse import urlparse
import hashlib
import hmac
import secrets
from datetime import timedelta

import datetime

from atrue_core.services import log_activity

from .forms import (AccountCreateForm, ProfilePhotoForm, UserAccountForm,
                   UserLoginForm, UserRegistrationForm)
from .models import ACCOUNT_TYPE_CHOICES, User
from .roles import effective_role_keys


def forgot_password_view(request):
    from django.conf import settings
    from django.utils import timezone
    from notifications.models import PasswordResetRequest, PasswordResetToken

    generic = 'If an account matches that email, password reset instructions will be sent shortly.'
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().casefold()[:254]
        ip = request.META.get('REMOTE_ADDR', '')[:64]
        secret = settings.SECRET_KEY.encode()
        digest = lambda value: hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()
        now = timezone.now()
        PasswordResetRequest.objects.filter(created_at__lt=now-timedelta(days=2)).delete()
        email_digest, ip_digest = digest(email), digest(ip)
        PasswordResetRequest.objects.create(email_digest=email_digest, ip_digest=ip_digest)
        limited = (PasswordResetRequest.objects.filter(email_digest=email_digest, created_at__gte=now-timedelta(hours=1)).count() > 5
                   or PasswordResetRequest.objects.filter(ip_digest=ip_digest, created_at__gte=now-timedelta(hours=1)).count() > 20)
        valid_email = bool(email)
        if valid_email:
            try:
                validate_email(email)
            except ValidationError:
                valid_email = False
        if valid_email and not limited:
            user = User.objects.filter(email__iexact=email, is_active=True).order_by('pk').first()
            if user and user.email:
                raw = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(raw.encode()).hexdigest()
                with transaction.atomic():
                    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
                    reset = PasswordResetToken.objects.create(
                        user=user, token_hash=token_hash, expires_at=now+timedelta(minutes=30))
                    transaction.on_commit(lambda pk=reset.pk, token=raw: __import__(
                        'notifications.email_service', fromlist=['deliver_password_reset']).deliver_password_reset(pk, token))
        if request.headers.get('X-ATRUE-RESET-MODAL') == '1':
            return JsonResponse({'ok': True, 'message': generic})
        return render(request, 'accounts/forgot_password.html', {'generic_message': generic}, status=200)
    return render(request, 'accounts/forgot_password.html')


def reset_password_view(request, user_id):
    from django.utils import timezone
    from notifications.models import PasswordResetToken

    response_status = 200
    success = False
    if request.method == 'POST':
        raw = (request.POST.get('token') or '')[:128]
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        with transaction.atomic():
            reset = PasswordResetToken.objects.select_for_update().filter(
                user_id=user_id, token_hash=token_hash, used_at__isnull=True,
                expires_at__gt=timezone.now()).select_related('user').first()
            if reset:
                form = SetPasswordForm(reset.user, request.POST)
                if form.is_valid():
                    form.save()
                    reset.used_at = timezone.now()
                    reset.save(update_fields=['used_at'])
                    PasswordResetToken.objects.filter(user=reset.user, used_at__isnull=True).update(used_at=timezone.now())
                    success = True
                else:
                    response_status = 400
            else:
                form = None
                response_status = 400
    else:
        form = None
    response = render(request, 'accounts/reset_password.html', {
        'form': form, 'success': success,
        'invalid_token': request.method == 'POST' and form is None,
    }, status=response_status)
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


def _next_target(request):
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    return next_url if next_url and urlparse(next_url).netloc == '' else None


def csrf_token_view(request):
    """Hand out the CSRF secret for *this request's* session.

    ``CSRF_USE_SESSIONS`` keeps the secret in the session, and per-tab context
    middleware makes that the tab's own session - so this returns the tab's
    token, not the browser-wide one, and a POST from any tab verifies against
    the session it will actually be checked against.

    Callers must be unauthenticated-tolerant: this is deliberately not
    ``login_required`` so it also works for a signed-out tab that still needs to
    post the sign-in form.
    """
    return JsonResponse({'csrf_token': get_token(request)})


@xframe_options_sameorigin
def login_view(request):
    modal_request = request.headers.get('X-ATRUE-LOGIN-MODAL') == '1'
    # Already signed in on this tab? Send them where they were going instead of
    # showing a sign-in form they cannot use.
    #
    # A full page request cannot carry the X-ATRUE-CTX header, so the tab token
    # travels in the query string. That makes one case impossible to handle on
    # the first hop: a pasted/typed/bookmarked URL, or any redirect chain that
    # dropped ?ctx=, arrives here with no token and is resolved against the
    # shared (anonymous) cookie session, so Django bounces it to this page.
    # The tab bootstrap then re-requests this page WITH ?ctx=, at which point
    # TabSessionMiddleware has bound the tab's own session and request.user is
    # genuinely authenticated. Without this early return the visitor sits on a
    # login form while actually being signed in, which reads as "my tab keeps
    # logging me out".
    # TabSessionMiddleware preserves ?ctx= across this redirect, so the target
    # is loaded in the same tab context.
    if request.user.is_authenticated:
        target = _next_target(request) or 'dashboard'
        if modal_request:
            return JsonResponse({'ok': True, 'redirect': redirect(target).url})
        return redirect(target)

    if request.method == 'GET':
        from django.urls import reverse
        from urllib.parse import urlencode
        params = {'signin': '1'}
        target = _next_target(request)
        if target:
            params['next'] = target
        if request.GET.get('ctx'):
            params['ctx'] = request.GET['ctx']
        return redirect(f"{reverse('home')}?{urlencode(params)}")

    form = UserLoginForm(request, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        target = _next_target(request) or 'dashboard'
        # No token -> session bookkeeping here: TabSessionMiddleware re-derives
        # the ctx -> session binding in its response phase, after login() has
        # recycled the session key. Binding here would record a stale key and
        # silently break every other tab.
        if modal_request:
            return JsonResponse({'ok': True, 'redirect': redirect(target).url})
        return redirect(target)
    if modal_request:
        errors = {
            field: [str(error) for error in field_errors]
            for field, field_errors in form.errors.items()
        }
        return JsonResponse({'ok': False, 'errors': errors}, status=400)
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    from django.conf import settings
    from django.utils import timezone

    from .models import AuthContext

    # Drop this session's tab bindings before the session is recycled. The tab
    # that is signing out is re-bound to its own now-anonymous session by
    # TabSessionMiddleware, so the "signed out" notice below reaches that tab
    # and no other; every other tab's binding is untouched.
    AuthContext.objects.filter(session_key=request.session.session_key).delete()
    # Abandoned signed-out workspaces would otherwise accumulate forever, since
    # they are no longer removed when a tab goes away. Anything older than the
    # session lifetime points at a session that has expired too.
    AuthContext.objects.filter(
        user__isnull=True,
        last_used__lt=timezone.now()
        - datetime.timedelta(seconds=settings.SESSION_COOKIE_AGE),
    ).delete()
    auth_logout(request)
    response = redirect('home')
    messages.success(request, 'You have been signed out. See you again!')
    return response


def register_view(request):
    """Public self-registration is disabled. Accounts are provisioned by
    an administrator/instructor through the account-management screen."""
    messages.info(request, 'Public sign-up is disabled. Please sign in with an account provided by the administrator or instructor.')
    return redirect('accounts:login')

def is_admin_user(user):
    from .roles import MANAGEMENT_ACCOUNT_TYPES, effective_role_keys
    return (
        user.is_staff
        or user.account_type in MANAGEMENT_ACCOUNT_TYPES
        or bool(effective_role_keys(user) & MANAGEMENT_ACCOUNT_TYPES)
    )


def is_account_manager(user):
    """FR module 1 account-management actors (Administrator, Instructor/Trainer)."""
    from .roles import ACCOUNT_MANAGER_TYPES, effective_role_keys
    return user.is_authenticated and (
        user.is_staff
        or user.account_type in ACCOUNT_MANAGER_TYPES
        or bool(effective_role_keys(user) & ACCOUNT_MANAGER_TYPES)
    )


def is_account_update_manager(user):
    """FR module 1 UPDATE – Administrator / System Administrator only. The
    Instructor/Trainer row is "—", so instructors update their own profile only."""
    from .roles import ACCOUNT_UPDATE_TYPES, effective_role_keys
    return user.is_authenticated and (
        user.is_staff
        or user.account_type in ACCOUNT_UPDATE_TYPES
        or bool(effective_role_keys(user) & ACCOUNT_UPDATE_TYPES)
    )


@login_required
def dashboard(request):
    user = request.user
    acct = user.account_type
    if acct in (User.AccountType.SYSTEM_ADMIN, User.AccountType.ADMIN):
        return render(request, 'system_admin_dashboard.html', system_admin_dashboard_context())
    if acct == User.AccountType.INSTRUCTOR:
        return render(request, 'admin_dashboard.html', admin_dashboard_context())
    from .roles import ROLE_DEFS, AIRLINE_STAFF_ROLE_KEYS
    if acct in ROLE_DEFS:
        return render(request, 'role_dashboard.html', role_dashboard_context(acct, user, request))
    # Students: reflect their most recent ACTIVE instructor-assigned role
    # so they land on the dashboard of the role they are simulating (BR-084).
    active_role = user.simulation_roles.filter(
        status='ACTIVE'
    ).order_by('-assigned_at').first()
    if active_role and active_role.role in ROLE_DEFS:
        return render(request, 'role_dashboard.html', role_dashboard_context(active_role.role, user, request))
    if AIRLINE_STAFF_ROLE_KEYS & set(effective_role_keys(user)):
        return render(
            request, 'role_dashboard.html',
            role_dashboard_context('AIRLINE_TICKETING_OFFICER', user, request),
        )
    return render(request, 'dashboard.html', student_dashboard_context(user, request))


def role_dashboard_context(account_type, user, request):
    from .roles import ROLE_DEFS, TIER_LABELS, effective_role_keys, AIRLINE_STAFF_ROLE_KEYS
    role = ROLE_DEFS[account_type]
    actions = list(role['actions'])
    permissions = list(role['permissions'])
    # Airline staff share one dashboard, whichever of the airline staff roles they
    # hold: the routes they may reach are the same set whichever code it is under.
    has_ticketing_role = bool(AIRLINE_STAFF_ROLE_KEYS & set(effective_role_keys(user)))
    if has_ticketing_role and account_type != 'AIRLINE_TICKETING_OFFICER':
        ticketing_role = ROLE_DEFS['AIRLINE_TICKETING_OFFICER']
        known_urls = {action['url'] for action in actions}
        actions.extend(
            action for action in ticketing_role['actions']
            if action['url'] not in known_urls
        )
        permissions.extend(
            permission for permission in ticketing_role['permissions']
            if permission not in permissions
        )
    context = {
        'role': role,
        'tier': role['tier'],
        'tier_label': TIER_LABELS.get(role['tier'], role['tier']),
        'current_role': user.simulation_roles.order_by('-assigned_at').first(),
        'permissions': permissions,
        'actions': actions,
    }
    if has_ticketing_role:
        from airlines.models import Booking

        context['ticketing_summary'] = {
            'reservations': Booking.objects.count(),
            'awaiting_confirmation': Booking.objects.filter(
                status=Booking.Status.PENDING,
            ).count(),
            'confirmed': Booking.objects.filter(
                status=Booking.Status.CONFIRMED,
            ).count(),
        }
    if role['tier'] in ('PLATFORM', 'MANAGEMENT'):
        context.update(admin_dashboard_context())
    else:
        context.update(student_dashboard_context(user, request))
    return context


def _collect_bookings(user):
    """Aggregate bookings across all service apps for dashboard search."""
    rows = []
    try:
        from hotels.models import Booking as HotelBooking
        for b in HotelBooking.objects.filter(customer=user).prefetch_related('rooms__hotel'):
            rows.append({'service': 'hotel', 'reference': b.booking_reference,
                         'details': ', '.join(room.hotel.name or '' for room in b.rooms.select_related('hotel').all()),
                         'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from resorts.models import Reservation as ResortReservation
        for b in ResortReservation.objects.filter(customer=user).select_related('unit__resort'):
            rows.append({'service': 'resort', 'reference': b.booking_reference,
                         'details': b.unit.resort.name, 'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from staycations.models import Reservation as StaycationReservation
        for b in StaycationReservation.objects.filter(customer=user).select_related('staycation'):
            rows.append({'service': 'staycation', 'reference': b.booking_reference,
                         'details': b.staycation.name, 'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from airlines.models import Booking as AirlineBooking
        for b in AirlineBooking.objects.filter(passenger=user).select_related('flight'):
            rows.append({'service': 'airline', 'reference': b.booking_reference,
                         'details': f"{b.flight.origin} → {b.flight.destination}",
                         'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from transportation.models import Booking as TransportBooking
        for b in TransportBooking.objects.filter(customer=user).select_related('vehicle__agency'):
            rows.append({'service': 'transport', 'reference': b.booking_reference,
                         'details': f"{b.vehicle.agency.name} - {b.vehicle.label}",
                         'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from restaurants.models import Reservation as RestoReservation
        for b in RestoReservation.objects.filter(customer=user).select_related('table__restaurant'):
            rows.append({'service': 'restaurant', 'reference': b.booking_reference,
                         'details': b.table.restaurant.name, 'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from landmarks.models import Ticket as LandmarkTicket
        for b in LandmarkTicket.objects.filter(customer=user).select_related('destination'):
            rows.append({'service': 'landmark', 'reference': b.booking_reference,
                         'details': b.destination.name, 'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from activities.models import Booking as ActivityBooking
        for b in ActivityBooking.objects.filter(customer=user).select_related('activity'):
            rows.append({'service': 'activity', 'reference': b.booking_reference,
                         'details': b.activity.name, 'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    try:
        from tour_package.models import Booking as TourPackageBooking
        for b in TourPackageBooking.objects.filter(customer=user).select_related('package'):
            rows.append({'service': 'package', 'reference': b.booking_reference,
                         'details': b.package.name, 'status': b.status, 'created': b.created_at})
    except Exception:
        pass
    return sorted(rows, key=lambda x: x['created'] or datetime.datetime(2000, 1, 1), reverse=True)


def student_dashboard_context(user, request):
    bookings = (
        user.airline_bookings.count() + user.hotel_bookings.count() +
        user.resort_reservations.count() + user.staycation_reservations.count() +
        user.restaurant_reservations.count() + user.transport_bookings.count() +
        user.attraction_tickets.count() + user.activity_bookings.count() +
        user.tour_package_bookings.count()
    )
    q = (request.GET.get('q') or '').strip()
    search_results = None
    if q:
        query = q.lower()
        search_results = [
            row for row in _collect_bookings(user)
            if query in row['service'].lower() or query in row['reference'].lower() or query in row['details'].lower()
        ]
    return {
        'total_bookings': bookings,
        'total_payments': user.payments.count(),
        'role_count': user.simulation_roles.count(),
        'activity_count': user.activity_logs.count(),
        'current_role': user.simulation_roles.order_by('-assigned_at').first(),
        'search_results': search_results,
        'q': q,
    }


def admin_dashboard_context():
    from django.db.models import Sum

    from activities.models import Booking as ActivityBooking
    from airlines.models import Booking as AirlineBooking
    from hotels.models import Booking as HotelBooking
    from landmarks.models import Ticket as LandmarkTicket
    from resorts.models import Reservation as ResortReservation
    from restaurants.models import Reservation as RestaurantReservation
    from simulation.models import ActivityLog, SimulationRoleAssignment
    from staycations.models import Reservation as StaycationReservation
    from tour_package.models import Booking as TourPackageBooking
    from transactions.models import Payment
    from transportation.models import Booking as TransportBooking

    package_total = TourPackageBooking.objects.count()

    service_breakdown = [
        ('Flights', AirlineBooking.objects.count(), 'fa-plane'),
        ('Hotels', HotelBooking.objects.count(), 'fa-hotel'),
        ('Resorts', ResortReservation.objects.count(), 'fa-umbrella-beach'),
        ('Staycations', StaycationReservation.objects.count(), 'fa-couch'),
        ('Restaurants', RestaurantReservation.objects.count(), 'fa-utensils'),
        ('Transportation', TransportBooking.objects.count(), 'fa-bus'),
        ('Landmarks', LandmarkTicket.objects.count(), 'fa-landmark'),
        ('Activities', ActivityBooking.objects.count(), 'fa-hiking'),
        ('Tour Packages', package_total, 'fa-suitcase-rolling'),
    ]
    total_bookings = sum(count for _, count, _ in service_breakdown)
    max_bookings = max((count for _, count, _ in service_breakdown), default=1)

    revenue = Payment.objects.aggregate(total=Sum('amount'))['total'] or 0

    return {
        'total_users': User.objects.count(),
        'total_students': User.objects.filter(account_type=User.AccountType.STUDENT).count(),
        'total_instructors': User.objects.filter(account_type__in=[
            User.AccountType.INSTRUCTOR, User.AccountType.ADMIN, User.AccountType.SYSTEM_ADMIN,
        ]).count(),
        'total_bookings': total_bookings,
        'total_payments': Payment.objects.count(),
        'total_revenue': revenue,
        'total_roles': SimulationRoleAssignment.objects.count(),
        'service_breakdown': service_breakdown,
        'max_bookings': max_bookings,
        'recent_payments': Payment.objects.select_related('customer').order_by('-id')[:6],
        'recent_users': User.objects.order_by('-date_joined')[:6],
        'recent_logs': ActivityLog.objects.select_related('user').order_by('-timestamp')[:6],
        'recent_roles': SimulationRoleAssignment.objects.select_related('student', 'assigned_by').order_by('-assigned_at')[:6],
    }


def system_admin_dashboard_context():
    """System Administrator dashboard: admin stats plus the full role matrix."""
    from collections import Counter

    from .roles import MANAGEMENT_ACCOUNT_TYPES
    from simulation.models import SimulationRoleAssignment

    context = admin_dashboard_context()
    counts = Counter(User.objects.values_list('account_type', flat=True))
    context['total_system_admins'] = counts.get('SYSTEM_ADMIN', 0)
    context['total_managers'] = sum(counts.get(acct, 0) for acct in MANAGEMENT_ACCOUNT_TYPES)
    context['role_matrix'] = [
        {
            'value': value,
            'label': label,
            'users': counts.get(value, 0),
            'assignments': SimulationRoleAssignment.objects.filter(role=value).count(),
        }
        for value, label in SimulationRoleAssignment.Role.choices
    ]
    return context


def _platform_booking_rows():
    """Aggregate every booking across all service apps for the dashboard stats page."""
    rows = []

    def _nm(person):
        if person is None:
            return '—'
        return person.get_full_name() or person.username

    try:
        from hotels.models import Booking as HotelBooking
        for b in HotelBooking.objects.select_related('customer').all():
            rows.append({'service': 'Hotel', 'icon': 'fa-hotel', 'reference': b.booking_reference,
                         'customer': _nm(b.customer),
                         'details': ', '.join(room.hotel.name or '' for room in b.rooms.select_related('hotel').all()),
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from resorts.models import Reservation as ResortReservation
        for b in ResortReservation.objects.select_related('customer', 'unit__resort').all():
            rows.append({'service': 'Resort', 'icon': 'fa-umbrella-beach', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': b.unit.resort.name,
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from staycations.models import Reservation as StaycationReservation
        for b in StaycationReservation.objects.select_related('customer', 'staycation').all():
            rows.append({'service': 'Staycation', 'icon': 'fa-couch', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': b.staycation.name,
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from airlines.models import Booking as AirlineBooking
        for b in AirlineBooking.objects.select_related('passenger', 'flight').all():
            rows.append({'service': 'Flight', 'icon': 'fa-plane', 'reference': b.booking_reference,
                         'customer': _nm(b.passenger),
                         'details': f"{b.flight.origin} → {b.flight.destination}",
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from transportation.models import Booking as TransportBooking
        for b in TransportBooking.objects.select_related('customer', 'vehicle__agency').all():
            rows.append({'service': 'Transport', 'icon': 'fa-bus', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': f"{b.vehicle.agency.name} - {b.vehicle.label}",
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from restaurants.models import Reservation as RestoReservation
        for b in RestoReservation.objects.select_related('customer', 'table__restaurant').all():
            rows.append({'service': 'Restaurant', 'icon': 'fa-utensils', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': b.table.restaurant.name,
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from landmarks.models import Ticket as LandmarkTicket
        for b in LandmarkTicket.objects.select_related('customer', 'destination').all():
            rows.append({'service': 'Landmark', 'icon': 'fa-landmark', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': b.destination.name,
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from activities.models import Booking as ActivityBooking
        for b in ActivityBooking.objects.select_related('customer', 'activity').all():
            rows.append({'service': 'Activity', 'icon': 'fa-hiking', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': b.activity.name,
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    try:
        from tour_package.models import Booking as TourPackageBooking
        for b in TourPackageBooking.objects.select_related('customer', 'package').all():
            rows.append({'service': 'Tour Package', 'icon': 'fa-suitcase-rolling', 'reference': b.booking_reference,
                         'customer': _nm(b.customer), 'details': b.package.name,
                         'status': b.get_status_display(), 'created': b.created_at})
    except Exception:
        pass
    return sorted(rows, key=lambda x: x['created'] or datetime.datetime(2000, 1, 1), reverse=True)


@login_required
def stats_list(request, kind):
    """Drill-down for each dashboard stat card: shows the recorded entries."""
    if not is_admin_user(request.user):
        messages.error(request, 'You are not authorised to view dashboard statistics.')
        return redirect('dashboard')

    from django.db.models import Sum

    from .roles import MANAGEMENT_ACCOUNT_TYPES
    from transactions.models import Payment

    kind = kind or ''
    if kind not in ('users', 'admins', 'managers', 'students', 'instructors', 'bookings', 'payments', 'revenue'):
        return redirect('dashboard')

    context = {'kind': kind, 'rows': [], 'title': 'Dashboard Detail'}

    if kind == 'users':
        context.update(title='All Users', icon='fa-users',
                       subtitle=f'{User.objects.count()} total account(s) registered on the platform.')
        context['rows'] = [
            {'name': u.get_full_name() or u.username, 'username': u.username, 'email': u.email or '—',
             'account_type': u.get_account_type_display(), 'status': u.get_status_display(),
             'date': u.date_joined, 'pk': u.pk}
            for u in User.objects.order_by('-date_joined')
        ]
    elif kind == 'admins':
        qs = User.objects.filter(account_type=User.AccountType.SYSTEM_ADMIN).order_by('-date_joined')
        context.update(title='System Admins', icon='fa-user-shield',
                       subtitle=f'{qs.count()} System Administrator account(s).')
        context['rows'] = [
            {'name': u.get_full_name() or u.username, 'username': u.username, 'email': u.email or '—',
             'account_type': u.get_account_type_display(), 'status': u.get_status_display(),
             'date': u.date_joined, 'pk': u.pk}
            for u in qs
        ]
    elif kind == 'managers':
        qs = User.objects.filter(account_type__in=MANAGEMENT_ACCOUNT_TYPES).order_by('-date_joined')
        context.update(title='Management Accounts', icon='fa-briefcase',
                       subtitle=f"{qs.count()} account(s) that manage platform modules.")
        context['rows'] = [
            {'name': u.get_full_name() or u.username, 'username': u.username, 'email': u.email or '—',
             'account_type': u.get_account_type_display(), 'status': u.get_status_display(),
             'date': u.date_joined, 'pk': u.pk}
            for u in qs
        ]
    elif kind == 'students':
        qs = User.objects.filter(account_type=User.AccountType.STUDENT).order_by('-date_joined')
        context.update(title='Students', icon='fa-graduation-cap',
                       subtitle=f'{qs.count()} student account(s).')
        context['rows'] = [
            {'name': u.get_full_name() or u.username, 'username': u.username, 'email': u.email or '—',
             'account_type': u.get_account_type_display(), 'status': u.get_status_display(),
             'date': u.date_joined, 'pk': u.pk}
            for u in qs
        ]
    elif kind == 'instructors':
        qs = User.objects.filter(account_type__in=[
            User.AccountType.INSTRUCTOR, User.AccountType.ADMIN, User.AccountType.SYSTEM_ADMIN,
        ]).order_by('-date_joined')
        context.update(title='Instructors', icon='fa-user-shield',
                       subtitle=f'{qs.count()} instructor/administrator account(s).')
        context['rows'] = [
            {'name': u.get_full_name() or u.username, 'username': u.username, 'email': u.email or '—',
             'account_type': u.get_account_type_display(), 'status': u.get_status_display(),
             'date': u.date_joined, 'pk': u.pk}
            for u in qs
        ]
    elif kind == 'bookings':
        rows = _platform_booking_rows()
        context.update(title='All Bookings', icon='fa-ticket-alt',
                       subtitle=f'{len(rows)} booking(s) recorded across every service module.')
        context['rows'] = rows
    elif kind in ('payments', 'revenue'):
        qs = Payment.objects.select_related('customer').order_by('-paid_at', '-id')
        context.update(title='Payments', icon='fa-credit-card',
                       subtitle=f'{qs.count()} payment(s) recorded.')
        context['rows'] = [
            {'reference': p.payment_reference, 'customer': (p.customer.get_full_name() or p.customer.username),
             'amount': p.amount, 'method': p.get_method_display(), 'status': p.get_status_display(),
             'date': p.paid_at}
            for p in qs
        ]
        if kind == 'revenue':
            total = Payment.objects.aggregate(total=Sum('amount'))['total'] or 0
            context.update(title='Revenue', icon='fa-coins',
                           subtitle=f"{qs.count()} payment(s) · ₱{total:,.2f} total collected.")
            context['total'] = total

    return render(request, 'dashboard_stats.html', context)


SORT_CHOICES = [
    ('-date_joined', 'Date Created (Newest first)'),
    ('date_joined', 'Date Created (Oldest first)'),
    ('first_name', 'Name (A–Z)'),
    ('-first_name', 'Name (Z–A)'),
    ('username', 'Username'),
    ('email', 'Email'),
    ('account_type', 'Account Type'),
    ('status', 'Status'),
]

SPAN_FIELDS = (
    'residential_address',
)

FORM_SECTIONS = (
    ('Personal Information', 'fa-id-card', ('last_name', 'first_name', 'middle_initial', 'middle_name', 'suffix', 'date_of_birth', 'sex')),
    ('Contact Details', 'fa-address-book', ('email', 'contact_number', 'nationality', 'residential_address')),
    ('Emergency Contact', 'fa-phone-volume', ('emergency_contact_name', 'emergency_contact_number', 'emergency_contact_relationship')),
    ('Profile Picture', 'fa-image', ('profile_picture',)),
    ('Account & Security', 'fa-user-shield', ('account_type', 'status', 'username', 'password1', 'password2')),
)


def _require_account_manager(user):
    if not user.is_authenticated:
        return 'Please sign in.'
    if not is_account_manager(user):
        return 'You are not authorised to manage user accounts.'
    return None


#: Only the Administrator and Instructor/Trainer may create user accounts.
CREATOR_ACCOUNT_TYPES = frozenset({
    User.AccountType.ADMIN,
    User.AccountType.INSTRUCTOR,
})


def _require_creator(user):
    if not user.is_authenticated:
        return 'Please sign in.'
    if user.account_type not in CREATOR_ACCOUNT_TYPES:
        return 'Only the Administrator and Instructor/Trainer may create user accounts.'
    return None


@login_required
def account_create(request):
    """FR-001 Create User Account.

    Only the Administrator and Instructor/Trainer may create accounts; the
    chosen username and password are stored exactly as entered so the new user
    can sign in immediately.
    """
    error = _require_creator(request.user)
    if error:
        messages.error(request, error)
        return redirect('dashboard')
    form = AccountCreateForm(request.POST or None, creator=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Account created successfully.')
        return redirect('accounts:account_list')
    return render(request, 'accounts/account_form.html', {
        'form': form,
        'is_create': True,
        'span_fields': SPAN_FIELDS,
        'form_sections': tuple(section for section in FORM_SECTIONS if section[0] != 'Profile Picture'),
        'page_title': 'Create User Account',
        'page_subtitle': 'Register a new account (FR-001).',
    })


@login_required
def account_list(request):
    """FR-002 RETRIEVE User Account – search and filter matching accounts."""
    error = _require_account_manager(request.user)
    if error:
        messages.error(request, error)
        return redirect('dashboard')

    qs = User.objects.all()
    q = (request.GET.get('q') or '').strip()
    acct_type = (request.GET.get('account_type') or '').strip()
    status = (request.GET.get('status') or '').strip()
    role = (request.GET.get('role') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    sort = (request.GET.get('sort') or '-date_joined').strip()

    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                       Q(username__icontains=q) | Q(email__icontains=q))
    if acct_type:
        qs = qs.filter(account_type=acct_type)
    if status:
        qs = qs.filter(status=status)
    if role:
        qs = qs.filter(simulation_roles__role=role).distinct()
    if date_from:
        qs = qs.filter(date_joined__date__gte=date_from)
    if date_to:
        qs = qs.filter(date_joined__date__lte=date_to)
    if sort not in dict(SORT_CHOICES):
        sort = '-date_joined'
    qs = qs.order_by(sort)

    from simulation.models import SimulationRoleAssignment
    return render(request, 'accounts/account_list.html', {
        'accounts': qs,
        'q': q,
        'account_type': acct_type,
        'status': status,
        'role': role,
        'date_from': date_from,
        'date_to': date_to,
        'sort': sort,
        'account_type_choices': ACCOUNT_TYPE_CHOICES,
        'status_choices': User.Status.choices,
        'role_choices': SimulationRoleAssignment.Role.choices,
        'sort_choices': SORT_CHOICES,
        'can_update': is_account_update_manager(request.user),
    })


@login_required
def my_account(request):
    """FR-003 VIEW User Account – the signed-in user's own profile."""
    return redirect('accounts:account_detail', pk=request.user.pk)


@login_required
def account_detail(request, pk):
    """FR-003 VIEW User Account (owner or manager) with booking history summary.

    Also the endpoint the profile header's photo controls post to, so a rejected
    upload redisplay carries the form's own errors and the page keeps whatever
    else it was showing.
    """
    account = get_object_or_404(User, pk=pk)
    if account != request.user and not is_account_manager(request.user):
        messages.error(request, 'You may only view your own account.')
        return redirect('dashboard')
    can_update = account == request.user or is_account_update_manager(request.user)
    edit_form = None
    if can_update:
        edit_form = UserAccountForm(
            request.POST if request.method == 'POST' and request.POST.get('profile_update') == '1' else None,
            request.FILES if request.method == 'POST' and request.POST.get('profile_update') == '1' else None,
            instance=account,
            as_admin=is_account_update_manager(request.user),
            allow_profile_picture=(account == request.user),
        )
        if request.method == 'POST' and request.POST.get('profile_update') == '1':
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, 'Account information updated successfully.')
                return redirect('accounts:account_detail', pk=account.pk)
    can_change_password = account == request.user or is_account_update_manager(request.user)
    password_form = None
    password_post = request.method == 'POST' and request.POST.get('password_update') == '1'
    if can_change_password:
        if account == request.user:
            password_form = PasswordChangeForm(
                request.user,
                request.POST if password_post else None,
            )
        else:
            password_form = SetPasswordForm(
                user=account,
                data=request.POST if password_post else None,
            )
        if password_post and password_form.is_valid():
            updated_user = password_form.save()
            if account == request.user:
                update_session_auth_hash(request, updated_user)
                log_activity(updated_user, 'Changed password',
                             f"Password updated for {updated_user.get_full_name() or updated_user.username} (ID: {updated_user.pk}).")
                messages.success(request, 'Your password has been changed successfully.')
            else:
                log_activity(request.user, 'Changed user password',
                             f"Set a new password for {account.get_full_name() or account.username} (ID: {account.pk}).")
                messages.success(request,
                                 f"Password for {account.get_full_name() or account.username} has been updated.")
            return redirect('accounts:account_detail', pk=account.pk)
    photo_form = None
    if account == request.user:
        photo_post = request.method == 'POST' and request.POST.get('profile_update') != '1' and not password_post
        photo_form = ProfilePhotoForm(
            request.POST if photo_post else None,
            request.FILES if photo_post else None,
        )
        if photo_post:
            # An empty POST is the header's "no change" state, not a failed
            # upload, so it must not raise a spurious "this field is required".
            if photo_form.is_bound and photo_form.is_valid():
                photo_form.save(request.user)
                messages.success(request, 'Profile photo updated.')
                return redirect('accounts:account_detail', pk=account.pk)
    return render(request, 'accounts/account_detail.html', {
        'account': account,
        'bookings': _collect_bookings(account),
        'is_manager': is_account_manager(request.user),
        'is_update_manager': is_account_update_manager(request.user),
        'photo_form': photo_form,
        # The header's camera button opens the photo panel without a second
        # request, so the two controls cannot disagree about what is showing.
        'show_photo_editor': bool(photo_form and photo_form.errors),
        'edit_form': edit_form,
        'form_sections': FORM_SECTIONS,
        'span_fields': SPAN_FIELDS,
        'password_form': password_form,
    })


@login_required
def account_photo_remove(request, pk):
    """Remove the signed-in user's profile photo.

    A POST-only endpoint because it destroys a file. Separate from
    ``account_detail`` rather than another field on it so the destructive action
    cannot be triggered by the photo *upload* form being submitted, and so it is
    still reachable while the upload panel is closed.
    """
    account = get_object_or_404(User, pk=pk)
    if account != request.user:
        messages.error(request, 'You may only change your own profile photo.')
        return redirect('accounts:account_detail', pk=request.user.pk)
    if request.method != 'POST':
        return redirect('accounts:account_detail', pk=account.pk)
    if account.profile_picture:
        account.profile_picture.delete(save=False)
        account.profile_picture = None
        account.save(update_fields=['profile_picture'])
        messages.success(request, 'Profile photo removed.')
    else:
        messages.info(request, 'There was no profile photo to remove.')
    return redirect('accounts:account_detail', pk=account.pk)


@login_required
def account_update(request, pk):
    """FR-004 UPDATE User Account – the owner, or Administrator / System
    Administrator for other accounts (Instructor/Trainer: own profile only)."""
    account = get_object_or_404(User, pk=pk)
    if account != request.user and not is_account_update_manager(request.user):
        messages.error(request, 'You may only update your own account.')
        return redirect('accounts:account_detail', pk=account.pk)
    is_manager = is_account_update_manager(request.user)
    form = UserAccountForm(
        request.POST or None,
        request.FILES or None,
        instance=account,
        as_admin=is_manager,
        allow_profile_picture=(account == request.user),
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Account information updated successfully.')
        return redirect('accounts:account_detail', pk=account.pk)
    return render(request, 'accounts/account_form.html', {
        'form': form,
        'account': account,
        'is_create': False,
        'is_manager': is_manager,
        'span_fields': SPAN_FIELDS,
        'form_sections': FORM_SECTIONS,
        'page_title': 'Update User Account',
        'page_subtitle': 'Edit the account information and save your changes (FR-004).',
    })


@login_required
def account_deactivate_confirm(request, pk):
    """FR-005 DEACTIVATE confirmation page – captures optional reason."""
    error = _require_account_manager(request.user)
    if error:
        messages.error(request, error)
        return redirect('dashboard')
    account = get_object_or_404(User, pk=pk)
    if account == request.user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('accounts:account_detail', pk=pk)
    if account.status == User.Status.INACTIVE:
        return redirect('accounts:account_detail', pk=pk)
    return render(request, 'accounts/account_deactivate_confirm.html', {
        'account': account,
    })


@login_required
def account_deactivate(request, pk):
    """FR-005 DEACTIVATE User Account (Administrator / Instructor for students)."""
    if request.method != 'POST':
        messages.error(request, 'Invalid request.')
        return redirect('accounts:account_detail', pk=pk)
    error = _require_account_manager(request.user)
    if error:
        messages.error(request, error)
        return redirect('dashboard')
    account = get_object_or_404(User, pk=pk)
    if account == request.user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('accounts:account_detail', pk=pk)
    reason = (request.POST.get('reason') or '').strip()
    if account.status == User.Status.INACTIVE:
        account.status = User.Status.ACTIVE
        account.save()
        log_activity(request.user, 'Reactivated user account',
                     f"Reactivated {account.get_full_name() or account.username} (ID: {account.pk}).")
        messages.success(request, f"{account.get_full_name() or account.username} has been reactivated.")
    else:
        account.status = User.Status.INACTIVE
        account.save()
        detail = f"Deactivated {account.get_full_name() or account.username} (ID: {account.pk})."
        if reason:
            detail += f" Reason: {reason}"
        log_activity(request.user, 'Deactivated user account', detail)
        messages.success(request,
                         f"{account.get_full_name() or account.username} deactivated. "
                         f"Historical bookings are retained and new bookings are blocked (BR-007).")
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'ok': True,
            'status': account.status,
            'status_display': account.get_status_display(),
            'message': f"{account.get_full_name() or account.username} updated.",
        })
    return redirect('accounts:account_detail', pk=pk)


@login_required
def change_password(request):
    """FR-006 Change Password for Students Account."""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            log_activity(user, 'Changed password',
                         f"Password updated for {user.get_full_name() or user.username} (ID: {user.pk}).")
            messages.success(request, 'Your password has been changed successfully.')
            return redirect('accounts:my_account')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'accounts/change_password.html', {'form': form})


@login_required
def account_change_password(request, pk):
    """System Administrator / Administrator sets a new password for another
    user account (USER_ROLE.md module 1 – Instructor/Trainer: own only)."""
    account = get_object_or_404(User, pk=pk)
    if account == request.user:
        return redirect('accounts:change_password')
    if not is_account_update_manager(request.user):
        messages.error(request, 'You may only change your own password.')
        return redirect('accounts:account_detail', pk=pk)
    form = SetPasswordForm(user=account, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log_activity(request.user, 'Changed user password',
                     f"Set a new password for {account.get_full_name() or account.username} (ID: {account.pk}).")
        messages.success(request,
                         f"Password for {account.get_full_name() or account.username} has been updated.")
        return redirect('accounts:account_detail', pk=account.pk)
    return render(request, 'accounts/change_account_password.html', {
        'form': form,
        'account': account,
    })


