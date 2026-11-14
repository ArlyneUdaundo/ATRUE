import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification
from simulation.models import ActivityLog, SimulationRoleAssignment, SimulationSession

User = get_user_model()
Role = SimulationRoleAssignment.Role


class InstructorAnnouncementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            'announcement-instructor', password='pw',
            account_type=User.AccountType.INSTRUCTOR)
        cls.student = User.objects.create_user(
            'announcement-student', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.other_student = User.objects.create_user(
            'other-announcement-student', password='pw',
            account_type=User.AccountType.STUDENT)
        cls.session = SimulationSession.objects.create(
            name='Announcement Session', instructor=cls.instructor)
        SimulationRoleAssignment.objects.create(
            student=cls.student,
            assigned_by=cls.instructor,
            role=Role.PASSENGER_AIRLINE,
            activity_name=cls.session.name,
            session=cls.session,
        )

    def setUp(self):
        self.client.force_login(self.instructor)
        self.url = reverse('simulation:add_announcement')

    def post(self, **overrides):
        data = {
            'session': self.session.pk,
            'kind': 'ANNOUNCEMENT',
            'title': 'Schedule change',
            'message': 'Tomorrow starts at 8:00 AM.',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_instructor_posts_announcement_to_session_participants(self):
        response = self.post()

        self.assertEqual(
            response.url, f"{reverse('simulation:workspace')}#session-{self.session.pk}")
        notification = Notification.objects.get(recipient=self.student)
        self.assertEqual(notification.notification_type, Notification.Type.ANNOUNCEMENT)
        self.assertEqual(notification.title, 'Schedule change')
        self.assertEqual(notification.message, 'Tomorrow starts at 8:00 AM.')
        self.assertEqual(notification.session, self.session)
        self.assertEqual(notification.actor, self.instructor)
        self.assertEqual(notification.related_object, self.session)
        self.assertFalse(Notification.objects.filter(recipient=self.other_student).exists())
        self.assertTrue(ActivityLog.objects.filter(
            user=self.instructor, action='Posted announcement',
            session=self.session).exists())

    def test_student_opens_announcement_at_the_session(self):
        self.post()
        notification = Notification.objects.get(recipient=self.student)
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('notifications:open', args=[notification.pk]))

        self.assertEqual(
            response.url, f"{reverse('simulation:workspace')}#session-{self.session.pk}")
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_instructor_can_post_an_update(self):
        response = self.post(kind='UPDATE', title='Room moved')

        self.assertEqual(response.status_code, 302)
        notification = Notification.objects.get(recipient=self.student)
        self.assertEqual(notification.notification_type, Notification.Type.UPDATE)
        self.assertEqual(notification.title, 'Room moved')

    def test_non_instructor_cannot_post_an_announcement(self):
        self.client.force_login(self.student)

        response = self.post()

        self.assertRedirects(response, reverse('simulation:workspace'))
        self.assertFalse(Notification.objects.exists())

    def test_modal_request_returns_only_the_announcement_form(self):
        response = self.client.get(f'{self.url}?modal=1')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'simulation/_announcement_form.html')
        self.assertContains(response, 'data-announcement-modal-form')
        self.assertContains(response, f'{self.url}?modal=1')

    def test_modal_post_returns_a_redirect_instead_of_a_page(self):
        response = self.post(modal='1')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['redirect'],
            f"{reverse('simulation:workspace')}#session-{self.session.pk}")
        self.assertTrue(Notification.objects.filter(recipient=self.student).exists())

    def test_workspace_loads_the_announcement_modal_once(self):
        response = self.client.get(reverse('simulation:workspace'))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        self.assertEqual(
            len(re.findall(r'src="[^"]*simulation-announcement-modal[^"]*"', body)), 1)
        self.assertContains(response, 'data-announcement-modal-open')
        self.assertContains(response, 'data-announcement-dialog')

    def test_announcement_requires_a_title_and_message(self):
        response = self.post(title='', message='')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a title for the announcement.')
        self.assertContains(response, 'Enter the announcement message.')
        self.assertFalse(Notification.objects.exists())

    def test_announcement_requires_assigned_students(self):
        empty_session = SimulationSession.objects.create(
            name='Empty Session', instructor=self.instructor)

        response = self.post(session=empty_session.pk)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This session has no assigned students yet.')
        self.assertFalse(Notification.objects.exists())
