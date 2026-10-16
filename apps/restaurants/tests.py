from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from establishments.models import establishment_for_instance
from notifications.models import Notification
from simulation.models import ActivityLog, SimulationRoleAssignment
from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

from .models import Reservation, Restaurant, Table
from .services import create_restaurant_reservation

User = get_user_model()


class RestaurantReservationWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'reservation-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.guest = User.objects.create_user(
            'restaurant-guest',
            password='pw',
            first_name='Rae',
            last_name='Guest',
            account_type=User.AccountType.STUDENT,
        )
        cls.officer = User.objects.create_user(
            'reservation-officer',
            password='pw',
            first_name='Anand',
            last_name='Officer',
            account_type=User.AccountType.STUDENT,
        )
        cls.manager = User.objects.create_user(
            'restaurant-manager',
            password='pw',
            first_name='Mina',
            last_name='Manager',
            account_type=User.AccountType.STUDENT,
        )
        cls.other_officer = User.objects.create_user(
            'other-reservation-officer',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.front_desk = User.objects.create_user(
            'restaurant-front-desk',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.restaurant = Restaurant.objects.create(
            name='Casa Test',
            location='Manila',
        )
        cls.other_restaurant = Restaurant.objects.create(
            name='Other Test Restaurant',
            location='Manila',
        )
        cls.restaurant_establishment = establishment_for_instance(
            cls.restaurant, create=True,
        )
        cls.other_establishment = establishment_for_instance(
            cls.other_restaurant, create=True,
        )
        cls.table = Table.objects.create(
            restaurant=cls.restaurant,
            table_number='A1',
            capacity=4,
        )
        cls.other_table = Table.objects.create(
            restaurant=cls.other_restaurant,
            table_number='B1',
            capacity=4,
        )
        cls.guest_assignment = SimulationRoleAssignment.objects.create(
            student=cls.guest,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESTAURANT_GUEST,
            establishment=cls.restaurant_establishment,
            activity_name='Restaurant reservation workflow',
        )
        cls.officer_assignment = SimulationRoleAssignment.objects.create(
            student=cls.officer,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
            establishment=cls.restaurant_establishment,
            activity_name='Restaurant reservation workflow',
        )
        cls.manager_assignment = SimulationRoleAssignment.objects.create(
            student=cls.manager,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESTAURANT_MANAGER,
            establishment=cls.restaurant_establishment,
            activity_name='Restaurant reservation workflow',
        )
        cls.other_officer_assignment = SimulationRoleAssignment.objects.create(
            student=cls.other_officer,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
            establishment=cls.other_establishment,
            activity_name='Other restaurant workflow',
        )
        cls.front_desk_assignment = SimulationRoleAssignment.objects.create(
            student=cls.front_desk,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESTAURANT_FRONT_DESK,
            establishment=cls.restaurant_establishment,
            activity_name='Restaurant reservation workflow',
        )

    def setUp(self):
        self.reservation_datetime = timezone.make_aware(
            datetime(2028, 10, 20, 19, 30),
            timezone.get_current_timezone(),
        )

    def activate_assignment(self, client, assignment):
        session = client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
        session.save()

    def submit_direct_reservation(self, *, client=None, **extra):
        client = client or self.client
        client.force_login(self.guest)
        self.activate_assignment(client, self.guest_assignment)
        return client.post(
            reverse('restaurants:book', args=[self.table.pk]),
            {
                'reservation_datetime': self.reservation_datetime.strftime(
                    '%Y-%m-%dT%H:%M',
                ),
                'guests': '2',
                'special_requests': 'Window seat if available',
                'pay_later': 'on',
                **extra,
            },
            follow=True,
        )

    def test_guest_submission_stays_pending_and_officer_confirms_and_notifies(self):
        guest_response = self.submit_direct_reservation()
        reservation = Reservation.objects.get(customer=self.guest)

        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertContains(
            guest_response,
            'PENDING — Waiting for Restaurant Reservation Officer confirmation.',
        )
        submitted = Notification.objects.get(
            recipient=self.officer,
            notification_type=Notification.Type.RESTAURANT_RESERVATION_SUBMITTED,
        )
        self.assertIn(reservation.booking_reference, submitted.message)

        self.client.force_login(self.officer)
        self.activate_assignment(self.client, self.officer_assignment)
        dashboard = self.client.get(reverse('restaurants:bookings'))
        self.assertContains(dashboard, reservation.booking_reference)
        self.assertContains(dashboard, 'Window seat if available')
        self.assertContains(dashboard, 'Review Reservation')

        review_url = reverse(
            'restaurants:booking_detail', args=[reservation.pk],
        )
        confirm_response = self.client.post(
            review_url,
            {'action': 'confirm', 'remark': 'Table prepared.'},
            follow=True,
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(reservation.confirmed_by, self.officer)
        self.assertIsNotNone(reservation.confirmed_at)
        self.assertEqual(reservation.manager_remarks, 'Table prepared.')
        self.assertContains(confirm_response, 'CONFIRMED')

        confirmation = Notification.objects.get(
            recipient=self.guest,
            notification_type=Notification.Type.RESTAURANT_RESERVATION_CONFIRMED,
        )
        for expected in (
            self.restaurant.name,
            reservation.booking_reference,
            'Table: A1',
            'Guests: 2',
            'Status: CONFIRMED',
            'Restaurant Reservation Officer',
            'Anand Officer',
        ):
            self.assertIn(expected, confirmation.message)

        self.client.force_login(self.guest)
        self.activate_assignment(self.client, self.guest_assignment)
        guest_detail = self.client.get(review_url)
        self.assertContains(
            guest_detail,
            'CONFIRMED — Your table has been reserved.',
        )

        self.client.force_login(self.officer)
        self.activate_assignment(self.client, self.officer_assignment)
        self.client.post(review_url, {'action': 'confirm'}, follow=True)
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.guest,
                notification_type=Notification.Type.RESTAURANT_RESERVATION_CONFIRMED,
            ).count(),
            1,
        )

    def test_shared_restaurant_flow_also_submits_pending_without_fake_confirmation(self):
        self.client.force_login(self.guest)
        self.activate_assignment(self.client, self.guest_assignment)
        response = self.client.post(
            reverse('restaurants:flow_select', args=[self.restaurant.pk]),
            {
                'check_in': self.reservation_datetime.date().isoformat(),
                'time': self.reservation_datetime.strftime('%H:%M'),
                'item_ids': [str(self.table.pk)],
                'item_0_first_name': 'Rae',
                'item_0_last_name': 'Guest',
                'item_0_email': 'rae@example.com',
                'item_0_contact': '09123456789',
                'item_0_adults': '2',
                'item_0_children': '0',
                'item_0_special_request': 'Window seat',
            },
        )
        self.assertEqual(response.status_code, 302)
        reservation = Reservation.objects.get(customer=self.guest)
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.number_of_guests, 2)
        self.assertEqual(reservation.special_requests, 'Window seat')
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.guest,
                notification_type=Notification.Type.RESTAURANT_RESERVATION_CONFIRMED,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.officer,
                notification_type=Notification.Type.RESTAURANT_RESERVATION_SUBMITTED,
            ).exists()
        )

    def test_shared_restaurant_flow_saves_every_selected_table_in_one_submit(self):
        second_table = Table.objects.create(
            restaurant=self.restaurant,
            table_number='A2',
            capacity=4,
        )
        self.client.force_login(self.guest)
        self.activate_assignment(self.client, self.guest_assignment)
        response = self.client.post(
            reverse('restaurants:flow_select', args=[self.restaurant.pk]),
            {
                'check_in': self.reservation_datetime.date().isoformat(),
                'time': self.reservation_datetime.strftime('%H:%M'),
                'item_ids': [str(self.table.pk), str(second_table.pk)],
                'item_0_first_name': 'Rae', 'item_0_last_name': 'Guest',
                'item_0_email': 'rae@example.com',
                'item_0_contact': '09123456789', 'item_0_adults': '2',
                'item_0_children': '0',
                'item_1_first_name': 'Rae', 'item_1_last_name': 'Guest',
                'item_1_email': 'rae@example.com',
                'item_1_contact': '09123456789', 'item_1_adults': '2',
                'item_1_children': '0',
            },
        )
        self.assertEqual(response.status_code, 302)
        reservations = Reservation.objects.filter(
            customer=self.guest, table__in=[self.table, second_table])
        self.assertEqual(reservations.count(), 2)
        self.assertEqual(
            set(reservations.values_list('status', flat=True)),
            {Reservation.Status.PENDING},
        )

    def test_restaurant_selection_opens_with_guest_information_popup(self):
        self.client.force_login(self.guest)
        self.activate_assignment(self.client, self.guest_assignment)
        response = self.client.get(
            reverse('restaurants:flow_select', args=[self.restaurant.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Guest Information')
        self.assertContains(response, 'Continue to tables')
        self.assertContains(response, 'Confirm Booking Now')

    def test_pay_now_checkout_does_not_confirm_a_guest_reservation(self):
        response = self.submit_direct_reservation(pay_later='')
        reservation = Reservation.objects.get(customer=self.guest)

        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertContains(
            response,
            'PENDING — Waiting for Restaurant Reservation Officer confirmation.',
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.guest,
                notification_type=Notification.Type.RESTAURANT_RESERVATION_CONFIRMED,
            ).exists()
        )

    def test_guest_cannot_submit_an_overlapping_reservation_for_the_same_table(self):
        self.submit_direct_reservation()
        second_response = self.submit_direct_reservation(
            reservation_datetime=(
                self.reservation_datetime + timedelta(minutes=60)
            ).strftime('%Y-%m-%dT%H:%M'),
            pay_later='',
        )

        self.assertEqual(Reservation.objects.filter(table=self.table).count(), 1)
        self.assertContains(
            second_response,
            'This table is already reserved for the requested time slot.',
        )

    def test_officer_cannot_review_or_confirm_another_restaurants_reservation(self):
        reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.table,
            when=self.reservation_datetime,
            guests=2,
        )
        other_reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.other_table,
            when=self.reservation_datetime,
            guests=2,
        )
        self.client.force_login(self.officer)
        self.activate_assignment(self.client, self.officer_assignment)
        dashboard = self.client.get(reverse('restaurants:bookings'))
        self.assertContains(dashboard, reservation.booking_reference)
        self.assertNotContains(dashboard, other_reservation.booking_reference)

        self.client.force_login(self.other_officer)
        self.activate_assignment(self.client, self.other_officer_assignment)
        other_dashboard = self.client.get(reverse('restaurants:bookings'))
        self.assertContains(other_dashboard, other_reservation.booking_reference)
        self.assertNotContains(other_dashboard, reservation.booking_reference)
        self.client.raise_request_exception = False

        response = self.client.get(
            reverse('restaurants:booking_detail', args=[reservation.pk]),
        )

        self.assertEqual(response.status_code, 403)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)

    def test_assigned_restaurant_manager_can_confirm_and_receives_submissions(self):
        reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.table,
            when=self.reservation_datetime,
            guests=2,
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.manager,
                notification_type=Notification.Type.RESTAURANT_RESERVATION_SUBMITTED,
            ).exists()
        )
        self.client.force_login(self.manager)
        self.activate_assignment(self.client, self.manager_assignment)

        response = self.client.post(
            reverse('restaurants:booking_detail', args=[reservation.pk]),
            {'action': 'confirm'},
            follow=True,
        )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CONFIRMED)
        self.assertEqual(reservation.confirmed_by, self.manager)
        self.assertContains(response, 'CONFIRMED')

    def test_restaurant_management_shows_only_the_assigned_restaurant(self):
        self.client.force_login(self.manager)
        self.activate_assignment(self.client, self.manager_assignment)

        response = self.client.get(reverse('restaurants:manage'))

        self.assertContains(response, self.restaurant.name)
        self.assertNotContains(response, self.other_restaurant.name)

    def test_restaurant_tables_shows_only_tables_for_the_assigned_restaurant(self):
        self.client.force_login(self.manager)
        self.activate_assignment(self.client, self.manager_assignment)

        response = self.client.get(reverse('restaurants:tables'))

        self.assertContains(response, self.table.table_id)
        self.assertContains(response, self.restaurant.name)
        self.assertNotContains(response, self.other_table.table_id)
        self.assertNotContains(response, self.other_restaurant.name)

    def test_guest_cannot_confirm_their_own_reservation(self):
        reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.table,
            when=self.reservation_datetime,
            guests=2,
        )
        self.client.force_login(self.guest)
        self.activate_assignment(self.client, self.guest_assignment)

        self.client.post(
            reverse('restaurants:booking_detail', args=[reservation.pk]),
            {'action': 'confirm'},
        )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertIsNone(reservation.confirmed_by)

    def test_front_desk_can_review_but_cannot_confirm_reservations(self):
        reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.table,
            when=self.reservation_datetime,
            guests=2,
        )
        self.client.force_login(self.front_desk)
        self.activate_assignment(self.client, self.front_desk_assignment)
        detail_url = reverse('restaurants:booking_detail', args=[reservation.pk])

        response = self.client.get(detail_url)

        self.assertContains(response, reservation.booking_reference)
        self.assertNotContains(response, 'Confirm Reservation')
        self.client.raise_request_exception = False
        denied = self.client.post(detail_url, {'action': 'confirm'})
        self.assertEqual(denied.status_code, 403)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertIsNone(reservation.confirmed_by)

    def test_confirmation_refuses_a_conflicting_reservation_and_keeps_pending(self):
        reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.table,
            when=self.reservation_datetime,
            guests=2,
        )
        Reservation.objects.create(
            customer=self.other_officer,
            table=self.table,
            reservation_datetime=self.reservation_datetime + timedelta(minutes=30),
            number_of_guests=2,
            status=Reservation.Status.PENDING,
        )
        self.client.force_login(self.officer)
        self.activate_assignment(self.client, self.officer_assignment)

        response = self.client.post(
            reverse('restaurants:booking_detail', args=[reservation.pk]),
            {'action': 'confirm'},
            follow=True,
        )

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertIsNone(reservation.confirmed_by)
        self.assertContains(
            response,
            'This table is no longer available for the selected date and time.',
        )

    def test_rejection_requires_reason_notifies_guest_and_cannot_be_confirmed_later(self):
        reservation = create_restaurant_reservation(
            customer=self.guest,
            table=self.table,
            when=self.reservation_datetime,
            guests=2,
        )
        self.client.force_login(self.officer)
        self.activate_assignment(self.client, self.officer_assignment)
        detail_url = reverse('restaurants:booking_detail', args=[reservation.pk])

        self.client.post(
            detail_url,
            {
                'action': 'decline',
                'rejection_reason': 'The requested seating area is unavailable.',
            },
            follow=True,
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.REJECTED)
        self.assertEqual(
            reservation.declined_reason,
            'The requested seating area is unavailable.',
        )
        self.client.force_login(self.guest)
        self.activate_assignment(self.client, self.guest_assignment)
        self.assertContains(
            self.client.get(detail_url),
            'REJECTED — Reservation could not be confirmed.',
        )
        rejection = Notification.objects.get(
            recipient=self.guest,
            notification_type=Notification.Type.RESTAURANT_RESERVATION_REJECTED,
        )
        self.assertIn(reservation.declined_reason, rejection.message)

        self.client.force_login(self.officer)
        self.activate_assignment(self.client, self.officer_assignment)
        self.client.post(detail_url, {'action': 'confirm'}, follow=True)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.REJECTED)
        self.assertIsNone(reservation.confirmed_by)

    def test_do_task_logs_long_restaurant_role_without_database_error(self):
        self.client.force_login(self.officer)

        response = self.client.get(
            reverse('simulation:do_task', args=[self.officer_assignment.pk]),
        )

        self.assertEqual(response.status_code, 200)
        activity = ActivityLog.objects.get(
            user=self.officer,
            action='Started simulation task',
        )
        self.assertEqual(
            activity.simulation_role,
            SimulationRoleAssignment.Role.RESTAURANT_RESERVATION_OFFICER,
        )
