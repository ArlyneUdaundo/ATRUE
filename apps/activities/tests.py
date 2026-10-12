from datetime import date

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from establishments.models import Establishment, establishment_for_instance
from simulation.models import SimulationRoleAssignment

Role = SimulationRoleAssignment.Role
from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

from .models import Activity, ActivityProvider, Booking

User = get_user_model()


class AssignedActivityDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'activity-scope-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.customer = User.objects.create_user(
            'activity-customer',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.provider = ActivityProvider.objects.create(
            name='Assigned Provider', location='Manila')
        cls.other_provider = ActivityProvider.objects.create(
            name='Other Provider', location='Manila')
        cls.activity = Activity.objects.create(
            name='Assigned Activity', provider=cls.provider, fee=100)
        cls.other_activity = Activity.objects.create(
            name='Other Activity', provider=cls.other_provider, fee=100)
        # The auto-establish signal owns the wrapper for the assigned activity.
        cls.activity_est = establishment_for_instance(cls.activity)

    def assignment_for(self, user, role, establishment):
        return SimulationRoleAssignment.objects.create(
            student=user, assigned_by=self.instructor, role=role,
            establishment=establishment, activity_name='Activity directory')

    def set_task(self, assignment):
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
        session.save()

    def make_booking(self, activity, status=Booking.Status.CONFIRMED):
        return Booking.objects.create(
            customer=self.customer, activity=activity,
            schedule_date=date.today(), participant_count=2, status=status)

    def test_operator_cannot_open_the_manage_directory(self):
        # The manage directory is the Manager's job; an operator who tries to
        # walk in is refused before any scope question comes up.
        user = User.objects.create_user(
            'activity-operator', password='pw', account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_OPERATOR, self.activity_est))

        response = self.client.get(reverse('activities:manage'))

        self.assertEqual(response.status_code, 403)

    def test_operator_operate_lists_only_the_assigned_activity_and_its_bookings(self):
        user = User.objects.create_user(
            'activity-operator-2', password='pw', account_type=User.AccountType.STUDENT)
        mine = self.make_booking(self.activity)
        theirs = self.make_booking(self.other_activity)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_OPERATOR, self.activity_est))

        response = self.client.get(reverse('activities:operate'))

        self.assertContains(response, self.activity.name)
        self.assertContains(response, f'<td class="mono">#{mine.pk}</td>')
        self.assertNotContains(response, self.other_activity.name)
        self.assertNotContains(response, f'<td class="mono">#{theirs.pk}</td>')

    def test_operator_completes_an_assigned_booking(self):
        user = User.objects.create_user(
            'activity-operator-3', password='pw', account_type=User.AccountType.STUDENT)
        booking = self.make_booking(self.activity, status=Booking.Status.CHECKED_IN)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_OPERATOR, self.activity_est))

        response = self.client.post(reverse('activities:operate'), {
            'action': 'complete',
            'activity_id': self.activity.pk,
            'booking_id': booking.pk,
        })

        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.COMPLETED)

    def test_reservation_officer_sees_only_assigned_activity_bookings(self):
        user = User.objects.create_user(
            'activity-reservation', password='pw', account_type=User.AccountType.STUDENT)
        mine = self.make_booking(self.activity)
        theirs = self.make_booking(self.other_activity)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_RESERVATION_OFFICER, self.activity_est))

        response = self.client.get(reverse('activities:bookings'))

        self.assertContains(response, f'<td class="mono">#{mine.pk}</td>')
        self.assertNotContains(response, f'<td class="mono">#{theirs.pk}</td>')

    def test_booking_detail_raises_403_for_an_unassigned_activity_booking(self):
        user = User.objects.create_user(
            'activity-reservation-2', password='pw', account_type=User.AccountType.STUDENT)
        theirs = self.make_booking(self.other_activity)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_RESERVATION_OFFICER, self.activity_est))

        response = self.client.get(
            reverse('activities:booking_detail', args=[theirs.pk]))

        self.assertEqual(response.status_code, 403)

    def test_a_user_can_still_view_their_own_booking_in_another_activity(self):
        # Operators and officers who booked elsewhere keep their customer view.
        user = User.objects.create_user(
            'activity-operator-customer', password='pw',
            account_type=User.AccountType.STUDENT)
        booking = Booking.objects.create(
            customer=user, activity=self.other_activity,
            schedule_date=date.today(), participant_count=1,
            status=Booking.Status.CONFIRMED)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_OPERATOR, self.activity_est))

        response = self.client.get(
            reverse('activities:booking_detail', args=[booking.pk]))

        self.assertEqual(response.status_code, 200)

    def test_operator_without_a_real_activity_sees_an_empty_operate_screen(self):
        # A wrapper without a live Activity behind it scopes to nothing: the
        # operator's day opens on an empty roster, not somebody else's.
        user = User.objects.create_user(
            'activity-operator-unassigned', password='pw',
            account_type=User.AccountType.STUDENT)
        self.client.force_login(user)
        self.set_task(self.assignment_for(
            user, Role.ACTIVITY_OPERATOR,
            Establishment.objects.create(
                name='Ghost Activity', type=Establishment.Type.ACTIVITY)))

        response = self.client.get(reverse('activities:operate'))

        self.assertEqual(response.status_code, 200)
        # The roster row for a real activity is a card header; an empty roster
        # prints "No activity assigned to you" instead. The former is what must
        # stay out (the static page title also reads "Operate Assigned
        # Activity", so an exact-card match is the check that means anything).
        self.assertContains(response, 'No activity assigned to you')
        self.assertNotContains(
            response, f'<i class="fas fa-person-hiking"></i> {self.activity.name}')
        self.assertNotContains(response, self.other_activity.name)

    def test_instructor_sees_every_activity(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse('activities:manage'))
        self.assertContains(response, self.activity.name)
        self.assertContains(response, self.other_activity.name)