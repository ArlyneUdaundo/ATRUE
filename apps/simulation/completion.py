"""Automatic activity completion.

A simulation role assignment is marked Done automatically the moment the student
has successfully performed the role's required action - and only then. Completion
is triggered from verified backend success, never from a page render or a
half-finished form, and it only ever completes the acting student's own
assignment.

Completion rules, keyed off the role's operation category:

* ``CUSTOMER`` roles (guests / passengers): Done when their booking is
  successfully created and saved.
* ``RESERVATION`` roles (reservation officers): Done when they confirm/process a
  booking to CONFIRMED.
* ``MANAGER`` roles: Done when they confirm a booking, or when they close out
  fulfilment/billing (``fulfil``/``complete`` in the transaction engine).

Every helper is idempotent. Only an ``ACTIVE`` assignment can be completed (the
DB update is guarded by ``status=ACTIVE``), so a refresh or a repeated
submission can never complete the same assignment twice or write two completion
log lines. When the acting student holds several qualifying assignments, the one
to complete is resolved deterministically (see :func:`complete_activity_assignment`);
if the resolution is genuinely ambiguous the action is recorded but nothing is
completed - the student's classroom instructor remains able to mark it by hand.
"""

from atrue_core.services import log_activity

from .models import (Role, SimulationAssignmentTaskCompletion,
                     SimulationRoleAssignment, SimulationSession)

CUSTOMER_CATEGORIES = frozenset({Role.OperationCategory.CUSTOMER})
OFFICER_CATEGORIES = frozenset({
    Role.OperationCategory.RESERVATION,
    Role.OperationCategory.MANAGER,
})


def establishment_for_booking(booking):
    """The simulation ``Establishment`` wrapping ``booking``'s parent, or None.

    Resolves the actual parent entity (hotel, restaurant, resort, ...) so an
    officer's assignment - which is scoped to an establishment - can be matched.
    """
    if booking is None:
        return None
    try:
        entity = _parent_entity(booking)
    except Exception:
        return None
    if entity is None:
        return None
    try:
        from establishments.models import establishment_for_instance
        return establishment_for_instance(entity, create=False)
    except Exception:
        return None


def _parent_entity(booking):
    """The domain object (Hotel, Restaurant, Flight operator, ...) the booking
    belongs to, or None when the booking has no such owner yet."""
    app = booking._meta.app_label
    if app == 'hotels':
        room = booking.room_entries.select_related('room__hotel').first()
        return room.room.hotel if room is not None else None
    if app == 'resorts':
        return booking.unit.resort
    if app == 'staycations':
        return booking.staycation
    if app == 'restaurants':
        return booking.table.restaurant
    if app == 'activities':
        return booking.activity
    if app == 'tour_package':
        return booking.package
    if app == 'landmarks':
        return booking.destination
    if app == 'airlines':
        return booking.flight.airline
    if app == 'transportation':
        return booking.vehicle.agency
    return None


def complete_guest_booking(user, *, assignment=None, session=None,
                           task_assignment_id=None, booking_reference=''):
    """Record the student's saved-booking task for instructor review."""
    assignment = _from_task(assignment, task_assignment_id, user, CUSTOMER_CATEGORIES)
    details = (
        'Guest booking created and saved (%s).' % booking_reference
        if booking_reference else 'Guest booking created and saved.'
    )
    return complete_activity_assignment(
        user, assignment=assignment, session=session,
        categories=CUSTOMER_CATEGORIES,
        action='Completed guest booking', details=details,
        booking_reference=booking_reference,
        task_event='CUSTOMER_BOOKING_SUBMITTED',
    )


def record_hotel_guest_booking(user, booking, *, assignment=None,
                               task_assignment_id=None):
    """Record the three guest actions proven by a saved hotel booking.

    No task is ticked before the booking exists: a selected room and a completed
    guest form are real only once the server has saved the whole booking.
    """
    target = _from_task(assignment, task_assignment_id, user, CUSTOMER_CATEGORIES)
    if target is None:
        establishment = establishment_for_booking(booking)
        if establishment is not None:
            target = _resolve_assignment(
                user, categories=CUSTOMER_CATEGORIES, establishment=establishment)
        if target is None:
            target = _resolve_assignment(user, categories=CUSTOMER_CATEGORIES)
    if target is None:
        return None
    reference = getattr(booking, 'booking_reference', '') or ''
    for task_event in ('HOTEL_ROOM_SELECTED', 'HOTEL_GUEST_INFO_COMPLETED',
                       'CUSTOMER_BOOKING_SUBMITTED'):
        _record_task_event(target, task_event, user, booking_reference=reference)
    return target


