"""Deletion helpers for establishments and their directly linked history."""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction


@transaction.atomic
def delete_booking_history(bookings, *, include_hotel_payments=False):
    """Delete financial/order records linked to these bookings, then bookings."""
    booking_ids = list(bookings.values_list('pk', flat=True))
    if not booking_ids:
        return

    from transactions.models import (
        AdditionalTransaction, Bill, Cancellation, Payment, Receipt,
        TravelOrderItem,
    )
    from simulation.models import SimulationTransaction

    content_type = ContentType.objects.get_for_model(bookings.model)
    linked = {'content_type': content_type, 'object_id__in': booking_ids}
    bills = Bill.objects.filter(**linked)
    bill_ids = list(bills.values_list('pk', flat=True))
    payments = Payment.objects.filter(**linked)
    if bill_ids:
        payments = payments | Payment.objects.filter(bill_id__in=bill_ids)
    payment_ids = list(payments.values_list('pk', flat=True).distinct())

    TravelOrderItem.objects.filter(**linked).delete()
    Cancellation.objects.filter(**linked).delete()
    AdditionalTransaction.objects.filter(**linked).delete()
    Receipt.objects.filter(payment_id__in=payment_ids).delete()
    if bill_ids:
        Receipt.objects.filter(bill_id__in=bill_ids).delete()
    payments.delete()
    bills.delete()
    SimulationTransaction.objects.filter(
        subject_type=content_type, subject_id__in=booking_ids
    ).delete()

    if include_hotel_payments:
        from hotels.models import Payment as HotelPayment
        HotelPayment.objects.filter(booking_id__in=booking_ids).delete()

    bookings.delete()


@transaction.atomic
def delete_linked_establishment_history(entity):
    """Remove simulation transactions that protect a catalogue establishment."""
    from establishments.models import establishment_for_instance
    from simulation.models import SimulationTransaction

    establishment = establishment_for_instance(entity, create=False)
    if establishment is None:
        return
    SimulationTransaction.objects.filter(establishment=establishment).delete()
    establishment.delete()
