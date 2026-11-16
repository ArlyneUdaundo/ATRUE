import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from activities.models import Activity, ActivityProvider
from activities.models import Booking as ActivityBooking
from airlines.models import Airline, Flight
from airlines.models import Booking as AirlineBooking
from hotels.models import Booking as HotelBooking
from hotels.models import BookingRoom, Hotel, Room
from landmarks.models import Landmark, Ticket
from restaurants.models import Reservation as RestaurantReservation
from restaurants.models import Restaurant, Table
from resorts.models import Reservation as ResortReservation
from resorts.models import Resort, RoomVilla
from staycations.models import Reservation as StaycationReservation
from staycations.models import Staycation
from tour_package.models import Booking as TourPackageBooking
from tour_package.models import TourPackage
from transactions.cancellation import (
    can_request_cancellation,
    process_generic_cancellation,
)
from transactions.models import Bill, Cancellation, Payment
from transportation.models import Agency, Vehicle
from transportation.models import Booking as TransportBooking

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
            customer=self.guest, status=HotelBooking.Status.CONFIRMED)
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

    def test_staff_cannot_open_another_users_request_page(self):
        staff = User.objects.create_user(
            'billing-staff', password='pw', is_staff=True,
            account_type=User.AccountType.STUDENT)
        self.client.force_login(staff)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    def test_ineligible_booking_shows_its_status_instead_of_a_form(self):
        self.booking.status = HotelBooking.Status.CANCELLED
        self.booking.save(update_fields=['status'])
        self.client.force_login(self.guest)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'can no longer be cancelled online')
        self.assertNotContains(response, 'Proof file')

    def test_unpaid_booking_is_cancelled_without_a_refund(self):
        unpaid = HotelBooking.objects.create(
            customer=self.guest, status=HotelBooking.Status.CONFIRMED)
        self.client.force_login(self.guest)
        self.client.post(self._url(unpaid), {
            'reason': 'No longer needed',
            'proof_type': 'ID',
            'proof': SimpleUploadedFile(
                'id.png', b'\x89PNG proof', content_type='image/png'),
        })
        cancellation = Cancellation.objects.get(
            content_type=ContentType.objects.get_for_model(unpaid),
            object_id=unpaid.pk)

        result = process_generic_cancellation(cancellation, self.officer, approve=True)

        unpaid.refresh_from_db()
        self.assertTrue(result['approved'])
        self.assertEqual(result['refunded'], Decimal('0'))
        self.assertEqual(unpaid.status, HotelBooking.Status.CANCELLED)
        self.assertEqual(Payment.objects.count(), 1)

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

@override_settings(
    DEBUG=True, SUPABASE_PRIVATE_STORAGE_CONFIGURED=False,
    MEDIA_ROOT=tempfile.mkdtemp())
