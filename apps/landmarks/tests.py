from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from establishments.models import establishment_for_instance
from simulation.models import SimulationRoleAssignment
from simulation.task_routing import TASK_ASSIGNMENT_SESSION_KEY

from .models import Landmark, Ticket

User = get_user_model()


class PublicLandmarkListingTests(TestCase):
    def test_public_directory_hides_tourist_spots_but_keeps_landmarks(self):
        Landmark.objects.create(
            name='Visible landmark', category=Landmark.Category.LANDMARK,
        )
        Landmark.objects.create(
            name='Hidden tourist spot', category=Landmark.Category.TOURIST_SPOT,
        )

        response = self.client.get(reverse('landmarks:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Visible landmark')
        self.assertNotContains(response, 'Hidden tourist spot')


def _assign(user, instructor, landmark, role):
    assignment = SimulationRoleAssignment.objects.create(
        student=user,
        assigned_by=instructor,
        role=role,
        establishment=establishment_for_instance(landmark, create=True),
        activity_name='Landmark operations',
    )
    return assignment


class AssignedLandmarkDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'landmark-scope-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.manager = User.objects.create_user(
            'landmark-scope-manager',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.landmark = Landmark.objects.create(
            name='Assigned Landmark',
            category=Landmark.Category.LANDMARK,
        )
        cls.other_landmark = Landmark.objects.create(
            name='Other Landmark',
            category=Landmark.Category.LANDMARK,
        )
        cls.assignment = SimulationRoleAssignment.objects.create(
            student=cls.manager,
            assigned_by=cls.instructor,
            role=SimulationRoleAssignment.Role.LANDMARK_MANAGER,
            establishment=establishment_for_instance(cls.landmark, create=True),
            activity_name='Landmark directory',
        )
        establishment_for_instance(cls.other_landmark, create=True)

    def test_landmark_manager_sees_only_the_assigned_landmark(self):
        self.client.force_login(self.manager)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = self.assignment.pk
        session.save()

        response = self.client.get(reverse('landmarks:manage'))

        self.assertContains(response, self.landmark.name)
        self.assertNotContains(response, self.other_landmark.name)

    def test_landmark_manager_sees_only_tickets_for_the_assigned_landmark(self):
        assigned_ticket = Ticket.objects.create(
            customer=self.manager,
            destination_type=Ticket.DestinationType.LANDMARK,
            destination=self.landmark,
        )
        other_ticket = Ticket.objects.create(
            customer=self.manager,
            destination_type=Ticket.DestinationType.LANDMARK,
            destination=self.other_landmark,
        )
        self.client.force_login(self.manager)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = self.assignment.pk
        session.save()

        response = self.client.get(reverse('landmarks:bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context['bookings'].values_list('pk', flat=True)),
            [assigned_ticket.pk],
        )
        self.assertNotContains(response, other_ticket.booking_reference)


class LandmarkOfficerWorkflowTests(TestCase):
    """Split-of-duties: the reservation officer confirms, the front desk checks in."""

    ROLES = SimulationRoleAssignment.Role

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'landmark-officer-instructor',
            password='pw',
            account_type=User.AccountType.INSTRUCTOR,
        )
        cls.customer = User.objects.create_user(
            'landmark-officer-customer',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.reservation_officer = User.objects.create_user(
            'landmark-reservation-officer',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.front_desk = User.objects.create_user(
            'landmark-front-desk',
            password='pw',
            account_type=User.AccountType.STUDENT,
        )
        cls.landmark = Landmark.objects.create(
            name='Officer Duty Landmark',
            category=Landmark.Category.LANDMARK,
            entry_fee=100,
        )
        cls.ro_assignment = _assign(
            cls.reservation_officer, cls.instructor, cls.landmark, cls.ROLES.LANDMARK_RESERVATION_OFFICER)
        cls.fd_assignment = _assign(
            cls.front_desk, cls.instructor, cls.landmark, cls.ROLES.LANDMARK_FRONT_DESK)

    def _book(self, status='PENDING'):
        return Ticket.objects.create(
            customer=self.customer,
            destination_type=Ticket.DestinationType.LANDMARK,
            destination=self.landmark,
            total_bill=100,
            status=status,
        )

    def _login_for(self, user, assignment):
        self.client.force_login(user)
        session = self.client.session
        session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
        session.save()

    def test_reservation_officer_bookings_default_to_pending(self):
        pending = self._book()
        self._book(status='CONFIRMED')
        self._login_for(self.reservation_officer, self.ro_assignment)

        response = self.client.get(reverse('landmarks:bookings'))

        self.assertEqual(response.context['queue'], 'confirm')
        self.assertEqual(
            list(response.context['bookings'].values_list('pk', flat=True)),
            [pending.pk],
        )

    def test_front_desk_bookings_default_to_confirmed(self):
        confirmed = self._book(status='CONFIRMED')
        self._book(status='PENDING')
        self._login_for(self.front_desk, self.fd_assignment)

        response = self.client.get(reverse('landmarks:bookings'))

        self.assertEqual(response.context['queue'], 'checkin')
        self.assertEqual(
            list(response.context['bookings'].values_list('pk', flat=True)),
            [confirmed.pk],
        )

    def test_reservation_officer_can_confirm_but_not_check_in(self):
        pending = self._book()
        self._login_for(self.reservation_officer, self.ro_assignment)

        response = self.client.post(
            reverse('landmarks:booking_detail', args=[pending.pk]),
            {'action': 'confirm'},
        )
        self.assertRedirects(response, reverse('landmarks:booking_detail', args=[pending.pk]))
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'CONFIRMED')

        response = self.client.post(
            reverse('landmarks:booking_detail', args=[pending.pk]),
            {'action': 'use'},
        )
        self.assertRedirects(response, reverse('landmarks:booking_detail', args=[pending.pk]))
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'CONFIRMED')

    def test_front_desk_can_check_in_but_not_confirm(self):
        confirmed = self._book(status='CONFIRMED')
        self._login_for(self.front_desk, self.fd_assignment)

        response = self.client.post(
            reverse('landmarks:booking_detail', args=[confirmed.pk]),
            {'action': 'use'},
        )
        self.assertRedirects(response, reverse('landmarks:booking_detail', args=[confirmed.pk]))
        confirmed.refresh_from_db()
        self.assertEqual(confirmed.status, 'USED')

        response = self.client.post(
            reverse('landmarks:booking_detail', args=[confirmed.pk]),
            {'action': 'confirm'},
        )
        self.assertRedirects(response, reverse('landmarks:booking_detail', args=[confirmed.pk]))
        confirmed.refresh_from_db()
        self.assertEqual(confirmed.status, 'USED')
