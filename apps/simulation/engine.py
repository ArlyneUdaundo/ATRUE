"""The centralised student-to-student transaction engine (Sections 9 and 19).

Every operational request in every establishment - hotel, airline, travel
agency, tour operator and transportation - travels through this module. Nothing
else is allowed to move a :class:`~simulation.models.SimulationTransaction`
between statuses, which is what makes the guarantees in Section 19 hold in one
place instead of five:

* **Routing (9.2).** A request is routed to whoever holds an ACTIVE assignment
  whose role's ``workflow_stage`` matches the stage the request is waiting at.
  The catalogue supplies the stage, so adding a role to ``role_catalogue`` is
  enough to make it receive work.
* **Isolation (19.4/19.5).** An actor must hold an ACTIVE assignment for *this
  transaction's* establishment inside *this* transaction's session. A student
  assigned to a different hotel, or to the same hotel in a different session,
  cannot see or act on the request.
* **Locking (9.3).** Claiming and transitioning take a row lock, so two
  classmates cannot both process the same request.
* **No self-approval (Scenario 5, rule 6).** The student who raised a request
  can never approve it, even by racing themselves through two roles.
* **Audit and notification (16/17).** Each action writes one immutable
  ``TransactionEvent``, one ``AuditLog`` row and the relevant notifications.

The concrete reservation stays with the module that owns it (``hotels.Booking``
and friends) and is attached through ``SimulationTransaction.subject``; this
module never duplicates reservation data, it only coordinates it.
"""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction as db_transaction
from django.utils import timezone

from audit_logs.services import audit
from establishments.models import Establishment
from notifications.models import Notification
from notifications.services import notify_many

from .models import (
    Role,
    SimulationRoleAssignment,
    SimulationSession,
    SimulationTransaction,
    TransactionEvent,
)

#: Which establishment category each transaction type belongs to. A request is
#: refused when its establishment does not match, so a flight can never be
#: queued against a hotel (Section 19 rule 12).
ESTABLISHMENT_TYPE_FOR_TRANSACTION = {
    SimulationTransaction.Type.HOTEL: 'HOTEL',
    SimulationTransaction.Type.FLIGHT: 'AIRLINE',
    SimulationTransaction.Type.TRAVEL_AGENCY: 'TRAVEL_AGENCY',
    SimulationTransaction.Type.TOUR: 'TOUR_OPERATOR',
    SimulationTransaction.Type.TRANSPORTATION: 'TRANSPORTATION',
}

#: The legal moves. Each entry is ``action -> (allowed from statuses, to status,
#: stage after the move, stage being acted on)``.
#:
#: ``stage after`` of ``None`` means "leave the stage alone". Keeping this as
#: data rather than ``if`` statements in each workflow is what stops a workflow
#: from inventing a transition the others do not have.
TRANSITIONS = {
    'claim': (
        frozenset({SimulationTransaction.Status.PENDING}),
        SimulationTransaction.Status.UNDER_REVIEW,
        None,
        None,
    ),
    'approve': (
        frozenset({SimulationTransaction.Status.UNDER_REVIEW}),
        SimulationTransaction.Status.CONFIRMED,
        None,
        None,
    ),
    'reject': (
        frozenset({SimulationTransaction.Status.PENDING,
                   SimulationTransaction.Status.UNDER_REVIEW}),
        SimulationTransaction.Status.REJECTED,
        SimulationTransaction.Stage.CLOSED,
        None,
    ),
    'cancel': (
        frozenset({SimulationTransaction.Status.PENDING,
                   SimulationTransaction.Status.UNDER_REVIEW,
                   SimulationTransaction.Status.CONFIRMED}),
        SimulationTransaction.Status.CANCELLED,
        SimulationTransaction.Stage.CLOSED,
        None,
    ),
    'forward_to_billing': (
        frozenset({SimulationTransaction.Status.CONFIRMED}),
        SimulationTransaction.Status.CONFIRMED,
        SimulationTransaction.Stage.BILLING,
        SimulationTransaction.Stage.FULFILLMENT,
    ),
    'fulfil': (
        frozenset({SimulationTransaction.Status.CONFIRMED}),
        SimulationTransaction.Status.COMPLETED,
        SimulationTransaction.Stage.DONE,
        SimulationTransaction.Stage.FULFILLMENT,
    ),
    'complete': (
        frozenset({SimulationTransaction.Status.CONFIRMED}),
        SimulationTransaction.Status.COMPLETED,
        SimulationTransaction.Stage.DONE,
        SimulationTransaction.Stage.BILLING,
    ),
}

