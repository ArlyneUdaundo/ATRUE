from datetime import date, timedelta

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone

from establishments.models import establishment_for_instance
from simulation.models import SimulationRoleAssignment
from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

from .models import AdditionalGuest, Reservation, Resort, RoomVilla

User = get_user_model()


class AssignedResortDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'resort-scope-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.manager = User.objects.create_user(
            'resort-scope-manager',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.resort = Resort.objects.create(name='Assigned Resort')
        cls.other_resort = Resort.objects.create(name='Other Resort')
        cls.assignment = SimulationRoleAssignment.objects.create(
            student=cls.manager,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESORT_MANAGER,
            establishment=establishment_for_instance(cls.resort, create=True),
            activity_name='Resort directory',
        )
        establishment_for_instance(cls.other_resort, create=True)

    def test_resort_manager_sees_only_the_assigned_resort(self):
        self.client.force_login(self.manager)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = self.assignment.pk
        session.save()

        response = self.client.get(reverse('resorts:manage'))

        self.assertContains(response, self.resort.name)
        self.assertNotContains(response, self.other_resort.name)


class AssignedResortBookingTests(TestCase):
    """A Reservation Officer reaches only the assigned resort's reservations.

    The officer answers the bookings their resort receives - a guest's request
    lands PENDING and the officer confirms it - and must not see, let alone
    confirm, another resort's bookings.
    """

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'resort-booking-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.guest = User.objects.create_user(
            'resort-booking-guest',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.officer = User.objects.create_user(
            'resort-booking-officer',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.resort = Resort.objects.create(name='Alona Booking Resort')
        cls.other_resort = Resort.objects.create(name='Bahura Booking Resort')
        cls.unit = RoomVilla.objects.create(
            resort=cls.resort, unit_number='B1', rate='1500')
        cls.other_unit = RoomVilla.objects.create(
            resort=cls.other_resort, unit_number='B1', rate='2000')
        cls.assignment = SimulationRoleAssignment.objects.create(
            student=cls.officer,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.RESORT_RESERVATION_OFFICER,
            establishment=establishment_for_instance(cls.resort, create=True),
            activity_name='Resort bookings',
        )
        establishment_for_instance(cls.other_resort, create=True)

    def make_reservation(self, unit, customer=None, status=Reservation.Status.PENDING):
        return Reservation.objects.create(
            customer=customer or self.guest, unit=unit,
            check_in=date.today(), check_out=date.today() + timedelta(days=2),
            number_of_adults=2, status=status,
        )

    def _activate(self):
        self.client.force_login(self.officer)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = self.assignment.pk
        session.save()

    def test_guest_reservation_lands_pending_and_the_officer_confirms_it(self):
        from transactions.models import Bill

        booking = self.make_reservation(self.unit)
        Bill.objects.create(
            service='resorts',
            customer=booking.customer,
            content_type=ContentType.objects.get_for_model(booking),
            object_id=booking.pk,
            total_amount=booking.total_bill,
            amount_paid=booking.total_bill,
            balance_due=0,
            status=Bill.Status.FULLY_PAID,
            verified_at=timezone.now(),
        )
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self._activate()

        response = self.client.post(
            reverse('resorts:booking_detail', args=[booking.pk]),
            {'action': 'confirm'},
        )

        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.CONFIRMED)

    def test_reservation_officer_sees_only_the_assigned_resort_bookings(self):
        mine = self.make_reservation(self.unit)
        theirs = self.make_reservation(self.other_unit)
        self._activate()

        response = self.client.get(reverse('resorts:bookings'))

        self.assertContains(
            response, f'<td class="mono">{mine.booking_reference}</td>')
        self.assertNotContains(
            response, f'<td class="mono">{theirs.booking_reference}</td>')

    def test_resort_reservation_pages_use_the_hotel_booking_layout(self):
        booking = self.make_reservation(self.unit)
        self._activate()

        bookings_page = self.client.get(reverse('resorts:bookings'))
        self.assertContains(bookings_page, 'hotel-booking-filter-grid')
        self.assertContains(bookings_page, '<th>Photo</th>')
        self.assertContains(bookings_page, '<th>Resort / Unit</th>')

        detail_page = self.client.get(
            reverse('resorts:booking_detail', args=[booking.pk]))
        self.assertContains(detail_page, 'hbd-main-grid')
        self.assertContains(detail_page, 'hbd-gallery')
        self.assertContains(detail_page, 'hbd-billing-wrap')

    def test_resort_unit_type_filter_is_preserved_in_the_shared_list(self):
        villa = RoomVilla.objects.create(
            resort=self.resort, unit_number='V1', rate='2500',
            unit_type=RoomVilla.UnitType.VILLA,
        )
        room_booking = self.make_reservation(self.unit)
        villa_booking = self.make_reservation(villa)
        self._activate()

        response = self.client.get(
            reverse('resorts:bookings'), {'unit_type': RoomVilla.UnitType.VILLA})

        self.assertContains(response, villa_booking.booking_reference)
        self.assertNotContains(response, room_booking.booking_reference)

    def test_resort_front_desk_checkin_and_checkout_actions_still_work(self):
        officer = User.objects.create_user(
            'resort-front-desk-action', password='pw',
            account_type=User.AccountType.STUDENT,
        )
        assignment = SimulationRoleAssignment.objects.create(
            student=officer,
            assigned_by=self.instructor,
            role=SimulationRoleAssignment.Role.RESORT_FRONT_DESK,
            establishment=establishment_for_instance(self.resort, create=True),
            activity_name='Resort front desk actions',
        )
        booking = self.make_reservation(self.unit, status=Reservation.Status.CONFIRMED)
        self.client.force_login(officer)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
        session.save()

        detail_url = reverse('resorts:booking_detail', args=[booking.pk])
        detail = self.client.get(detail_url)
        self.assertContains(detail, 'hbd-main-grid')
        self.assertContains(detail, 'name="action" value="checkin"')
        checked_in = self.client.post(detail_url, {'action': 'checkin'})
        self.assertEqual(checked_in.status_code, 302)
        booking.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.CHECKED_IN)
        self.assertEqual(self.unit.status, RoomVilla.Status.OCCUPIED)

        checked_out = self.client.post(detail_url, {'action': 'checkout'})
        self.assertEqual(checked_out.status_code, 302)
        booking.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.CHECKED_OUT)
        self.assertEqual(self.unit.status, RoomVilla.Status.AVAILABLE)

    def test_resort_manager_modify_and_cancel_actions_still_work(self):
        manager = User.objects.create_user(
            'resort-manager-action', password='pw',
            account_type=User.AccountType.STUDENT,
        )
        assignment = SimulationRoleAssignment.objects.create(
            student=manager,
            assigned_by=self.instructor,
            role=SimulationRoleAssignment.Role.RESORT_MANAGER,
            establishment=establishment_for_instance(self.resort, create=True),
            activity_name='Resort manager actions',
        )
        self.client.force_login(manager)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
        session.save()

        booking = self.make_reservation(self.unit)
        detail_url = reverse('resorts:booking_detail', args=[booking.pk])
        detail = self.client.get(detail_url)
        self.assertContains(detail, 'hbd-main-grid')
        self.assertContains(detail, 'name="action" value="modify"')
        modified = self.client.post(detail_url, {
            'action': 'modify',
            'check_in': (date.today() + timedelta(days=10)).isoformat(),
            'check_out': (date.today() + timedelta(days=12)).isoformat(),
            'adults': '2',
            'children': '0',
        })
        self.assertEqual(modified.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.MODIFIED)

        confirmed = self.make_reservation(
            self.unit, status=Reservation.Status.CONFIRMED)
        cancel_url = reverse('resorts:booking_detail', args=[confirmed.pk])
        cancel_detail = self.client.get(cancel_url)
        self.assertContains(cancel_detail, 'name="action" value="cancel"')
        cancelled = self.client.post(cancel_url, {'action': 'cancel'})
        self.assertEqual(cancelled.status_code, 302)
        confirmed.refresh_from_db()
        self.assertEqual(confirmed.status, Reservation.Status.CANCELLED)

    def test_reservation_officer_gets_403_for_an_unassigned_resort_booking(self):
        theirs = self.make_reservation(self.other_unit)
        self._activate()

        response = self.client.get(
            reverse('resorts:booking_detail', args=[theirs.pk]))

        self.assertEqual(response.status_code, 403)

    def test_a_resort_user_can_still_view_their_own_booking_elsewhere(self):
        # The officer booked another resort as a customer; their own booking
        # stays reachable even though it is outside their assignment.
        booking = self.make_reservation(self.other_unit, customer=self.officer)
        self._activate()

        response = self.client.get(
            reverse('resorts:booking_detail', args=[booking.pk]))

        self.assertEqual(response.status_code, 200)


class ResortMultiUnitGuestAssignmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'multi-unit-guest', password='pw', account_type=User.AccountType.STUDENT,
            first_name='Ari', middle_name='Mae', last_name='Dela Cruz',
            email='ari@example.com', contact_number='09171234567',
        )
        self.resort = Resort.objects.create(name='Ordered Unit Resort')
        self.second = RoomVilla.objects.create(
            resort=self.resort, unit_number='B-20', rate='1800.00', capacity_adults=4, capacity_children=2)
        self.first = RoomVilla.objects.create(
            resort=self.resort, unit_number='A-10', rate='1600.00', capacity_adults=4, capacity_children=2)
        self.client.force_login(self.user)

    def test_selected_order_and_guest_assignments_are_saved_and_displayed(self):
        check_in = date.today() + timedelta(days=10)
        check_out = check_in + timedelta(days=2)
        response = self.client.post(
            reverse('resorts:flow_select', args=[self.resort.pk]),
            {
                'item_ids': [str(self.second.pk), str(self.first.pk)],
                'check_in': check_in.isoformat(), 'check_out': check_out.isoformat(),
                'pay_later': 'on',
                'item_0_first_name': 'Spoof', 'item_0_last_name': 'Identity',
                'item_0_email': 'spoof@example.com', 'item_0_contact': '09999999999',
                'item_0_adults': '1', 'item_0_children': '0',
                'item_1_first_name': 'Bea', 'item_1_middle_name': 'Joy',
                'item_1_last_name': 'Guest', 'item_1_email': 'bea@example.com',
                'item_1_contact': '09170000000', 'item_1_adults': '2',
                'item_1_children': '1',
            },
        )
        booking = Reservation.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(booking.unit_id, self.second.pk)
        self.assertEqual(booking.customer_id, self.user.pk)
        self.assertEqual(booking.payer_name, 'Ari Mae Dela Cruz')
        assignment = AdditionalGuest.objects.get(reservation=booking)
        self.assertEqual(assignment.unit_id, self.first.pk)
        self.assertEqual(assignment.selection_order, 2)
        self.assertEqual(
            (assignment.first_name, assignment.middle_name, assignment.last_name),
            ('Bea', 'Joy', 'Guest'),
        )
        self.assertEqual(assignment.email, 'bea@example.com')
        self.assertEqual(assignment.contact, '09170000000')
        self.assertEqual((assignment.adults, assignment.children), (2, 1))

        detail = self.client.get(reverse('resorts:booking_detail', args=[booking.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Ari Mae Dela Cruz')
        self.assertContains(detail, 'bea@example.com')
        self.assertContains(detail, 'A-10')
