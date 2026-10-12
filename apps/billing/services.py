"""Simulated billing service (Section 15).

The only supported way to create a :class:`~billing.models.SimulatedBill`, record a
:class:`~billing.models.SimulatedPayment` or move a bill between statuses. Every
function here:

* refuses anything that is not a *simulated* payment - there is no gateway, no
  bank and no card network in this code path, and nothing here claims a real
  booking or ticket exists (Section 19 rules 17-18);
* refuses a second payment against a settled bill (Section 15.4);
* writes an append-only :class:`~billing.models.BillingEvent`, an
  :class:`~audit_logs.models.AuditLog` row and the customer's notification, so
  "record every billing status change" holds by construction;
* hands the transaction back to the simulation engine when the bill is settled,
  so the request and its bill can never disagree about whether it is finished.
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction as db_transaction
from django.utils import timezone

from audit_logs.services import audit
from notifications.models import Notification
from notifications.services import notify
from simulation import engine
from simulation.models import SimulationTransaction

from .models import BillingEvent, SimulatedBill, SimulatedPayment

#: A recorded payment is a classroom note, never a receipt from a real system.
SIMULATED_DISCLAIMER = 'Simulated classroom payment - no real funds were transferred.'


class BillingError(Exception):
    """Base class for every refusal the billing service makes."""

    def __init__(self, message, code='invalid'):
        super().__init__(message)
        self.code = code


class BillNotPayableError(BillingError):
    def __init__(self, bill, reason=''):
        super().__init__(
            reason or f'{bill.bill_reference} is {bill.get_status_display().lower()} '
                      'and cannot take a payment.', code='bill_not_payable')


class DuplicatePaymentError(BillingError):
    def __init__(self, bill):
        super().__init__(
            f'{bill.bill_reference} has already been settled in full.',
            code='duplicate_payment')


class InvalidAmountError(BillingError):
    def __init__(self, amount):
        super().__init__(f'"{amount}" is not a valid payment amount.', code='invalid_amount')


def _decimal(value):
    try:
        return Decimal(value).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmountError(value)


def issue_bill(transaction, issued_by, *, items=None, total_amount=None, remarks=''):
    """Raise the bill for an approved, approved-for-billing transaction.

    Exactly one bill may exist per transaction, so calling this twice returns the
    bill that already exists rather than creating a second one the customer could
    be asked to pay twice.
    """
    existing = SimulatedBill.objects.filter(transaction=transaction).first()
    if existing is not None:
        return existing

    if transaction.stage != SimulationTransaction.Stage.BILLING:
        raise BillingError(
            f'{transaction.reference} is not waiting for billing; it is at the '
            f'{transaction.get_stage_display().lower()} stage.',
            code='not_at_billing_stage')

    with db_transaction.atomic():
        locked = SimulationTransaction.objects.select_for_update().get(pk=transaction.pk)
        # Re-check under the lock: two billing officers clicking at once must not
        # both create a bill.
        existing = SimulatedBill.objects.filter(transaction=locked).first()
        if existing is not None:
            return existing

        # Billing the request means working on it, so the officer takes the claim.
        # It was released when the request arrived at this stage, and without it
        # the request could not be completed when the bill is settled.
        if not locked.is_claimed:
            engine.claim_transaction(locked, issued_by,
                                     remarks='Claimed to issue the bill.')

        if items is None and total_amount is None:
            total_amount = locked.total_amount
        bill = SimulatedBill.objects.create(
            transaction=locked,
            establishment=locked.establishment,
            session=locked.session,
            customer=locked.initiator,
            issued_by=issued_by,
            remarks=remarks,
        )
        if items is not None:
            bill.calculate(items)
        else:
            bill.total_amount = _decimal(total_amount)
            bill.refresh_balance()
        bill.save()

        _event(bill, 'issue', actor=issued_by, remarks=remarks)

    notify(
        locked.initiator, Notification.Type.BILLING_READY,
        f'{bill.bill_reference} was issued for {bill.establishment.name}: '
        f'{bill.total_amount} due. {SIMULATED_DISCLAIMER}',
        transaction=locked, title='A bill is waiting for you')

    audit('billing.issue', actor=issued_by, transaction=locked,
          details=f'{bill.bill_reference} for {bill.total_amount}.',
          new_value=bill.total_amount, remarks=remarks)

    return bill


def record_payment(bill, recorded_by, amount, *, method=SimulatedPayment.Method.CASH,
                   status=SimulatedPayment.Status.PAID, remarks=''):
    """Record a simulated payment against ``bill`` and settle it when it clears.

    A partial payment leaves the bill open with a reduced balance; a payment that
    covers the balance marks it paid and completes the underlying transaction.
    """
    amount = _decimal(amount)
    if amount <= 0:
        raise InvalidAmountError(amount)

    with db_transaction.atomic():
        locked = SimulatedBill.objects.select_for_update().select_related(
            'transaction').get(pk=bill.pk)

        if locked.status in SimulatedBill.CLOSED_STATUSES:
            if locked.status == SimulatedBill.Status.PAID:
                raise DuplicatePaymentError(locked)
            raise BillNotPayableError(locked)

        outstanding = locked.balance_due
        if amount > outstanding:
            raise BillingError(
                f'{amount} is more than the {outstanding} still due on '
                f'{locked.bill_reference}.', code='amount_exceeds_balance')

        payment = SimulatedPayment.objects.create(
            bill=locked,
            transaction=locked.transaction,
            amount=amount,
            method=method,
            status=status,
            recorded_by=recorded_by,
            remarks=remarks,
        )
        if status == SimulatedPayment.Status.PAID:
            payment.recorded_at = timezone.now()
            payment.save(update_fields=['recorded_at'])

        previous_status = locked.status
        locked.amount_paid = Decimal(locked.amount_paid) + amount
        locked.refresh_balance()
        settled = locked.balance_due == 0
        if settled:
            locked.status = SimulatedBill.Status.PAID
            locked.settled_at = timezone.now()
        else:
            locked.status = SimulatedBill.Status.PENDING_VERIFICATION
        locked.save(update_fields=['amount_paid', 'balance_due', 'status',
                                   'settled_at', 'updated_at'])

        _event(locked, 'payment', actor=recorded_by, from_status=previous_status,
               to_status=locked.status, amount=amount, remarks=remarks)

    notify(
        locked.customer,
        Notification.Type.PAYMENT_RECORDED if settled else Notification.Type.BILLING_READY,
        (f'{amount} was recorded against {locked.bill_reference}. '
         f'{locked.balance_due} still due. {SIMULATED_DISCLAIMER}') if not settled else
        (f'{locked.bill_reference} is settled in full. {SIMULATED_DISCLAIMER}'),
        transaction=locked.transaction, title='Simulated payment recorded')

    audit('billing.payment', actor=recorded_by, transaction=locked.transaction,
          details=f'{amount} by {method} against {locked.bill_reference}.',
          previous_value=previous_status, new_value=locked.status,
          remarks=remarks)

    if settled:
        _settle_transaction(locked, recorded_by)

    return payment, locked


def reject_bill(bill, actor, *, remarks=''):
    """Refuse a bill (wrong amount, duplicated request, ...)."""
    return _close(bill, actor, SimulatedBill.Status.REJECTED,
                  Notification.Type.PAYMENT_REJECTED, 'billing.reject', remarks)


def cancel_bill(bill, actor, *, remarks=''):
    """Cancel a bill because the underlying request was called off."""
    return _close(bill, actor, SimulatedBill.Status.CANCELLED,
                  Notification.Type.GENERAL, 'billing.cancel', remarks)


def refund_bill(bill, actor, *, remarks=''):
    """Record a simulated refund against a settled bill."""
    return _close(bill, actor, SimulatedBill.Status.REFUNDED,
                  Notification.Type.PAYMENT_REFUNDED, 'billing.refund', remarks)


def _close(bill, actor, status, notification_type, action, remarks):
    with db_transaction.atomic():
        locked = SimulatedBill.objects.select_for_update().get(pk=bill.pk)
        if locked.status == status:
            return locked
        if locked.status in SimulatedBill.CLOSED_STATUSES and status != SimulatedBill.Status.REFUNDED:
            raise BillNotPayableError(locked)

        previous_status = locked.status
        locked.status = status
        locked.save(update_fields=['status', 'updated_at'])
        _event(locked, action, actor=actor, from_status=previous_status,
               to_status=status, remarks=remarks)

    notify(
        locked.customer, notification_type,
        f'{locked.bill_reference} is now {locked.get_status_display().lower()}.'
        + (f' {remarks}' if remarks else ''),
        transaction=locked.transaction, title='Bill updated')

    audit(action, actor=actor, transaction=locked.transaction,
          previous_value=previous_status, new_value=status, remarks=remarks)

    return locked


def _settle_transaction(bill, actor):
    """Complete the simulation request once its bill is settled in full."""
    from simulation import workflows

    transaction = bill.transaction
    if transaction.status == SimulationTransaction.Status.COMPLETED:
        return transaction
    try:
        settled = engine.complete(transaction, actor, remarks=(
            f'Settled by simulated bill {bill.bill_reference}.'))
    except engine.TransactionError as error:
        # The bill is settled either way, so this is recorded rather than raised:
        # a supervisor may have closed the request already, or the claim may have
        # moved to another student. Either way the instructor can see why the
        # request and its bill disagree instead of finding out by accident.
        audit('billing.settle_pending', actor=actor, transaction=transaction,
              details=(f'{bill.bill_reference} is settled but '
                       f'{transaction.reference} could not be completed: {error}'),
              remarks=str(error))
        return transaction

    # The booking rows predate the simulation and other pages still read them, so
    # they are brought in step here rather than left showing "confirmed" for a
    # request that has been settled and closed.
    workflows.sync_booking_status(settled)
    return settled


def _event(bill, action, *, actor, from_status='', to_status='', amount=0, remarks=''):
    return BillingEvent.objects.create(
        bill=bill, transaction=bill.transaction, action=action,
        from_status=from_status, to_status=to_status or bill.status,
        actor=actor, amount=amount or 0, remarks=remarks)


def bill_for(transaction, *, create=False, issued_by=None, items=None, total_amount=None,
             remarks=''):
    """The bill for ``transaction``, optionally raising it."""
    bill = SimulatedBill.objects.filter(transaction=transaction).first()
    if bill is not None or not create:
        return bill
    if issued_by is None:
        raise BillingError('Issuing a bill needs the officer issuing it.',
                           code='no_issuer')
    return issue_bill(transaction, issued_by, items=items,
                      total_amount=total_amount, remarks=remarks)