#: An approval may hand the request straight to fulfilment or to billing; which
#: one is the workflow's decision, but nothing else is allowed.
POST_APPROVAL_STAGES = frozenset({
    SimulationTransaction.Stage.FULFILLMENT,
    SimulationTransaction.Stage.BILLING,
})

CLAIM_REQUIRED_ACTIONS = frozenset(
    {'approve', 'fulfil', 'complete', 'forward_to_billing'})

#: Notification type raised for each action, keyed the same way as TRANSITIONS.
NOTIFICATION_FOR_ACTION = {
    'reject': Notification.Type.GENERAL,
    'cancel': Notification.Type.GENERAL,
}


class TransactionError(Exception):
    """Base class for every refusal the engine makes."""

    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


class SessionNotActiveError(TransactionError):
    def __init__(self, session):
        super().__init__(
            f'"{session.name}" is {session.get_status_display().lower()}. '
            'Only an active simulation session accepts requests.',
            code='session_not_active')


class NotEligibleError(TransactionError):
    """The actor holds no matching ACTIVE assignment for this transaction."""

    def __init__(self, actor, transaction=None, reason=''):
        detail = reason or (
            f'{actor} holds no active assignment for '
            f'{transaction.establishment.name} in this session.' if transaction else
            f'{actor} holds no matching active role assignment.')
        super().__init__(detail, code='not_eligible')


class AlreadyClaimedError(TransactionError):
    def __init__(self, transaction):
        super().__init__(
            f'{transaction.reference} is already being handled by '
            f'{transaction.claimed_by}.', code='already_claimed')


class SelfApprovalError(TransactionError):
    def __init__(self, transaction):
        super().__init__(
            f'{transaction.initiator} raised {transaction.reference} and may not '
            'process or approve it.', code='self_approval')


class IllegalTransitionError(TransactionError):
    def __init__(self, transaction, action):
        super().__init__(
            f'{transaction.reference} cannot be {action.replace("_", " ")} while it '
            f'is {transaction.get_status_display().lower()}.',
            code='illegal_transition')


class StageMismatchError(TransactionError):
    def __init__(self, transaction, action, expected):
        super().__init__(
            f'{transaction.reference} is waiting at '
            f'{transaction.get_stage_display().lower()}, so it cannot be '
            f'{action.replace("_", " ")} yet; that step belongs to the '
            f'{transaction.get_stage_display().lower()} stage.',
            code='stage_mismatch')


class NoHandlerError(TransactionError):
    """Nobody is assigned to handle the request at its current stage."""

    def __init__(self, transaction, stage=None):
        stage = stage or transaction.stage
        super().__init__(
            f'No active assignment can handle {transaction.reference} at the '
            f'{transaction.get_stage_display().lower()} stage.',
            code='no_handler')


# --------------------------------------------------------------------------- #
# Assignment lookup / eligibility
# --------------------------------------------------------------------------- #

def active_assignments_for(user, *, session=None, establishment=None, stage=None,
                           include_oversight=True):
    """The ACTIVE assignments of ``user`` that could handle work.

    Section 19 rule 4 and 5 in one place: an assignment only counts while it is
    ACTIVE, inside the given session, for the given establishment, and its role's
    ``workflow_stage`` is the stage being acted on. Oversight roles (managers,
    instructors) are included because a supervisor is allowed to act anywhere in
    the workflow.
    """
    assignments = SimulationRoleAssignment.objects.filter(
        student=user, status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role_ref__isnull=False,
    ).select_related('role_ref', 'establishment', 'session')

    if session is not None:
        assignments = assignments.filter(session=session)
    if establishment is not None:
        assignments = assignments.filter(establishment=establishment)
    if stage is not None:
        stages = {stage}
        if include_oversight:
            stages.add(Role.WorkflowStage.OVERSIGHT)
        assignments = assignments.filter(role_ref__workflow_stage__in=stages)

    return assignments