class CrossServiceCancellationRequestTests(TestCase):
    """Every supported booking type offers the same proof-backed request flow."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            'cross-owner', password='pw', account_type=User.AccountType.STUDENT)
        cls.other = User.objects.create_user(
            'cross-other', password='pw', account_type=User.AccountType.STUDENT)
        cls.officer = User.objects.create_user(
            'cross-officer', password='pw', account_type=User.AccountType.STUDENT)
        cls.bookings = {}

        hotel = Hotel.objects.create(name='Cross Hotel')
        room = Room.objects.create(hotel=hotel, room_number='C1', rate='1500')
        hotel_booking = HotelBooking.objects.create(
            customer=cls.owner, status=HotelBooking.Status.CONFIRMED)
        BookingRoom.objects.create(
            booking=hotel_booking, room=room,
            check_in=timezone.localdate(),
            check_out=timezone.localdate() + timedelta(days=1))
        cls.bookings['hotels'] = hotel_booking

        resort = Resort.objects.create(name='Cross Resort')
        unit = RoomVilla.objects.create(
            resort=resort, unit_number='R1', rate='2000')
        cls.bookings['resorts'] = ResortReservation.objects.create(
            customer=cls.owner, unit=unit,
            check_in=timezone.localdate(),
            check_out=timezone.localdate() + timedelta(days=2),
            number_of_adults=2, status=ResortReservation.Status.CONFIRMED)

        staycation = Staycation.objects.create(name='Cross Staycation', rate='1800')
        cls.bookings['staycations'] = StaycationReservation.objects.create(
            customer=cls.owner, staycation=staycation,
            check_in=timezone.localdate(),
            check_out=timezone.localdate() + timedelta(days=2),
            number_of_adults=2, status=StaycationReservation.Status.CONFIRMED)

        restaurant = Restaurant.objects.create(name='Cross Restaurant')
        table = Table.objects.create(
            restaurant=restaurant, table_number='T1', capacity=4)
        cls.bookings['restaurants'] = RestaurantReservation.objects.create(
            customer=cls.owner, table=table,
            reservation_datetime=timezone.now() + timedelta(days=2),
            number_of_guests=2, status=RestaurantReservation.Status.CONFIRMED)

        agency = Agency.objects.create(name='Cross Transport')
        vehicle = Vehicle.objects.create(
            agency=agency, vehicle_name='Cross Van', plate_number='CRS-100',
            capacity=10, rate_per_km=Decimal('15.00'))
        cls.bookings['transportation'] = TransportBooking.objects.create(
            customer=cls.owner, vehicle=vehicle,
            pickup_location='A', drop_off_location='B',
            schedule=timezone.now() + timedelta(days=2),
            duration_hours=4, passengers=2,
            status=TransportBooking.Status.CONFIRMED)

        landmark = Landmark.objects.create(
            name='Cross Landmark', category=Landmark.Category.LANDMARK,
            entry_fee=100)
        cls.bookings['landmarks'] = Ticket.objects.create(
            customer=cls.owner,
            destination_type=Ticket.DestinationType.LANDMARK,
            destination=landmark, total_bill=100,
            status=Ticket.Status.CONFIRMED)

        provider = ActivityProvider.objects.create(
            name='Cross Provider', location='Manila')
        activity = Activity.objects.create(
            name='Cross Activity', provider=provider, fee=100)
        cls.bookings['activities'] = ActivityBooking.objects.create(
            customer=cls.owner, activity=activity,
            schedule_date=timezone.localdate(), participant_count=2,
            status=ActivityBooking.Status.CONFIRMED)

        package = TourPackage.objects.create(name='Cross Package', price=100)
        cls.bookings['tour_package'] = TourPackageBooking.objects.create(
            customer=cls.owner, package=package,
            travel_date=timezone.localdate(), number_of_travelers=2,
            status=TourPackageBooking.Status.CONFIRMED)

        airline = Airline.objects.create(name='Cross Air')
        departs = timezone.now() + timedelta(days=7)
        flight = Flight.objects.create(
            airline=airline, origin='Manila', destination='Cebu',
            departure_time=departs, arrival_time=departs + timedelta(hours=2))
        cls.bookings['airlines'] = AirlineBooking.objects.create(
            passenger=cls.owner, flight=flight, total_bill=1000,
            status=AirlineBooking.Status.CONFIRMED)

    def _url(self, booking):
        return reverse('transactions:request_cancellation', args=[
            booking._meta.app_label, booking._meta.model_name, booking.pk])

    def _post_request(self, booking):
        return self.client.post(self._url(booking), {
            'reason': 'Change of plans',
            'proof_type': 'ID',
            'proof': SimpleUploadedFile(
                'id.png', b'\x89PNG proof', content_type='image/png'),
        })

    def test_every_supported_type_offers_its_owner_a_request_page(self):
        expected_details = {
            'hotels': ('Hotel Reservation', 'Cross Hotel', 'C1'),
            'airlines': ('Airline Booking', 'Cross Air', 'Manila to Cebu'),
            'resorts': ('Resort Reservation', 'Cross Resort', 'R1'),
            'staycations': ('Staycation Reservation', 'Cross Staycation'),
            'restaurants': ('Restaurant Reservation', 'Cross Restaurant', 'T1'),
            'transportation': ('Transportation Booking', 'Cross Transport', 'Cross Van'),
            'landmarks': ('Landmark Ticket', 'Cross Landmark'),
            'activities': ('Activity Booking', 'Cross Activity', 'Cross Provider'),
            'tour_package': ('Tour Package Booking', 'Cross Package'),
        }
        self.client.force_login(self.owner)
        for app_label, booking in self.bookings.items():
            with self.subTest(service=app_label):
                self.assertTrue(can_request_cancellation(booking, self.owner))
                self.assertFalse(can_request_cancellation(booking, self.other))
                response = self.client.get(self._url(booking))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Verify ownership')
                for detail in expected_details[app_label]:
                    self.assertContains(response, detail)

    def test_every_supported_type_accepts_a_proof_backed_request(self):
        self.client.force_login(self.owner)
        for app_label, booking in self.bookings.items():
            with self.subTest(service=app_label):
                response = self._post_request(booking)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    response.url,
                    reverse(f'{app_label}:booking_detail', args=[booking.pk]))

                content_type = ContentType.objects.get_for_model(booking)
                cancellation = Cancellation.objects.get(
                    content_type=content_type, object_id=booking.pk)
                self.assertEqual(cancellation.status, Cancellation.Status.REQUESTED)
                self.assertEqual(cancellation.reason, 'Change of plans')
                self.assertEqual(cancellation.proof_type, 'ID')
                booking.refresh_from_db()
                self.assertEqual(booking.status, 'CONFIRMED')

        self.assertEqual(Cancellation.objects.count(), len(self.bookings))

    def test_generic_approval_refunds_each_types_own_payment(self):
        amount = Decimal('250.00')
        for app_label, booking in self.bookings.items():
            if app_label == 'airlines':
                continue
            with self.subTest(service=app_label):
                bill = Bill.objects.create(
                    service=app_label, customer=self.owner,
                    total_amount=amount, amount_paid=amount,
                    balance_due=Decimal('0'), status=Bill.Status.FULLY_PAID)
                bill.link_to_booking(booking)
                bill.save()
                payment = Payment.objects.create(
                    bill=bill, customer=self.owner, amount=amount,
                    method='GCASH', status=Payment.Status.PAID,
                    paid_at=timezone.now())
                payment.link_to_booking(booking)
                payment.save(update_fields=['content_type', 'object_id'])
                cancellation = Cancellation(
                    requested_by=self.owner,
                    status=Cancellation.Status.REQUESTED,
                    reason='Change of plans',
                )
                cancellation.link_to_booking(booking)
                cancellation.save()

                result = process_generic_cancellation(
                    cancellation, self.officer, approve=True)

                cancellation.refresh_from_db()
                booking.refresh_from_db()
                payment.refresh_from_db()
                self.assertTrue(result['approved'])
                self.assertEqual(result['refunded'], amount)
                self.assertEqual(cancellation.status, Cancellation.Status.APPROVED)
                self.assertEqual(cancellation.refund_amount, amount)
                self.assertEqual(booking.status, 'CANCELLED')
                self.assertEqual(payment.status, Payment.Status.REFUNDED)
                self.assertEqual(payment.refunded_amount, amount)

    def test_a_pending_request_blocks_duplicates_for_every_type(self):
        self.client.force_login(self.owner)
        for app_label, booking in self.bookings.items():
            with self.subTest(service=app_label):
                self._post_request(booking)
                response = self._post_request(booking)
                self.assertEqual(response.status_code, 200)

                content_type = ContentType.objects.get_for_model(booking)
                self.assertEqual(Cancellation.objects.filter(
                    content_type=content_type, object_id=booking.pk).count(), 1)

    def test_my_bookings_shows_each_request_and_its_pending_status(self):
        self.client.force_login(self.owner)
        for booking in self.bookings.values():
            self._post_request(booking)

        response = self.client.get(
            reverse('transactions:booking_list') + '?nav=my-bookings')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Refund pending', count=len(self.bookings))
        for booking in self.bookings.values():
            self.assertContains(response, booking.booking_reference)

    def test_airline_request_uses_the_airline_specific_workflow(self):
        from airlines import services

        self.client.force_login(self.owner)
        booking = self.bookings['airlines']
        with mock.patch(
            'airlines.services.request_cancellation_refund',
            wraps=services.request_cancellation_refund,
        ) as request_refund:
            response = self._post_request(booking)

        self.assertEqual(response.status_code, 302)
        request_refund.assert_called_once()
        self.assertEqual(request_refund.call_args.args, (booking, self.owner))

    def test_unpaid_airline_request_is_cancelled_without_a_refund(self):
        from airlines.services import process_cancellation_refund

        self.client.force_login(self.owner)
        booking = self.bookings['airlines']
        self._post_request(booking)
        cancellation = Cancellation.objects.get(
            content_type=ContentType.objects.get_for_model(booking),
            object_id=booking.pk)

        result = process_cancellation_refund(
            cancellation, self.officer, approve=True)

        booking.refresh_from_db()
        self.assertTrue(result['approved'])
        self.assertEqual(result['refunded'], Decimal('0'))
        self.assertEqual(booking.status, AirlineBooking.Status.CANCELLED)

    def test_another_user_cannot_open_any_request_page(self):
        self.client.force_login(self.other)
        for app_label, booking in self.bookings.items():
            with self.subTest(service=app_label):
                response = self.client.get(self._url(booking))
                self.assertEqual(response.status_code, 404)

    def test_billing_officer_refund_queue_shows_type_specific_details(self):
        admin = User.objects.create_superuser(
            'queue-admin', 'queue-admin@example.com', 'pw')
        for booking in self.bookings.values():
            cancellation = Cancellation(
                requested_by=self.owner,
                status=Cancellation.Status.REQUESTED,
                reason='Change of plans',
            )
            cancellation.link_to_booking(booking)
            cancellation.save()

        self.client.force_login(admin)
        response = self.client.get(reverse('transactions:payment_review'))

        self.assertEqual(response.status_code, 200)
        for detail in (
            'Hotel Reservation', 'Cross Hotel', 'C1',
            'Airline Booking', 'Cross Air', 'Manila to Cebu',
            'Resort Reservation', 'Cross Resort',
            'Staycation Reservation', 'Cross Staycation',
            'Restaurant Reservation', 'Cross Restaurant',
            'Transportation Booking', 'Cross Transport',
            'Landmark Ticket', 'Cross Landmark',
            'Activity Booking', 'Cross Activity',
            'Tour Package Booking', 'Cross Package',
        ):
            with self.subTest(detail=detail):
                self.assertContains(response, detail)
