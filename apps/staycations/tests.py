from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from establishments.models import establishment_for_instance
from simulation.models import SimulationRoleAssignment
from staycations.models import Service, Staycation


class StaycationScopingTests(TestCase):
    """A student assigned one staycation sees and manages only that staycation.

    Mirrors the behavior of ``atrue_core.hotel_scope`` for hotels (BR-085): the
    management lists filter to the assigned staycations, and an object-keyed
    view raises 403 as soon as its staycation is not assigned to the student.
    """

    def setUp(self):
        self.instructor = User.objects.create_user(
            'instructor', password='pw', account_type=User.AccountType.INSTRUCTOR)
        self.student = User.objects.create_user(
            'student', password='pw', account_type=User.AccountType.STUDENT)
        self.assigned_staycation = Staycation.objects.create(
            name='Island Breeze', rate=Decimal('5000.00'))
        self.other_staycation = Staycation.objects.create(
            name='Cebu Getaway', rate=Decimal('4000.00'))
        self.assigned_est = establishment_for_instance(
            self.assigned_staycation, create=True)
        self.other_est = establishment_for_instance(self.other_staycation, create=True)
        self.assigned_service = Service.objects.create(
            staycation=self.assigned_staycation, name='Kayak Rental', rate=Decimal('500.00'))
        Service.objects.create(
            staycation=self.other_staycation, name='Private Chef', rate=Decimal('900.00'))

    def _assign(self, establishment):
        return SimulationRoleAssignment.objects.create(
            student=self.student,
            assigned_by=self.instructor,
            role=SimulationRoleAssignment.Role.STAYCATION_MANAGER,
            activity_name='STAY 1',
            establishment=establishment,
        )

    def _login(self, user):
        self.client.force_login(user)
        return user

    def test_only_the_assigned_staycation_is_listed(self):
        self._assign(self.assigned_est)
        self._login(self.student)
        response = self.client.get(reverse('staycations:manage'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Island Breeze', body)
        self.assertNotIn('Cebu Getaway', body)

    def test_only_the_assigned_staycations_services_are_listed(self):
        self._assign(self.assigned_est)
        self._login(self.student)
        response = self.client.get(reverse('staycations:services'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Kayak Rental', body)
        self.assertNotIn('Private Chef', body)

    def test_updating_the_assigned_staycation_is_allowed(self):
        self._assign(self.assigned_est)
        self._login(self.student)
        response = self.client.get(
            reverse('staycations:update_staycation', args=[self.assigned_staycation.pk]))
        self.assertEqual(response.status_code, 200)

    def test_an_unassigned_staycation_update_is_forbidden(self):
        self._assign(self.assigned_est)
        self._login(self.student)
        response = self.client.get(
            reverse('staycations:update_staycation', args=[self.other_staycation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_adding_a_staycation_is_forbidden_for_a_scoped_student(self):
        self._assign(self.assigned_est)
        self._login(self.student)
        response = self.client.get(reverse('staycations:add'))
        self.assertEqual(response.status_code, 403)

    def test_an_assigned_manager_account_with_no_assignment_sees_nothing(self):
        manager = User.objects.create_user(
            'staycation_manager', password='pw',
            account_type='STAYCATION_MANAGER')
        self._login(manager)
        response = self.client.get(reverse('staycations:manage'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('No staycations yet', response.content.decode())

    def test_an_instructor_still_sees_every_staycation(self):
        self._login(self.instructor)
        response = self.client.get(reverse('staycations:manage'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Island Breeze', body)
        self.assertIn('Cebu Getaway', body)
        self.assertIn('Add Staycation', body)

    def test_booking_flow_hides_search_controls_but_keeps_default_booking_dates(self):
        self._login(self.student)
        response = self.client.get(reverse(
            'staycations:flow_select', args=[self.assigned_staycation.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stays')
        self.assertContains(response, 'data-keep-booking-summary')
        self.assertNotContains(response, '1 Search')
        self.assertNotContains(response, 'id="searchCheckIn"')
        self.assertNotContains(response, 'id="searchCheckOut"')
        self.assertNotContains(response, 'class="ag-search-btn"')
        self.assertContains(response, 'id="bkCheckIn"')
        self.assertContains(response, 'id="bkCheckOut"')

    @override_settings(STORAGES={
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    })
    def test_booking_flow_submits_to_shared_review_before_payment(self):
        from datetime import date, timedelta

        from staycations.models import Reservation

        self.student.first_name = 'Ari'
        self.student.last_name = 'Guest'
        self.student.contact_number = '09171234567'
        self.student.save(update_fields=['first_name', 'last_name', 'contact_number'])
        self._login(self.student)
        check_in = date.today() + timedelta(days=2)
        check_out = check_in + timedelta(days=1)

        response = self.client.post(
            reverse('staycations:flow_select', args=[self.assigned_staycation.pk]),
            {
                'check_in': check_in.isoformat(),
                'check_out': check_out.isoformat(),
                'item_ids': [str(self.assigned_staycation.pk)],
                'item_0_first_name': 'Ari',
                'item_0_last_name': 'Guest',
                'item_0_contact': '09171234567',
                'item_0_adults': '1',
                'item_0_children': '0',
            },
        )

        booking = Reservation.objects.get(customer=self.student)
        self.assertRedirects(
            response,
            reverse('establishment_booking_review', args=['staycation', booking.pk]),
        )
        review = self.client.get(response.url)
        self.assertContains(review, 'Review Your Booking')
        self.assertContains(review, 'Price Breakdown')
        self.assertContains(review, 'Island Breeze')
        self.assertContains(review, 'Ari Guest')

    def test_booking_filters_omit_staycation_and_fit_two_rows(self):
        self._login(self.instructor)
        response = self.client.get(reverse('staycations:bookings'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="staycation"')
        self.assertContains(
            response,
            '.staycation-booking-filters.form-grid {'
            '\n        grid-template-columns: repeat(3, minmax(0, 1fr));',
        )
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'name="status"')
        self.assertContains(response, 'name="check_in"')
        self.assertContains(response, 'name="check_out"')
        self.assertContains(response, 'name="sort"')