def assignment_for(user, *, session, establishment, stage):
    """The single assignment that lets ``user`` act at ``stage``, or None."""
    return active_assignments_for(
        user, session=session, establishment=establishment, stage=stage).first()


def handlers_for(transaction, stage=None, *, exclude=None):
    """Every student who may act on ``transaction`` at ``stage``.

    Used both to build the instructor's queue and to tell the initiator who is
    handling their request.
    """
    stage = stage or transaction.stage
    assignments = SimulationRoleAssignment.objects.filter(
        session=transaction.session,
        establishment=transaction.establishment,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        role_ref__isnull=False,
        role_ref__workflow_stage__in={stage, Role.WorkflowStage.OVERSIGHT},
    ).select_related('student', 'role_ref')

    if exclude is not None:
        assignments = assignments.exclude(student=exclude)

    seen = set()
    handlers = []
    for assignment in assignments.order_by('assigned_at', 'id'):
        # One student can hold several roles at an establishment; they only need
        # telling once.
        if assignment.student_id in seen:
            continue
        seen.add(assignment.student_id)
        handlers.append(assignment)
    return handlers


def visible_transactions(user, *, session=None, include_initiated=True):
    """Transactions ``user`` is allowed to see (Section 19 rule 4/5).

    A student sees what they raised plus whatever their own assignments let them
    handle; an instructor or staff member sees everything in the sessions they
    supervise.
    """
    queryset = SimulationTransaction.objects.select_related(
        'session', 'establishment', 'initiator', 'claimed_by')
    if _supervises(user):
        return queryset if session is None else queryset.filter(session=session)

    assignments = SimulationRoleAssignment.objects.filter(
        student=user,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).values_list('establishment', flat=True).distinct()
    if session is not None:
        assignments = assignments.filter(session=session)

    handled = queryset.filter(establishment__in=assignments)
    if session is not None:
        handled = handled.filter(session=session)
    if include_initiated:
        handled = handled | queryset.filter(initiator=user)
    return handled.distinct()


def _supervises(user):
    """True for staff and for instructors who own at least one session."""
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True
    return SimulationSession.objects.filter(instructor=user).exists()


# --------------------------------------------------------------------------- #
# Submitting
# --------------------------------------------------------------------------- #

