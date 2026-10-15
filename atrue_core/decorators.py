from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from accounts.roles import (
    MANAGEMENT_ACCOUNT_TYPES,
    can_access_module_route,
    is_airline_booking_restricted,
)
from accounts.views import is_admin_user


def student_booking_required(view_func):
    """Only non-admin (student/customer) accounts may book services (BR-001, BR-002)."""
    @wraps(view_func)
    def wrap(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            messages.error(request, 'Please sign in as a student to book services.')
            return redirect('accounts:login')
        if is_admin_user(user):
            resolver = getattr(request, 'resolver_match', None)
            task_guest_booking = False
            if (
                not user.is_staff
                and user.account_type not in MANAGEMENT_ACCOUNT_TYPES
            ):
                namespace = getattr(resolver, 'namespace', None)
                url_name = getattr(resolver, 'url_name', None)
                role_by_booking_route = {
                    ('airlines', 'book'): 'PASSENGER_AIRLINE',
                    ('airlines', 'book_itinerary'): 'PASSENGER_AIRLINE',
                    ('activities', 'book_activity'): 'ACTIVITY_GUEST',
                    ('activities', 'flow_select'): 'ACTIVITY_GUEST',
                }
                task_role = role_by_booking_route.get((namespace, url_name))
                if task_role:
                    from simulation.models import SimulationRoleAssignment

                    task_guest_booking = SimulationRoleAssignment.objects.filter(
                        pk=request.session.get('active_simulation_task_assignment'),
                        student=user,
                        role=task_role,
                        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                    ).exists()
            if not task_guest_booking:
                messages.warning(
                    request,
                    'Booking is available to student and assigned guest accounts. Admins and instructors manage the platform.')
                return redirect('dashboard')
        if not user.is_bookable:
            messages.warning(request, 'Your account is deactivated. Contact the administrator.')
            return redirect('dashboard')
        resolver = getattr(request, 'resolver_match', None)
        if (
            is_airline_booking_restricted(user)
            and getattr(resolver, 'namespace', None) == 'airlines'
            and getattr(resolver, 'url_name', None) in {'book', 'book_itinerary'}
        ):
            messages.warning(request, 'This account is limited to airline ticketing operations.')
            return redirect('airlines:list')
        return view_func(request, *args, **kwargs)
    return wrap


def manager_required(view_func):
    """Restrict a management view to users whose role owns its module.

    Each management account type may only open the admin functions of the
    modules assigned to it (see ``accounts.roles.MANAGEMENT_MODULE_ACCESS``);
    System Administrator / Administrator / Instructor and Django staff keep
    unrestricted access.
    """
    @wraps(view_func)
    def wrap(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            messages.error(request, 'Please sign in.')
            return redirect('accounts:login')
        resolver = getattr(request, 'resolver_match', None)
        module = getattr(resolver, 'namespace', None) or ''
        task_assignment_id = request.session.get(
            'active_simulation_task_assignment')
        if task_assignment_id is not None:
            from simulation.models import SimulationRoleAssignment
            from simulation.task_routing import task_operation_for

            assignment = (
                SimulationRoleAssignment.objects
                .filter(
                    pk=task_assignment_id,
                    student=user,
                    status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                )
                .select_related('role_ref', 'establishment', 'hotel')
                .first()
            )
            if assignment is None:
                request.session.pop('active_simulation_task_assignment', None)
            else:
                operation = task_operation_for(assignment)
                route_name = getattr(resolver, 'url_name', None)
                if (operation is None
                        or f'{module}:{route_name}' not in operation['allowed_routes']):
                    raise PermissionDenied(
                        'This operations page is not allowed for your active assignment.')
                request.active_simulation_assignment = assignment
                return view_func(request, *args, **kwargs)

        route_name = getattr(resolver, 'url_name', None)
        if not can_access_module_route(user, module, route_name):
            messages.warning(request, 'You are not authorised to manage this module.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrap


def role_required(*roles):
    """Restrict a view to users assigned any of the given simulation roles (BR-084)."""
    def decorator(view_func):
        @wraps(view_func)
        def wrap(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                messages.error(request, 'Please sign in.')
                return redirect('accounts:login')
            if is_admin_user(user):
                return view_func(request, *args, **kwargs)
            assigned = set(user.simulation_roles.values_list('role', flat=True))
            if roles and not assigned.intersection(roles):
                messages.warning(request, 'Your assigned role does not allow this action.')
                return redirect('dashboard')
            return view_func(request, *args, **kwargs)
        return wrap
    return decorator
