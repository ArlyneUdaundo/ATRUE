from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification
from notifications.services import notify
from establishments.models import Establishment
from travel_agencies.models import TravelAgencyRequest


class NotificationInboxTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='inbox-user', password='test-pass',
        )
        self.other_user = get_user_model().objects.create_user(
            username='other-inbox-user', password='test-pass',
        )
        self.client.force_login(self.user)

    def make_notification(self, recipient=None, notification_type=Notification.Type.GENERAL,
                          is_read=False, message='Test notification'):
        return Notification.objects.create(
            recipient=recipient or self.user,
            notification_type=notification_type,
            title='Test notification',
            message=message,
            is_read=is_read,
        )

    def test_all_view_includes_read_and_unread_from_all_categories(self):
        self.make_notification(notification_type=Notification.Type.ROLE_ASSIGNED)
        self.make_notification(notification_type=Notification.Type.PAYMENT_RECORDED,
                               is_read=True)
        self.make_notification(recipient=self.other_user)

        response = self.client.get(reverse('notifications:list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 2)
        self.assertEqual(response.context['unread_count_total'], 1)

    def test_unread_and_category_filters_are_applied_together(self):
        self.make_notification(notification_type=Notification.Type.ROLE_ASSIGNED)
        self.make_notification(notification_type=Notification.Type.ROLE_MODIFIED,
                               is_read=True)
        self.make_notification(notification_type=Notification.Type.PAYMENT_RECORDED)

        response = self.client.get(reverse('notifications:list'), {
            'status': 'unread', 'category': 'roles',
        })

        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertEqual(response.context['page_obj'].object_list[0].notification_type,
                         Notification.Type.ROLE_ASSIGNED)

    def test_history_is_paginated_without_dropping_old_notifications(self):
        for index in range(30):
            self.make_notification(message=f'Notification {index}')

        first_page = self.client.get(reverse('notifications:list'))
        second_page = self.client.get(reverse('notifications:list'), {'page': 2})

        self.assertEqual(first_page.context['page_obj'].paginator.count, 30)
        self.assertEqual(len(first_page.context['notifications']), 25)
        self.assertEqual(len(second_page.context['notifications']), 5)

    def test_travel_request_notification_opens_its_related_record(self):
        agency = Establishment.objects.create(
            name='Example Travel Agency', type=Establishment.Type.TRAVEL_AGENCY)
        travel_request = TravelAgencyRequest.objects.create(
            customer=self.user,
            establishment=agency,
            destination='Baguio',
        )
        notification = notify(
            self.user,
            Notification.Type.GENERAL,
            'Your travel request was received.',
            title='Travel request received',
            related_object=travel_request,
        )

        response = self.client.post(reverse('notifications:open', args=[notification.pk]))

        self.assertRedirects(
            response, reverse('notifications:travel_request', args=[notification.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertEqual(notification.related_object, travel_request)
        detail = self.client.get(response.url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Baguio')

    def test_deleted_related_record_falls_back_to_notification_history(self):
        agency = Establishment.objects.create(
            name='Example Travel Agency', type=Establishment.Type.TRAVEL_AGENCY)
        travel_request = TravelAgencyRequest.objects.create(
            customer=self.user,
            establishment=agency,
            destination='Baguio',
        )
        notification = notify(
            self.user, Notification.Type.GENERAL,
            'Your travel request was received.', related_object=travel_request,
        )
        travel_request.delete()

        response = self.client.post(reverse('notifications:open', args=[notification.pk]))

        self.assertRedirects(response, reverse('notifications:list'))