def submit_transaction(*, subject, transaction_type, initiator, establishment=None,
                       session=None, service_date=None, service_end_date=None,
                       party_size=1, total_amount=0, remarks='', payload=None):
    """Raise a new student-to-student request and route it to the right queue.

    ``subject`` is the already-created reservation row the request concerns (a
    ``hotels.Booking``, an ``airlines.Booking`` and so on); this function attaches
    it rather than copying it, so the existing booking pages keep working
    unchanged.

    The initiator must hold an ACTIVE assignment in ``session``. A student who
    holds only a customer role (Guest, Passenger, Customer) raises the request;
    an operational student may also raise one on an establishment's behalf. The
    request is never auto-claimed: the initiator may not process their own
    request (Scenario 5), so claiming is always somebody else's decision.
    """
    if subject is None:
        raise TransactionError('A request must concern an existing reservation.',
                               code='no_subject')
    if session is None:
        session = getattr(subject, 'session', None) or _session_for(initiator)
    if session is None:
        raise TransactionError('A request must belong to a simulation session.',
                               code='no_session')
    if session.status != SimulationSession.Status.ACTIVE:
        raise SessionNotActiveError(session)

    establishment = establishment or _establishment_for_subject(subject)
    if establishment is None:
        raise TransactionError(
            'This request does not name an establishment to route it to.',
            code='no_establishment')
    if establishment.status != Establishment.Status.ACTIVE:
        raise TransactionError(
            f'{establishment.name} is not accepting requests right now.',
            code='establishment_inactive')

    expected_type = ESTABLISHMENT_TYPE_FOR_TRANSACTION.get(transaction_type)
    if establishment.type != expected_type:
        raise TransactionError(
            f'{establishment.name} is a {establishment.get_type_display()} and '
            'cannot handle a '
            f'{dict(SimulationTransaction.Type.choices).get(transaction_type, transaction_type)} '
            'request.', code='establishment_type_mismatch')

    assignment = SimulationRoleAssignment.objects.filter(
        student=initiator,
        session=session,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).select_related('role_ref').first()
    if assignment is None:
        raise NotEligibleError(initiator, reason=(
            f'{initiator} holds no active role in "{session.name}", so cannot '
            'raise a request.'))

    with db_transaction.atomic():
        trx = SimulationTransaction.objects.create(
            session=session,
            establishment=establishment,
            transaction_type=transaction_type,
            initiator=initiator,
            initiator_role=assignment.role_ref,
            initiator_assignment=assignment,
            subject_type=ContentType.objects.get_for_model(
                subject.__class__, for_concrete_model=False),
            subject_id=subject.pk,
            status=SimulationTransaction.Status.PENDING,
            stage=SimulationTransaction.Stage.INTAKE,
            service_date=service_date,
            service_end_date=service_end_date,
            party_size=party_size,
            total_amount=total_amount,
            remarks=remarks,
            payload=payload or {},
        )
        _record_event(trx, 'submit', initiator, assignment.role_ref,
                      remarks='Request submitted.')

        # The students who are expected to pick this up are told; the initiator is
        # not, because it is their own request.
        notify_many(
            [handler.student for handler in handlers_for(trx, exclude=initiator)],
            Notification.Type.GENERAL,
            f'{trx.reference} ({trx.subject_label}) is waiting at the '
            f'{trx.get_stage_display().lower()} stage.',
            transaction=trx, title='New request to handle')

        audit('transaction.submit', actor=initiator, transaction=trx,
              role=assignment.role_ref,
              details=f'{transaction_type} request raised.')

    # A guest/passenger raising the request has just performed the one action
    # their role requires: their assignment is automatically completed.
    if assignment.role_ref is not None and (
            assignment.role_ref.operation_category == Role.OperationCategory.CUSTOMER):
        from .completion import complete_guest_booking
        complete_guest_booking(
            initiator, assignment=assignment, session=session,
            booking_reference=getattr(subject, 'booking_reference', '') or '')

    return trx


def _session_for(user):
    """The single active session this user takes part in, if it is unambiguous."""
    sessions = SimulationSession.objects.filter(
        status=SimulationSession.Status.ACTIVE,
        assignments__student=user,
        assignments__status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    ).distinct()
    return sessions.first() if sessions.count() == 1 else None


def _establishment_for_subject(subject):
    """Find the establishment a reservation belongs to."""
    from establishments.models import establishment_for_instance

    found = establishment_for_instance(subject, create=False)
    if found is not None:
        return found
    establishment = getattr(subject, 'establishment', None)
    if establishment is not None:
        return establishment
    return establishment_for_instance(subject, create=True)


# --------------------------------------------------------------------------- #
# Claiming
# --------------------------------------------------------------------------- #

def claim_transaction(transaction, actor, *, remarks=''):
    """Take exclusive responsibility for a request (Section 9.3).

    The row is locked for the duration, so if two students click at the same
    moment exactly one succeeds and the other is told it is already claimed
    rather than silently double-processing it.
    """
    with db_transaction.atomic():
        trx = _lock(transaction)
        _require_open(trx, 'claim')
        _require_session_active(trx)
        _require_actor_not_initiator(trx, actor)

        if trx.is_claimed:
            raise AlreadyClaimedError(trx)

        assignment = assignment_for(actor, session=trx.session,
                                    establishment=trx.establishment, stage=trx.stage)
        if assignment is None:
            raise NotEligibleError(actor, trx, reason=(
                f'{actor} holds no active assignment that can handle requests at '
                f'{trx.establishment.name} in "{trx.session.name}" at this stage.'))

        previous_status, previous_stage = trx.status, trx.stage
        trx.claimed_by = actor
        trx.claimed_by_role = assignment.role_ref
        trx.claimed_at = timezone.now()
        # Taking a request moves a *new* request to "under review", but it must
        # not walk an already-approved one backwards: a billing officer claiming
        # a confirmed request leaves it confirmed.
        if trx.status == SimulationTransaction.Status.PENDING:
            trx.status = SimulationTransaction.Status.UNDER_REVIEW
        trx.save(update_fields=['claimed_by', 'claimed_by_role', 'claimed_at',
                                'status', 'updated_at'])

        _record_event(trx, 'claim', actor, assignment.role_ref,
                      from_status=previous_status, from_stage=previous_stage,
                      remarks=remarks or 'Request claimed.')

    notify_many(
        [trx.initiator],
        Notification.Type.TRANSACTION_CLAIMED,
        f'{trx.reference} is now being handled by {actor}.',
        transaction=trx, title='Your request was claimed')

    audit('transaction.claim', actor=actor, transaction=trx,
          role=assignment.role_ref, remarks=remarks,
          details=f'Claimed at the {trx.get_stage_display().lower()} stage.')

    return trx


