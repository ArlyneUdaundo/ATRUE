import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from hotels.models import Booking as HotelBooking
from hotels.models import BookingRoom, Hotel, Room
from transactions.cancellation import process_generic_cancellation
from transactions.models import Bill, Cancellation, Payment

User = get_user_model()


@override_settings(
    DEBUG=True, SUPABASE_PRIVATE_STORAGE_CONFIGURED=False,
    MEDIA_ROOT=tempfile.mkdtemp())
class GenericCancellationRequestTests(TestCase):

    def setUp(self):
        self.guest = User.objects.create_user(
            'guest-owner', password='pw', account_type=User.AccountType.STUDENT)
        self.other = User.objects.create_user(
            'guest-other', password='pw', account_type=User.AccountType.STUDENT)
        self.officer = User.objects.create_user(
            'billing-officer', password='pw', account_type=User.AccountType.STUDENT)
        self.hotel = Hotel.objects.create(name='Cancellation Inn')
        self.room = Room.objects.create(
            hotel=self.hotel, room_number='101', rate='1500.00')
        self.booking = HotelBooking.objects.create(
            customer=self.guest, status=HotelBooking.Status.CONFIRMED,
            total_bill=Decimal('1500.00'), amount_paid=Decimal('1500.00'),
            balance_due=Decimal('0.00'))
        BookingRoom.objects.create(
            booking=self.booking, room=self.room,
            check_in=timezone.localdate(),
            check_out=timezone.localdate() + timedelta(days=1))
        self.bill = Bill.objects.create(
            service='hotels', customer=self.guest, total_amount=Decimal('1500.00'),
            amount_paid=Decimal('1500.00'), balance_due=Decimal('0.00'),
            status=Bill.Status.FULLY_PAID)
        self.bill.link_to_booking(self.booking)
        self.bill.save()
        self.payment = Payment.objects.create(
            bill=self.bill, customer=self.guest, amount=Decimal('1500.00'),
            method='GCASH', status=Payment.Status.PAID, paid_at=timezone.now())

    def _url(self, booking=None):
        booking = booking or self.booking
        return reverse('transactions:request_cancellation', args=[
            booking._meta.app_label, booking._meta.model_name, booking.pk])

    def test_owner_sees_the_proof_upload_form(self):
        self.client.force_login(self.guest)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verify ownership')
        self.assertContains(response, 'Proof file')

    def test_another_user_cannot_open_the_request_page(self):
        self.client.force_login(self.other)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    def test_request_requires_proof(self):
        self.client.force_login(self.guest)
        response = self.client.post(self._url(), {
            'reason': 'Change of plans', 'proof_type': 'ID'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Cancellation.objects.exists())

    def test_owner_submits_a_request_with_proof(self):
        self.client.force_login(self.guest)
        response = self.client.post(self._url(), {
            'reason': 'Change of plans',
            'proof_type': 'ETICKET',
            'proof': SimpleUploadedFile(
                'ticket.pdf', b'%PDF-1.4 proof', content_type='application/pdf'),
        })
        self.assertRedirects(
            response, reverse('hotels:booking_detail', args=[self.booking.pk]))

        cancellation = Cancellation.objects.get(object_id=self.booking.pk)
        self.assertEqual(cancellation.status, Cancellation.Status.REQUESTED)
        self.assertEqual(cancellation.proof_type, 'ETICKET')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, HotelBooking.Status.CONFIRMED)

    def test_approval_cancels_the_booking_and_refunds_the_payment(self):
        self.client.force_login(self.guest)
        self.client.post(self._url(), {
            'reason': 'Change of plans',
            'proof_type': 'ID',
            'proof': SimpleUploadedFile(
                'id.png', b'\x89PNG proof', content_type='image/png'),
        })
        cancellation = Cancellation.objects.get(object_id=self.booking.pk)

        result = process_generic_cancellation(
            cancellation, self.officer, approve=True, remarks='Verified.')

        cancellation.refresh_from_db()
        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertTrue(result['approved'])
        self.assertEqual(result['refunded'], Decimal('1500.00'))
        self.assertEqual(cancellation.status, Cancellation.Status.APPROVED)
        self.assertEqual(self.booking.status, HotelBooking.Status.CANCELLED)
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.room.status, Room.RoomStatus.AVAILABLE)
