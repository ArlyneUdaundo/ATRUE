from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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


class SharedTransportBookingFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            'shared-transport-booker', password='pw',
            account_type=User.AccountType.STUDENT,
            first_name='Taylor', last_name='Rider', contact_number='09171234567',
        )
        cls.agency = Agency.objects.create(name='Shared Flow Transport')
        cls.vehicle = Vehicle.objects.create(
            agency=cls.agency, vehicle_name='Route Van', plate_number='FLOW-101',
            capacity=10, rate_per_km=Decimal('15.00'),
        )

    def setUp(self):
        self.client.force_login(self.student)
        self.url = reverse('transportation:flow_select', args=[self.agency.pk])
        self.schedule = timezone.localdate() + timedelta(days=2)

    def _payload(self, **overrides):
        data = {
            'check_in': self.schedule.isoformat(),
            'time': '10:00',
            'item_ids': [str(self.vehicle.pk)],
            'item_0_first_name': 'Taylor',
            'item_0_last_name': 'Rider',
            'item_0_contact': '09171234567',
            'item_0_adults': '2',
            'item_0_children': '1',
            'pickup_location': 'Tuguegarao City',
            'drop_off_location': 'Aparri',
            'distance_km': '100',
            'duration_hours': '4',
            'driver_id': '',
        }
        data.update(overrides)
        return data

    def test_agency_flow_uses_shared_selection_and_trip_details_screen(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'establishments/select.html')
        self.assertContains(response, 'Route Van')
        self.assertContains(response, 'Pickup location')
        self.assertContains(response, 'id="searchCheckIn"')
        self.assertContains(response, 'id="searchTime"')
        self.assertNotContains(response, 'class="ag-search establishment-search')
        self.assertContains(response, 'Distance (km)')
        self.assertContains(response, 'Pickup time')

    def test_old_agency_vehicle_url_redirects_into_booking_flow(self):
        agency_url = reverse('transportation:agency_vehicles', args=[self.agency.pk])
        schedule = timezone.localtime(timezone.now() + timedelta(days=2))

        response = self.client.get(agency_url, {'schedule': schedule.isoformat()})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            f'{self.url}?check_in={schedule:%Y-%m-%d}&time={schedule:%H:%M}',
        )

    def test_agency_list_links_directly_to_shared_booking_flow(self):
        response = self.client.get(reverse('transportation:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{self.url}?check_in=')
        self.assertNotContains(response, f'href="{reverse("transportation:agency_vehicles", args=[self.agency.pk])}')

    def test_vehicle_photo_is_shown_in_shared_booking_flow(self):
        self.vehicle.image = 'transport_vehicles/route-van.jpg'
        self.vehicle.save(update_fields=['image'])
        self.vehicle.refresh_from_db()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['cards'][0]['photos'],
            [{'url': self.vehicle.image.url}],
        )

    @override_settings(STORAGES={
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    })
    def test_booking_creates_transport_record_order_and_bill_then_continues_to_payment(self):
        from transactions.models import TravelOrder, TravelOrderItem
        from atrue_core.services import bill_for_booking

        response = self.client.post(self.url, self._payload())

        booking = Booking.objects.get(vehicle=self.vehicle)
        self.assertRedirects(
            response, reverse('transactions:bill_detail', args=[bill_for_booking(booking).pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(booking.pickup_location, 'Tuguegarao City')
        self.assertEqual(booking.drop_off_location, 'Aparri')
        self.assertEqual(booking.distance_km, Decimal('100.00'))
        self.assertEqual(booking.passengers, 3)
        self.assertEqual(booking.duration_hours, 4)
        self.assertEqual(booking.total_bill, Decimal('1500.00'))
        order = TravelOrder.objects.get(customer=self.student)
        self.assertEqual(order.bill, bill_for_booking(booking))
        self.assertTrue(TravelOrderItem.objects.filter(
            order=order, object_id=booking.pk, service='transport',
        ).exists())
        payment_page = self.client.get(response.url)
        self.assertEqual(payment_page.status_code, 200)
        self.assertEqual(
            payment_page.context['payment_summary']['quantity_label'], 'Passengers')
        self.assertIn(
            'Tuguegarao City → Aparri',
            payment_page.context['payment_summary']['details'])

    def test_shared_flow_rejects_an_overlapping_vehicle_booking(self):
        schedule = timezone.make_aware(datetime.combine(
            self.schedule, datetime.min.time().replace(hour=10),
        ))
        Booking.objects.create(
            customer=self.student, vehicle=self.vehicle,
            pickup_location='A', drop_off_location='B',
            schedule=schedule, duration_hours=4, passengers=1,
        )

        response = self.client.post(self.url, self._payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already reserved for the selected schedule')
        self.assertEqual(Booking.objects.count(), 1)

    def test_shared_flow_rejects_a_malformed_driver_id_without_creating_a_booking(self):
        response = self.client.post(
            self.url, self._payload(driver_id='not-a-driver-id'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose an active driver from this agency')
        self.assertFalse(Booking.objects.exists())