def release_claim(transaction, actor, *, remarks=''):
    """Give a claim back so a classmate can pick the request up."""
    with db_transaction.atomic():
        trx = _lock(transaction)
        if not trx.is_claimed:
            return trx
        if trx.claimed_by_id != actor.pk and not _supervises(actor):
            raise NotEligibleError(actor, trx, reason=(
                f'{trx.reference} is claimed by {trx.claimed_by}, so {actor} '
                'cannot release it.'))
        previous = trx.claimed_by
        previous_status = trx.status
        trx.claimed_by = None
        trx.claimed_by_role = None
        trx.claimed_at = None
        # Only walk a new request back to pending; releasing the claim on an
        # approved one must not un-approve it.
        if trx.status == SimulationTransaction.Status.UNDER_REVIEW:
            trx.status = SimulationTransaction.Status.PENDING
        trx.save(update_fields=['claimed_by', 'claimed_by_role', 'claimed_at',
                                'status', 'updated_at'])
        _record_event(trx, 'release', actor, None, from_status=previous_status,
                      from_stage=trx.stage, remarks=remarks or 'Claim released.')

    if previous is not None:
        notify_many(
            [previous],
            Notification.Type.GENERAL,
            f'{trx.reference} was released and is open again.',
            transaction=trx, title='Your claim was released')

    audit('transaction.release', actor=actor, transaction=trx, remarks=remarks,
          details=f'Released the claim held by {previous}.')

    return trx


#: Actions a customer may perform on their own request. Withdrawing your own
#: request is not approving it: nobody gains anything by letting a guest cancel
#: their own reservation, and refusing to do so would leave them stuck. Every
#: action that grants, confirms or closes work stays off this list.
INITIATOR_ACTIONS = frozenset({'cancel'})

# --------------------------------------------------------------------------- #
# Moving a request along
# --------------------------------------------------------------------------- #

