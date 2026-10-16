from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Agency, Booking, Vehicle

User = get_user_model()


class VehicleBookingViewTests(TestCase):
    """The vehicle booking modal content: real vehicle data, server-side
    validation, price calculation and a confirmation that only appears after
    the booking is actually saved."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            'booker', password='pw', account_type=User.AccountType.STUDENT)
        cls.agency = Agency.objects.create(name='Cagayan Transport', contact_number='0917')
        cls.vehicle = Vehicle.objects.create(
            agency=cls.agency, vehicle_name='Hiace Grandia', plate_number='XYZ-100',
            capacity=10, rate_per_km=Decimal('15.00'))
        cls.url = reverse('transportation:book', args=[cls.vehicle.id])

    def setUp(self):
        self.client.force_login(self.student)

    def _schedule(self):
        return (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')

    def _payload(self, **overrides):
        data = {
            'pickup_location': 'Tuguegarao City',
            'drop_off_location': 'Aparri',
            'distance_km': '100',
            'passengers': '2',
            'duration_hours': '4',
            'schedule': self._schedule(),
            'payment_method': 'GCASH',
            'embed': '1',
        }
        data.update(overrides)
        return data

    def test_get_shows_real_vehicle_details_and_rate(self):
        response = self.client.get(self.url, {'schedule': self._schedule()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hiace Grandia')
        self.assertContains(response, 'XYZ-100')
        self.assertContains(response, '15.00')

    def test_valid_booking_is_saved_and_confirmed_in_modal(self):
        response = self.client.post(self.url, self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Booking confirmed')

        booking = Booking.objects.get(vehicle=self.vehicle)
        self.assertEqual(booking.customer, self.student)
        self.assertEqual(booking.distance_km, Decimal('100'))
        self.assertEqual(booking.passengers, 2)
        self.assertEqual(booking.duration_hours, 4)
        # Price follows the existing rule: rate per km x distance.
        self.assertEqual(booking.total_bill, Decimal('1500.00'))

    def test_invalid_distance_is_rejected_and_preserves_entered_data(self):
        response = self.client.post(self.url, self._payload(distance_km='0'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter the travel distance')
        self.assertContains(response, 'value="Tuguegarao City"')
        self.assertFalse(Booking.objects.exists())

    def test_passenger_count_over_capacity_is_rejected(self):
        response = self.client.post(self.url, self._payload(passengers='11'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passenger count must be between 1 and 10')
        self.assertFalse(Booking.objects.exists())

    def test_overlapping_booking_is_rejected(self):
        schedule = timezone.localtime(timezone.now() + timedelta(days=3))
        Booking.objects.create(
            customer=self.student, vehicle=self.vehicle,
            pickup_location='A', drop_off_location='B',
            schedule=schedule, duration_hours=4, passengers=1)
        response = self.client.post(self.url, self._payload(
            schedule=schedule.strftime('%Y-%m-%dT%H:%M')))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already reserved')
        self.assertEqual(Booking.objects.count(), 1)

    def test_unavailable_vehicle_redirects_to_list(self):
        self.vehicle.status = Vehicle.VehicleStatus.MAINTENANCE
        self.vehicle.save(update_fields=['status'])
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('transportation:list'))
