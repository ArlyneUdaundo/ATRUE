from datetime import date

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from establishments.models import Establishment, establishment_for_instance
from simulation.models import SimulationRoleAssignment

Role = SimulationRoleAssignment.Role
from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

from .models import Booking, TourPackage
from transactions.models import Bill, Payment, Receipt

User = get_user_model()


class AssignedTourPackageDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'package-scope-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.customer = User.objects.create_user(
            'package-customer',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.package = TourPackage.objects.create(
            name='Assigned Package', price=100)
        cls.other_package = TourPackage.objects.create(
            name='Other Package', price=100)
        # The auto-establish signal owns the wrapper for the assigned package.
        cls.package_est = establishment_for_instance(cls.package)

    def assignment_for(self, user, role, establishment):
        return SimulationRoleAssignment.objects.create(
            student=user, assigned_by=self.instructor, role=role,
            establishment=establishment, activity_name='Tour package directory')

    def set_task(self, assignment):
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
        session.save()

    def make_booking(self, package, status=Booking.Status.CONFIRMED):
        return Booking.objects.create(
            customer=self.customer, package=package,
            travel_date=date.today(), number_of_travelers=2, status=status)

    def test_operator_cannot_open_the_manage_directory(self):
        # The manage directory is the Manager's job; an operator who tries to
        # walk in is refused before any scope question comes up.
        user = User.objects.create_user(
            'package-operator', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_FRONT_DESK_OFFICER, self.package_est))

        response = self.client.get(reverse('tour_package:manage'))

        self.assertEqual(response.status_code, 403)

    def test_frontdesk_operate_lists_only_the_assigned_package_and_its_bookings(self):
        user = User.objects.create_user(
            'package-operator-2', password='pw', account_type=User.AccountType.STUDENT)
        mine = self.make_booking(self.package)
        theirs = self.make_booking(self.other_package)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_FRONT_DESK_OFFICER, self.package_est))

        response = self.client.get(reverse('tour_package:operate'))

        self.assertContains(response, self.package.name)
        self.assertContains(response, f'<td class="mono">#{mine.pk}</td>')
        self.assertNotContains(response, self.other_package.name)
        self.assertNotContains(response, f'<td class="mono">#{theirs.pk}</td>')

    def test_frontdesk_completes_an_assigned_booking(self):
        user = User.objects.create_user(
            'package-operator-3', password='pw', account_type=User.AccountType.STUDENT)
        booking = self.make_booking(self.package, status=Booking.Status.CHECKED_IN)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_FRONT_DESK_OFFICER, self.package_est))

        response = self.client.post(reverse('tour_package:operate'), {
            'action': 'complete',
            'package_id': self.package.pk,
            'booking_id': booking.pk,
        })

        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.COMPLETED)

    def test_reservation_officer_sees_only_assigned_package_bookings(self):
        user = User.objects.create_user(
            'package-reservation', password='pw', account_type=User.AccountType.STUDENT)
        mine = self.make_booking(self.package)
        theirs = self.make_booking(self.other_package)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_RESERVATION_OFFICER, self.package_est))

        response = self.client.get(reverse('tour_package:bookings'))

        # The bookings table renders the booking reference, not the row id.
        self.assertContains(
            response, f'<td class="mono">{mine.booking_reference}</td>')
        self.assertNotContains(
            response, f'<td class="mono">{theirs.booking_reference}</td>')

    def test_booking_detail_raises_403_for_an_unassigned_package_booking(self):
        user = User.objects.create_user(
            'package-reservation-2', password='pw', account_type=User.AccountType.STUDENT)
        theirs = self.make_booking(self.other_package)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_RESERVATION_OFFICER, self.package_est))

        response = self.client.get(
            reverse('tour_package:booking_detail', args=[theirs.pk]))

        self.assertEqual(response.status_code, 404)

    def test_a_user_can_still_view_their_own_booking_in_another_package(self):
        user = User.objects.create_user(
            'package-operator-customer', password='pw',
            account_type=User.AccountType.STUDENT)
        booking = Booking.objects.create(
            customer=user, package=self.other_package,
            travel_date=date.today(), number_of_travelers=1,
            status=Booking.Status.CONFIRMED)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_FRONT_DESK_OFFICER, self.package_est))

        response = self.client.get(
            reverse('tour_package:booking_detail', args=[booking.pk]))

        self.assertEqual(response.status_code, 404)

    def test_assigned_guest_sees_only_the_assigned_package(self):
        user = User.objects.create_user(
            'assigned-package-guest', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(user, Role.TOUR_GUEST, self.package_est))

        response = self.client.get(reverse('tour_package:list'))

        self.assertContains(response, self.package.name)
        self.assertNotContains(response, self.other_package.name)

    def test_guest_cannot_open_or_book_an_unassigned_package(self):
        user = User.objects.create_user(
            'assigned-package-guest-2', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(user, Role.TOUR_GUEST, self.package_est))

        detail = self.client.get(reverse('tour_package:detail', args=[self.other_package.slug]))
        booking = self.client.post(reverse('tour_package:book_package', args=[self.other_package.pk]))

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(booking.status_code, 404)

    def test_assigned_guest_can_book_the_assigned_package(self):
        user = User.objects.create_user(
            'assigned-package-booker', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(user, Role.TOUR_GUEST, self.package_est))

        response = self.client.post(
            reverse('tour_package:book_package', args=[self.package.pk]),
            {'travel_date': date.today().isoformat(), 'travelers': '1', 'adults': '1',
             'payment_method': 'MAYA', 'pay_later': 'on'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Booking.objects.filter(customer=user, package=self.package).exists())

    def test_no_assignment_returns_no_package_records(self):
        user = User.objects.create_user(
            'unassigned-package-user', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)

        response = self.client.get(reverse('tour_package:list'))

        self.assertNotContains(response, self.package.name)
        self.assertNotContains(response, self.other_package.name)

    def test_assignment_changes_immediately_change_guest_scope(self):
        user = User.objects.create_user(
            'dynamic-package-guest', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)

        before = self.client.get(reverse('tour_package:list'))
        assignment = self.assignment_for(user, Role.TOUR_GUEST, self.package_est)
        after = self.client.get(reverse('tour_package:list'))
        assignment.status = SimulationRoleAssignment.AssignmentStatus.INACTIVE
        assignment.save(update_fields=['status'])
        revoked = self.client.get(reverse('tour_package:list'))

        self.assertNotContains(before, self.package.name)
        self.assertContains(after, self.package.name)
        self.assertNotContains(revoked, self.package.name)

    def test_my_bookings_and_bill_detail_hide_unassigned_package_records(self):
        user = User.objects.create_user(
            'package-payment-scope', password='pw', account_type=User.AccountType.STUDENT)
        booking = self.make_booking(self.other_package)
        booking.customer = user
        booking.save(update_fields=['customer'])
        bill = Bill(customer=user, service='tour_package', total_amount=100, balance_due=100)
        bill.link_to_booking(booking)
        bill.save()
        payment = Payment.objects.create(
            bill=bill, customer=user, amount=100, method='CASH', status=Payment.Status.PAID)
        payment.link_to_booking(booking)
        payment.save(update_fields=['content_type', 'object_id'])
        receipt = Receipt.objects.create(payment=payment, bill=bill, customer=user, amount=100)
        self.client.force_login(user)
        self.set_task(self.assignment_for(user, Role.TOUR_GUEST, self.package_est))

        bookings = self.client.get(reverse('transactions:booking_list'))
        transactions = self.client.get(reverse('transactions:list'))
        bill_detail = self.client.get(reverse('transactions:bill_detail', args=[bill.pk]))
        receipt_detail = self.client.get(reverse('transactions:receipt_detail', args=[receipt.pk]))

        self.assertNotContains(bookings, booking.booking_reference)
        self.assertNotContains(transactions, bill.bill_reference)
        self.assertNotContains(transactions, payment.payment_reference)
        self.assertNotContains(transactions, receipt.receipt_reference)
        self.assertEqual(bill_detail.status_code, 403)
        self.assertEqual(receipt_detail.status_code, 403)

    def test_reservation_officer_cannot_perform_frontdesk_action(self):
        user = User.objects.create_user(
            'package-reservation-3', password='pw', account_type=User.AccountType.STUDENT)
        booking = self.make_booking(self.package, status=Booking.Status.CONFIRMED)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_RESERVATION_OFFICER, self.package_est))

        response = self.client.post(
            reverse('tour_package:booking_detail', args=[booking.pk]), {'action': 'complete'})

        self.assertEqual(response.status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_reservation_officer_confirms_an_assigned_package_booking(self):
        user = User.objects.create_user(
            'package-reservation-confirm', password='pw', account_type=User.AccountType.STUDENT)
        booking = self.make_booking(self.package, status=Booking.Status.PENDING)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_RESERVATION_OFFICER, self.package_est))

        response = self.client.post(
            reverse('tour_package:booking_detail', args=[booking.pk]), {'action': 'confirm'})

        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_assigned_package_manager_can_update_only_the_assigned_package(self):
        user = User.objects.create_user(
            'package-manager-update', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(user, Role.TOUR_PACKAGE_MANAGER, self.package_est))
        payload = {'name': 'Updated Assigned Package', 'price': '125.00'}

        allowed = self.client.post(
            reverse('tour_package:update_package', args=[self.package.pk]), payload)
        denied = self.client.post(
            reverse('tour_package:update_package', args=[self.other_package.pk]), payload)

        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(denied.status_code, 404)
        self.package.refresh_from_db()
        self.assertEqual(self.package.name, 'Updated Assigned Package')

    def test_guest_assignment_does_not_expand_manager_role_to_another_package(self):
        user = User.objects.create_user(
            'package-mixed-roles', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.assignment_for(user, Role.TOUR_PACKAGE_MANAGER, self.package_est)
        other_establishment = establishment_for_instance(self.other_package)
        self.assignment_for(user, Role.TOUR_GUEST, other_establishment)

        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_MANAGER, self.package_est))
        response = self.client.post(
            reverse('tour_package:update_package', args=[self.other_package.pk]),
            {'name': 'Unauthorized update', 'price': '100.00'},
        )

        self.assertEqual(response.status_code, 404)
        self.other_package.refresh_from_db()
        self.assertEqual(self.other_package.name, 'Other Package')

    def test_frontdesk_cannot_process_booking_from_another_assigned_package_id(self):
        user = User.objects.create_user(
            'package-frontdesk-1', password='pw', account_type=User.AccountType.STUDENT)
        booking = self.make_booking(self.other_package, status=Booking.Status.CONFIRMED)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.TOUR_PACKAGE_OPERATOR, self.package_est))

        response = self.client.post(reverse('tour_package:operate'), {
            'action': 'attend', 'package_id': self.package.pk, 'booking_id': booking.pk,
        })

        self.assertEqual(response.status_code, 404)

    def test_instructor_sees_every_package(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse('tour_package:manage'))
        self.assertContains(response, self.package.name)
        self.assertContains(response, self.other_package.name)