def transition(transaction, actor, action, *, stage=None, remarks='', **extra_fields):
    """Move a request through the workflow, enforcing every Section 19 rule.

    ``action`` is one of :data:`TRANSITIONS`. ``stage`` is only meaningful for
    ``approve``, where the workflow chooses between fulfilment and billing.
    """
    if action not in TRANSITIONS:
        raise TransactionError(f'"{action}" is not a workflow action.',
                               code='unknown_action')

    with db_transaction.atomic():
        trx = _lock(transaction)
        from_statuses, to_status, to_stage, acted_stage = TRANSITIONS[action]

        _require_open(trx, action)
        _require_session_active(trx)
        if action not in INITIATOR_ACTIONS:
            _require_actor_not_initiator(trx, actor)

        if trx.status not in from_statuses:
            # An action that needs an unclaimed request to have been taken in hand
            # first should say so, rather than blaming the status: "you have not
            # claimed this yet" is far more use to a student than "cannot approve
            # while pending".
            if (action in CLAIM_REQUIRED_ACTIONS
                    and trx.status == SimulationTransaction.Status.PENDING):
                raise NotEligibleError(actor, trx, reason=(
                    f'{trx.reference} must be claimed before it can be '
                    f'{action.replace("_", " ")}ed.'))
            raise IllegalTransitionError(trx, action)
        if acted_stage is not None and trx.stage != acted_stage:
            raise StageMismatchError(trx, action, acted_stage)

        if action == 'approve':
            to_stage = stage or SimulationTransaction.Stage.FULFILLMENT
            if to_stage not in POST_APPROVAL_STAGES:
                raise TransactionError(
                    f'An approval must hand the request to fulfilment or to '
                    f'billing, not to {to_stage}.', code='bad_stage')

        # Acting at the stage the request is *entering* is what grants authority;
        # ``approve``/``claim`` are authorised by the stage it is leaving.
        authority_stage = acted_stage or trx.stage
        assignment = assignment_for(actor, session=trx.session,
                                    establishment=trx.establishment,
                                    stage=authority_stage)
        withdrawing_own = (action in INITIATOR_ACTIONS
                           and trx.initiator_id == actor.pk)
        if assignment is None and not withdrawing_own:
            raise NotEligibleError(actor, trx, reason=(
                f'{actor} holds no active assignment that can '
                f'{action.replace("_", " ")} {trx.reference} at the '
                f'{dict(SimulationTransaction.Stage.choices).get(authority_stage, authority_stage)} '
                'stage.'))

        # Approving also requires holding the request: a student cannot approve
        # something another student is working on.
        if action in CLAIM_REQUIRED_ACTIONS:
            if trx.claimed_by_id != actor.pk and not _supervises(actor):
                raise NotEligibleError(actor, trx, reason=(
                    f'{trx.reference} must be claimed before it can be '
                    f'{action.replace("_", " ")}ed.'))

        for field, value in extra_fields.items():
            setattr(trx, field, value)

        if to_stage is None:
            to_stage = trx.stage
        if to_status == SimulationTransaction.Status.CONFIRMED and not trx.confirmed_at:
            trx.confirmed_at = timezone.now()

        previous_status, previous_stage = trx.status, trx.stage
        if to_stage is None:
            to_stage = trx.stage

        # A claim belongs to the stage it was taken at. Once the request moves on
        # the previous holder is no longer the right student for it, so the claim
        # is released for whoever handles the new stage - which is also what lets
        # "approve, then forward to billing" work at all.
        if to_stage != previous_stage:
            trx.claimed_by = None
            trx.claimed_by_role = None
            trx.claimed_at = None

        if to_status == SimulationTransaction.Status.COMPLETED:
            trx.completed_at = timezone.now()

        trx.status = to_status
        trx.stage = to_stage
        trx.save()

        _record_event(trx, action, actor,
                       assignment.role_ref if assignment is not None else None,
                       from_status=previous_status, from_stage=previous_stage,
                       remarks=remarks)
        _notify_participants(trx, action, actor, remarks)

    audit(f'transaction.{action}', actor=actor, transaction=trx,
          role=(assignment.role_ref if assignment is not None else None),
          remarks=remarks,
          previous_value=previous_status, new_value=to_status,
          details=(f'Moved to {trx.get_status_display().lower()} at the '
                   f'{trx.get_stage_display().lower()} stage.'))

    # Confirming a request is the reservation officer's/manager's required
    # action; closing it out is the manager's. Either way the acting student's
    # own assignment is completed - never a classmate's.
    if assignment is not None:
        from .completion import (complete_reservation_completion,
                                 complete_reservation_confirmation)
        booking_reference = ''
        try:
            subject = trx.subject
            if subject is not None:
                booking_reference = getattr(subject, 'booking_reference', '') or ''
        except Exception:
            booking_reference = ''
        if (action == 'approve'
                and to_status == SimulationTransaction.Status.CONFIRMED):
            complete_reservation_confirmation(
                actor, assignment=assignment, session=trx.session,
                booking_reference=booking_reference)
        elif (action in ('fulfil', 'complete')
                and to_status == SimulationTransaction.Status.COMPLETED):
            complete_reservation_completion(
                actor, assignment=assignment, session=trx.session,
                booking_reference=booking_reference)

    return trx


def approve(transaction, actor, *, stage=None, remarks='', **extra_fields):
    return transition(transaction, actor, 'approve', stage=stage, remarks=remarks,
                      **extra_fields)


def reject(transaction, actor, *, remarks=''):
    return transition(transaction, actor, 'reject', remarks=remarks)


def cancel(transaction, actor, *, remarks=''):
    return transition(transaction, actor, 'cancel', remarks=remarks)


def forward_to_billing(transaction, actor, *, remarks='', **extra_fields):
    return transition(transaction, actor, 'forward_to_billing', remarks=remarks,
                      **extra_fields)