def record_guest_payment_verified(booking, *, session=None, actor=None,
                                  task_assignment_id=None):
    """Tick the guest's payment task and the acting Billing Officer's task."""
    completion = _record_booking_event(
        booking, 'PAYMENT_VERIFIED', session=session, actor=actor)
    # The assignment id is recorded when the student enters their task page.
    # Callers that have the request pass it explicitly; when absent, the
    # resolver below still requires one unambiguous active match.
    billing_assignment = _active_assignment(task_assignment_id, actor)
    officer = record_actor_task_event(
        actor, 'PAYMENT_VERIFIED', session=session,
        establishment=establishment_for_booking(booking),
        assignment=billing_assignment,
        booking_reference=_booking_reference(booking),
    ) if actor is not None else None
    return completion or officer


def record_guest_reservation_confirmed(booking, *, session=None, actor=None):
    """Tick the guest's reservation-confirmation task for this booking."""
    return _record_booking_event(
        booking, 'RESERVATION_CONFIRMED', session=session, actor=actor)


def record_booking_fulfilled(booking, *, actor, session=None,
                             task_assignment_id=None):
    """Tick the acting front-desk/manager task once service is delivered.

    The legacy booking pages change ``status`` directly instead of going through
    the transaction engine, so they call this after the successful save. The
    assignment is resolved from the verified task event, not from the page.
    """
    return record_actor_task_event(
        actor, 'BOOKING_FULFILLED', session=session,
        establishment=establishment_for_booking(booking),
        booking_reference=_booking_reference(booking),
        assignment=_active_assignment(task_assignment_id, actor),
    )


#: Backwards-compatible names used by the hotel guest flow and its tests.
record_hotel_guest_payment_verified = record_guest_payment_verified
record_hotel_guest_reservation_confirmed = record_guest_reservation_confirmed


