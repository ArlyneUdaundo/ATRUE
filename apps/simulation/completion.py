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

from django.utils import timezone

from atrue_core.services import log_activity

from .models import Role, SimulationRoleAssignment, SimulationSession

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
    """Mark the student's CUSTOMER role Done, after a booking was saved."""
    assignment = _from_task(assignment, task_assignment_id, user, CUSTOMER_CATEGORIES)
    details = (
        'Guest booking created and saved (%s).' % booking_reference
        if booking_reference else 'Guest booking created and saved.'
    )
    return complete_activity_assignment(
        user, assignment=assignment, session=session,
        categories=CUSTOMER_CATEGORIES,
        action='Completed guest booking', details=details,
    )


def complete_reservation_confirmation(user, *, assignment=None, session=None,
                                      establishment=None, booking_reference=''):
    """Mark the student's RESERVATION/MANAGER role Done, after a booking was
    confirmed/processed to CONFIRMED."""
    details = (
        'Booking confirmed (%s).' % booking_reference
        if booking_reference else 'Booking confirmed.'
    )
    return complete_activity_assignment(
        user, assignment=assignment, session=session, establishment=establishment,
        categories=OFFICER_CATEGORIES,
        action='Completed reservation confirmation', details=details,
    )


def complete_reservation_completion(user, *, assignment=None, session=None,
                                    establishment=None, booking_reference=''):
    """Mark the student's MANAGER role Done, after fulfilment/delivery was
    closed out (``fulfil``/``complete``)."""
    details = (
        'Booking delivered (%s).' % booking_reference
        if booking_reference else 'Booking delivered.'
    )
    return complete_activity_assignment(
        user, assignment=assignment, session=session, establishment=establishment,
        categories=frozenset({Role.OperationCategory.MANAGER}),
        action='Completed activity delivery', details=details,
    )


def complete_activity_assignment(user, *, assignment=None, session=None,
                                 establishment=None, categories=None, action='',
                                 details=''):
    """Complete the acting student's qualifying assignment, idempotently.

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

    Returns the completed ``SimulationRoleAssignment`` the first time, ``None``
    when there was nothing to complete (already Done, no candidate, or
    ambiguous). A completion is written to the activity log exactly once.
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

    now = timezone.now()
    completed = SimulationRoleAssignment.objects.filter(
        pk=target.pk,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).update(
        status=SimulationRoleAssignment.AssignmentStatus.DONE,
        completed_at=now,
    )
    if not completed:
        # Already Done (or deactivated) under the current lock - leave the
        # single completion event already written and do nothing more.
        return None

    log_activity(
        target.student,
        action or 'Activity completed',
        details=details,
        session=target.session,
        establishment=target.establishment,
        role=target.role,
    )
    target.refresh_from_db()
    return target


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