from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from establishments.models import establishment_for_instance
from hotels.models import Booking as HotelBooking
from hotels.models import BookingRoom, Hotel, Room
from simulation.models import SimulationRoleAssignment

User = get_user_model()


@override_settings(STORAGES={
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
})
class MyBookingsNavigationTests(TestCase):
    """The account menu opens the customer's bookings, not the task screen."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            'booking-owner', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.other = User.objects.create_user(
            'booking-other', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.hotel = Hotel.objects.create(name='Navigation Inn')
        cls.room = Room.objects.create(
            hotel=cls.hotel, room_number='101', rate='1500.00')
        cls.establishment = establishment_for_instance(cls.hotel, create=True)
        cls.booking = HotelBooking.objects.create(
            customer=cls.student, status=HotelBooking.Status.CONFIRMED)
        BookingRoom.objects.create(
            booking=cls.booking, room=cls.room,
            check_in=date(2030, 1, 2), check_out=date(2030, 1, 3))
        cls.other_booking = HotelBooking.objects.create(
            customer=cls.other, status=HotelBooking.Status.CONFIRMED)
        BookingRoom.objects.create(
            booking=cls.other_booking, room=cls.room,
            check_in=date(2030, 1, 2), check_out=date(2030, 1, 3))

    def setUp(self):
        self.assignment = SimulationRoleAssignment.objects.create(
            student=self.student,
            role=SimulationRoleAssignment.Role.GUEST_HOTEL,
            establishment=self.establishment,
            activity_name='Navigation test',
            simulation_date=timezone.localdate() + timedelta(days=1),
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
        )
        self.client.force_login(self.student)

    def test_account_menu_link_opens_own_bookings_during_an_upcoming_task(self):
        response = self.client.get(
            reverse('transactions:booking_list') + '?nav=my-bookings')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'transactions/bookings.html')
        self.assertContains(response, self.booking.booking_reference)
        self.assertNotContains(response, self.other_booking.booking_reference)

    def test_simulation_task_link_still_enforces_the_window(self):
        response = self.client.get(reverse('transactions:booking_list'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse('simulation:role_detail', args=[self.assignment.pk]))