def record_actor_task_event(user, task_event, *, session=None, establishment=None,
                            booking_reference='', assignment=None,
                            task_assignment_id=None):
    """Record ``task_event`` for one unambiguous ACTIVE assignment of ``user``."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    if assignment is None and task_assignment_id:
        assignment = _active_assignment(task_assignment_id, user)
        if assignment is None:
            return None
    if assignment is not None:
        if (assignment.student_id != user.pk
                or assignment.status != SimulationRoleAssignment.AssignmentStatus.ACTIVE
                or (session is not None and assignment.session_id != session.pk)
                or (establishment is not None
                    and assignment.establishment_id != establishment.pk)):
            return None
        if task_event not in _assignment_events(assignment):
            return None
        return _record_task_event(
            assignment, task_event, user, booking_reference=booking_reference)

    qs = SimulationRoleAssignment.objects.filter(
        student=user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).select_related('session', 'establishment', 'role_ref', 'hotel')
    if session is not None:
        qs = qs.filter(session=session)
    else:
        qs = qs.filter(session__status=SimulationSession.Status.ACTIVE)
    if establishment is not None:
        qs = qs.filter(establishment=establishment)
    candidates = [
        candidate for candidate in qs.order_by('assigned_at', 'id')[:20]
        if task_event in _assignment_events(candidate)
    ]
    if len(candidates) != 1:
        return None
    return _record_task_event(
        candidates[0], task_event, user,
        booking_reference=booking_reference)


def _assignment_events(assignment):
    from .task_routing import assignment_tasks_for
    return {
        event
        for task in assignment_tasks_for(assignment)
        for event in task.get('completion_events', ())
    }


def _active_assignment(task_assignment_id, user):
    if not task_assignment_id or user is None:
        return None
    return SimulationRoleAssignment.objects.filter(
        pk=task_assignment_id,
        student=user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).select_related('session', 'establishment', 'role_ref', 'hotel').first()


def _booking_reference(booking):
    return getattr(booking, 'booking_reference', '') or ''


def _booking_customer(booking):
    return (
        getattr(booking, 'customer', None)
        or getattr(booking, 'passenger', None)
        or getattr(booking, 'user', None)
    )


def _record_booking_event(booking, task_event, *, session=None, actor=None):
    target = _guest_assignment_for_booking(booking, session=session)
    if target is None:
        return None
    return _record_task_event(
        target, task_event, actor or target.student,
        booking_reference=_booking_reference(booking))


def _guest_assignment_for_booking(booking, *, session=None):
    """Find the guest assignment whose booking produced this verified action."""
    from .task_routing import GUEST_MODULES, GUEST_ROLE_ALIASES

    guest_roles = set(GUEST_MODULES) | set(GUEST_ROLE_ALIASES) | {'PASSENGER_AIRLINE'}
    reference = _booking_reference(booking)
    if reference:
        completion = (
            SimulationAssignmentTaskCompletion.objects
            .filter(booking_reference=reference, assignment__role__in=guest_roles)
            .select_related('assignment')
            .first())
        if completion is not None:
            return completion.assignment

    customer = _booking_customer(booking)
    if customer is None:
        return None
    assignments = SimulationRoleAssignment.objects.filter(
        student=customer,
        role__in=guest_roles,
        status__in=(SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                    SimulationRoleAssignment.AssignmentStatus.DONE),
    )
    if session is not None:
        assignments = assignments.filter(session=session)
    establishment = establishment_for_booking(booking)
    if establishment is not None:
        scoped = assignments.filter(establishment=establishment)
        if scoped.exists():
            assignments = scoped
    candidates = list(assignments[:2])
    return candidates[0] if len(candidates) == 1 else None


def _record_task_event(target, task_event, user, *, booking_reference=''):
    """Write one verified task completion without changing assignment status."""
    if target is None:
        return None
    from .task_routing import assignment_tasks_for
    task = next((item for item in assignment_tasks_for(target)
                 if task_event in item.get('completion_events', ())), None)
    if task is None:
        return None
    completion, created = SimulationAssignmentTaskCompletion.objects.get_or_create(
        assignment=target, task_key=task['key'],
        defaults={
            'task_label': task['label'],
            'completion_event': task_event,
            'completed_by': user,
            'booking_reference': booking_reference,
        },
    )
    if not created:
        if booking_reference and not completion.booking_reference:
            completion.booking_reference = booking_reference
            completion.save(update_fields=['booking_reference'])
        return None
    place = (target.establishment.name if target.establishment_id
             else target.hotel.name if target.hotel_id else 'n/a')
    log_activity(
        target.student, 'Completed simulation task',
        f"Verified {task['label']} at {place}.",
        session=target.session, establishment=target.establishment,
        role=target.role, role_assignment=target)
    return completion


def complete_reservation_confirmation(user, *, assignment=None, session=None,
                                      establishment=None, booking_reference=''):
    """Record the confirmed-booking task for the assigned role."""
    details = (
        'Booking confirmed (%s).' % booking_reference
        if booking_reference else 'Booking confirmed.'
    )
    return complete_activity_assignment(
        user, assignment=assignment, session=session, establishment=establishment,
        categories=OFFICER_CATEGORIES,
        action='Completed reservation confirmation', details=details,
        booking_reference=booking_reference,
        task_event='BOOKING_CONFIRMED',
    )


def complete_reservation_completion(user, *, assignment=None, session=None,
                                    establishment=None, booking_reference=''):
    """Record the fulfilled-service task for the assigned role."""
    details = (
        'Booking delivered (%s).' % booking_reference
        if booking_reference else 'Booking delivered.'
    )
    return complete_activity_assignment(
        user, assignment=assignment, session=session, establishment=establishment,
        categories=frozenset({
            Role.OperationCategory.MANAGER,
            Role.OperationCategory.FRONT_DESK,
        }),
        action='Completed activity delivery', details=details,
        booking_reference=booking_reference,
        task_event='BOOKING_FULFILLED',
    )


def complete_activity_assignment(user, *, assignment=None, session=None,
                                 establishment=None, categories=None, action='',
                                 details='', booking_reference='', task_event=''):
    """Record the acting student's verified role task, idempotently.

    ``user`` must be authenticated. ``categories`` restricts which operation
    categories may be completed (a CUSTOMER action can never complete a
    reservation officer's assignment, and vice versa).

    Resolution order:
      1. ``assignment`` (explicit - the engine path) that is still ACTIVE.
      2. the still-ACTIVE assignment behind ``task_assignment_id`` (the session
         key set when the student opened the activity's task).
      3. the single matching candidate, when there is exactly one.
      4. when the student's only ACTIVE session would leave one candidate.
      5. otherwise ``None`` - no-op, never a guess.

    Returns the matched active assignment when the event is allowed by its role,
    or ``None`` when there is no safe match. This records task progress only;
    the instructor remains responsible for the assignment's Mark as Done action.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    categories = categories or set(OFFICER_CATEGORIES)
    target = _resolve_assignment(
        user, categories=categories, establishment=establishment,
        session=session, assignment=assignment,
    )
    if target is None:
        return None

    if task_event:
        from .task_routing import assignment_tasks_for
        task = next((item for item in assignment_tasks_for(target)
                     if task_event in item.get('completion_events', ())), None)
        if task is not None:
            completion, created = SimulationAssignmentTaskCompletion.objects.get_or_create(
                assignment=target, task_key=task['key'],
                defaults={
                    'task_label': task['label'],
                    'completion_event': task_event,
                    'completed_by': user,
                    'booking_reference': booking_reference,
                },
            )
            if not created:
                return target
            place = (target.establishment.name if target.establishment_id
                     else target.hotel.name if target.hotel_id else 'n/a')
            log_activity(
                target.student, 'Completed simulation task',
                f"Verified {task['label']} at {place}.",
                session=target.session, establishment=target.establishment,
                role=target.role, role_assignment=target)
            if action:
                log_activity(
                    target.student, action, details=details, session=target.session,
                    establishment=target.establishment, role=target.role,
                    role_assignment=target)
            return target
    return None


def _from_task(assignment, task_assignment_id, user, categories):
    """Resolve the assignment that launched the current task (if still ACTIVE
    and of a matching category), unless an explicit one was given."""
    if assignment is not None or not task_assignment_id:
        return assignment
    return SimulationRoleAssignment.objects.filter(
        pk=task_assignment_id,
        student=user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role_ref__isnull=False,
        role_ref__operation_category__in=categories,
    ).select_related('session', 'establishment').first()


def _resolve_assignment(user, *, categories, establishment=None, session=None,
                        assignment=None):
    """Pick the single assignment this action completes, or None."""
    if assignment is not None:
        try:
            assignment = SimulationRoleAssignment.objects.select_related(
                'session', 'establishment', 'role_ref').get(
                pk=assignment.pk,
                student=user,
                status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                role_ref__isnull=False,
                role_ref__operation_category__in=categories,
            )
            return assignment
        except SimulationRoleAssignment.DoesNotExist:
            # The explicit assignment is not eligible for this action (wrong
            # category, already Done, or another student's) - and that is the
            # end of the resolution. Guessing at a different assignment of the
            # same user's would risk completing work they did not just do.
            return None

    qs = SimulationRoleAssignment.objects.filter(
        student=user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role_ref__isnull=False,
        role_ref__operation_category__in=categories,
    ).select_related('session', 'establishment', 'role_ref')
    if establishment is not None:
        qs = qs.filter(establishment=establishment)
    if session is not None:
        qs = qs.filter(session=session)
    else:
        qs = qs.filter(session__status=SimulationSession.Status.ACTIVE)
    qs = qs.order_by('assigned_at', 'id')

    candidates = list(qs[:2])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) != 2:
        return None

    # Exactly two candidates: keep them only if the student's sole ACTIVE
    # session disambiguates them (otherwise completing one would be a guess).
    sessions = (
        SimulationSession.objects
        .filter(status=SimulationSession.Status.ACTIVE)
        .filter(assignments__student=user,
                assignments__status=SimulationRoleAssignment.AssignmentStatus.ACTIVE)
        .distinct()
    )
    if sessions.count() != 1:
        return None
    narrowed = [a for a in candidates if a.session_id == sessions.first().pk]
    return narrowed[0] if len(narrowed) == 1 else None