def fulfil(transaction, actor, *, remarks='', **extra_fields):
    return transition(transaction, actor, 'fulfil', remarks=remarks, **extra_fields)


def complete(transaction, actor, *, remarks='', **extra_fields):
    return transition(transaction, actor, 'complete', remarks=remarks, **extra_fields)


def record_progress(transaction, actor, action, *, remarks=''):
    """Record something that happened during a stage without moving the request.

    Real service has more than one event per stage - a guest checks in and then
    checks out, a vehicle is dispatched and then arrives - and those are not
    status transitions, so they are recorded as events instead of being forced
    into the transition matrix.

    ``action`` names the event (for example ``check_in``). It is deliberately not
    an approval: nobody can self-approve by noting progress, and the request's
    status and stage stay exactly as they were.
    """
    trx = _lock(transaction)
    _require_open(trx, 'record progress on')

    # The same people who may act on the request may note progress on it, plus the
    # customer who raised it, because "the guest has arrived" is their report to
    # make.
    assignment = assignment_for(
        actor, session=trx.session, establishment=trx.establishment,
        stage=trx.stage)
    is_initiator = trx.initiator_id == getattr(actor, 'pk', None)
    if assignment is None and not is_initiator and not _supervises(actor):
        raise NotEligibleError(actor, trx, reason=(
            f'{actor} may not record progress on {trx.reference}.'))

    _record_event(trx, action, actor,
                  assignment.role_ref if assignment is not None else None,
                  from_status=trx.status, from_stage=trx.stage, remarks=remarks)
    audit(f'{trx.transaction_type}.{action}', actor=actor, transaction=trx,
          details=remarks,
          role=(assignment.role if assignment is not None else ''))

    trx.refresh_from_db()
    return trx


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _lock(transaction):
    """Re-read the transaction under a row lock (PostgreSQL ``SELECT ... FOR UPDATE``)."""
    if not getattr(transaction, 'pk', None):
        raise TransactionError('This request has not been saved yet.',
                               code='unsaved')
    return SimulationTransaction.objects.select_for_update().get(pk=transaction.pk)


def _require_open(trx, action='act on'):
    """Refuse to move a request that has reached a final status."""
    if not trx.is_open:
        raise IllegalTransitionError(trx, action)


def _require_session_active(trx):
    if trx.session.status != SimulationSession.Status.ACTIVE:
        raise SessionNotActiveError(trx.session)


def _require_actor_not_initiator(trx, actor):
    # Rule 6 / Scenario 5. The database also refuses to store a claim held by the
    # initiator; checking here means the student gets an explanation instead of a
    # constraint violation.
    if trx.initiator_id == getattr(actor, 'pk', None):
        raise SelfApprovalError(trx)


def _record_event(trx, action, actor, role, *, from_status='', from_stage='',
                  remarks=''):
    """Append one immutable history row describing the move just made."""
    return TransactionEvent.objects.create(
        transaction=trx,
        action=action,
        from_status=from_status or '',
        to_status=trx.status,
        from_stage=from_stage or '',
        to_stage=trx.stage,
        actor=actor,
        role=role,
        establishment=trx.establishment,
        remarks=remarks,
    )


def _notify_participants(trx, action, actor, remarks):
    """Tell the initiator and the next stage's handlers what happened."""
    notification_type = NOTIFICATION_FOR_ACTION.get(action)
    if notification_type is None:
        notification_type = Notification.Type.GENERAL

    subject = trx.subject_label
    message = f'{trx.reference} ({subject}) was {action.replace("_", " ")}ed by {actor}.'
    if remarks:
        message = f'{message} {remarks}'
    message = f'{message} It is now {trx.get_status_display().lower()} at the ' \
              f'{trx.get_stage_display().lower()} stage.'

    recipients = {trx.initiator_id: trx.initiator}
    if trx.stage in {SimulationTransaction.Stage.FULFILLMENT,
                     SimulationTransaction.Stage.BILLING}:
        for handler in handlers_for(trx, exclude=trx.initiator):
            recipients[handler.student_id] = handler.student

    notify_many(
        [user for user in recipients.values() if user is not None],
        notification_type, message, transaction=trx,
        title=f'{trx.reference} updated')