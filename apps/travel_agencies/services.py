"""Travel agency workflow (Section 12).

The shape every establishment follows, expressed once here and then mirrored for
hotel, airline, tour operator and transportation:

    customer request -> consultant quotes -> customer accepts -> simulated billing

Only the *steps* differ between establishments; the routing, claiming, isolation,
self-approval and audit rules all come from :mod:`simulation.engine`, so a change
to those rules cannot be made in one workflow and forgotten in another.

Nothing in this module reserves a real flight, hotel or seat, and no quotation is
a real offer - they are classroom artefacts (Section 19 rules 17-18).
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction as db_transaction
from django.db.models import Max

from audit_logs.services import audit
from notifications.models import Notification
from notifications.services import notify
from simulation import engine
from simulation.models import SimulationTransaction

from .models import TravelAgencyRequest, TravelItinerary, TravelQuotation


class WorkflowError(Exception):
    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


def _money(value):
    try:
        return Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def submit_request(*, customer, establishment, destination, travel_date=None,
                   return_date=None, party_size=1, budget=0, origin='', requirements=''):
    """A customer raises a travel request and it is routed to a consultant."""
    request = TravelAgencyRequest.objects.create(
        customer=customer, establishment=establishment, destination=destination,
        origin=origin, travel_date=travel_date, return_date=return_date,
        party_size=party_size, budget=_money(budget), requirements=requirements,
    )
    request.full_clean(exclude=['decision'])

    trx = engine.submit_transaction(
        subject=request,
        transaction_type=SimulationTransaction.Type.TRAVEL_AGENCY,
        initiator=customer,
        establishment=establishment,
        session=_active_session(customer),
        service_date=travel_date,
        service_end_date=return_date,
        party_size=party_size,
        total_amount=_money(budget),
        remarks=requirements,
    )

    notify(customer, Notification.Type.GENERAL,
           f'Your request to {establishment.name} for {destination} was received '
           f'and is now with a travel consultant. Reference {request.request_reference}.',
           transaction=trx, title='Travel request received')

    audit('travel.request_submitted', actor=customer, transaction=trx,
          details=f'{request.request_reference} for {destination}, '
                  f'{party_size} traveller(s).',
          new_value=request.request_reference, remarks=requirements)

    return request, trx


def prepare_quotation(trx, consultant, *, items, discount=0, valid_until=None,
                      terms='', itinerary_days=None):
    """The consultant prices a request and sends the customer a quotation.

    The consultant must be working on the request (they hold the claim), which is
    what stops two students quoting the same customer at once. Re-quoting bumps
    the version and supersedes the previous quotation rather than overwriting it,
    so "every quotation change is recorded" holds.
    """
    # Re-read under the caller's own object: the row in the database is what says
    # who holds the claim, and re-quoting by the consultant who already holds it
    # is legitimate.
    trx = SimulationTransaction.objects.get(pk=trx.pk)
    if not trx.is_claimed:
        trx = engine.claim_transaction(trx, consultant,
                                       remarks='Claimed to prepare a quotation.')

    request = trx.subject
    if request is None:
        raise WorkflowError('This request has no travel request attached.',
                            code='no_subject')

    with db_transaction.atomic():
        latest_version = TravelQuotation.objects.filter(
            request=request).aggregate(Max('version'))['version__max'] or 0

        TravelQuotation.objects.filter(
            request=request,
            status=TravelQuotation.Status.SENT,
        ).update(status=TravelQuotation.Status.SUPERSEDED)

        quotation = TravelQuotation.objects.create(
            request=request,
            version=latest_version + 1,
            prepared_by=consultant,
            valid_until=valid_until,
            terms=terms,
        )
        quotation.calculate(items)
        quotation.discount = _money(discount)
        quotation.total = max(Decimal(0), quotation.subtotal - quotation.discount)
        quotation.status = TravelQuotation.Status.SENT
        quotation.save()

        for day in itinerary_days or []:
            TravelItinerary.objects.create(
                request=request, version=quotation.version,
                created_by=consultant,
                title=day.get('title', ''),
                day_number=day.get('day_number', 1),
                activity=day.get('activity', ''),
                destination=day.get('destination', ''),
                notes=day.get('notes', ''),
            )

    trx.total_amount = quotation.total
    trx.payload = {
        'quotation_reference': quotation.quotation_reference,
        'quotation_version': quotation.version,
        'quotation_total': str(quotation.total),
    }
    trx.save(update_fields=['total_amount', 'payload', 'updated_at'])

    notify(request.customer, Notification.Type.TRAVEL_QUOTATION_READY,
           f'{quotation.quotation_reference} for {request.destination} totals '
           f'{quotation.total}. This is a simulated quotation.',
           transaction=trx, title='Your quotation is ready')

    audit('travel.quotation_sent', actor=consultant, transaction=trx,
          details=f'{quotation.quotation_reference} v{quotation.version} '
                  f'for {quotation.total}.',
          new_value=quotation.total)

    return quotation


def accept_quotation(trx, customer):
    """The customer accepts, which sends the request to simulated billing."""
    request = trx.subject
    quotation = request.current_quotation
    if quotation is None:
        raise WorkflowError('There is no quotation to accept.', code='no_quotation')

    if request.customer_id != customer.pk:
        raise WorkflowError('Only the customer who raised the request may accept it.',
                            code='not_the_customer')

    with db_transaction.atomic():
        quotation.accept(customer)
        request.decision = TravelAgencyRequest.Decision.ACCEPTED
        request.save(update_fields=['decision'])

    notify(quotation.prepared_by, Notification.Type.TRAVEL_REQUEST_ACCEPTED,
           f'{customer} accepted {quotation.quotation_reference}.',
           transaction=trx, title='Your quotation was accepted')

    audit('travel.quotation_accepted', actor=customer, transaction=trx,
          details=f'{quotation.quotation_reference} accepted.', role='PASSENGER_AIRLINE')

    return engine.approve(trx, quotation.prepared_by,
                          stage=SimulationTransaction.Stage.BILLING,
                          remarks='Quotation accepted; awaiting simulated payment.')


def decline_quotation(trx, customer, *, remarks=''):
    """The customer turns the quotation down, which closes the request."""
    request = trx.subject
    quotation = request.current_quotation
    if quotation is None:
        raise WorkflowError('There is no quotation to decline.', code='no_quotation')
    if request.customer_id != customer.pk:
        raise WorkflowError('Only the customer who raised the request may decline it.',
                            code='not_the_customer')

    with db_transaction.atomic():
        quotation.decline(customer)
        request.decision = TravelAgencyRequest.Decision.DECLINED
        request.save(update_fields=['decision'])

    notify(quotation.prepared_by, Notification.Type.TRAVEL_REQUEST_DECLINED,
           f'{customer} declined {quotation.quotation_reference}.',
           transaction=trx, title='Your quotation was declined')

    audit('travel.quotation_declined', actor=customer, transaction=trx,
          details=f'{quotation.quotation_reference} declined.', remarks=remarks)

    return engine.reject(trx, quotation.prepared_by,
                         remarks=remarks or 'The customer declined the quotation.')


def _active_session(customer):
    from simulation.models import SimulationSession

    sessions = SimulationSession.objects.filter(
        status=SimulationSession.Status.ACTIVE,
        assignments__student=customer,
        assignments__status='ACTIVE',
    ).distinct()
    return sessions.first() if sessions.count() == 1 else None