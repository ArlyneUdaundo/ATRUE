import hashlib
import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from activities.models import Activity, ActivityProvider, Booking
from notifications.email_service import queue_booking_confirmation
from notifications.email_service import _brevo_send
from notifications.models import EmailDelivery, PasswordResetToken


@override_settings(APP_BASE_URL='https://example.test', BREVO_API_KEY='test-key',
                   BREVO_SENDER_EMAIL='noreply@example.test', BREVO_SENDER_NAME='ATRUE')
class BrevoEmailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='emailguest', email='guest@example.test', password='InitialPass!879')

    @patch('notifications.email_service._brevo_send', return_value='provider-message-1')
    def test_booking_email_is_saved_once_and_only_after_commit(self, send):
        provider = ActivityProvider.objects.create(name='Provider', location='Manila')
        activity = Activity.objects.create(provider=provider, name='Kayak', fee='100.00')
        booking = Booking.objects.create(customer=self.user, activity=activity,
                                         schedule_date=timezone.localdate(), participant_count=2)
        with self.captureOnCommitCallbacks(execute=True):
            queue_booking_confirmation(booking)
            queue_booking_confirmation(booking)
        self.assertEqual(EmailDelivery.objects.count(), 1)
        row = EmailDelivery.objects.get()
        self.assertEqual(row.status, EmailDelivery.Status.SENT)
        self.assertEqual(row.provider_message_id, 'provider-message-1')
        self.assertEqual(send.call_count, 1)
        self.assertIn('Payment pending', send.call_args.kwargs['text'])

    @patch('notifications.email_service._brevo_send', side_effect=OSError('offline'))
    def test_brevo_failure_does_not_remove_booking_and_is_recorded(self, send):
        provider = ActivityProvider.objects.create(name='Provider', location='Manila')
        activity = Activity.objects.create(provider=provider, name='Hike', fee='100.00')
        booking = Booking.objects.create(customer=self.user, activity=activity,
                                         schedule_date=timezone.localdate())
        with self.captureOnCommitCallbacks(execute=True):
            queue_booking_confirmation(booking)
        booking.refresh_from_db()
        self.assertTrue(booking.pk)
        self.assertEqual(EmailDelivery.objects.get().status, EmailDelivery.Status.FAILED)

    @patch('notifications.email_service._brevo_send', return_value='reset-message')
    def test_forgot_password_response_is_generic_and_password_reset_is_single_use(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            known = self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email})
        unknown = self.client.post(reverse('accounts:forgot_password'), {'email': 'missing@example.test'})
        self.assertContains(known, 'If an account matches', status_code=200)
        self.assertContains(unknown, 'If an account matches', status_code=200)
        reset = PasswordResetToken.objects.get(user=self.user)
        html = send.call_args.kwargs['html']
        raw = re.search(r'reset-password/\d+/#([^"&]+)', html).group(1)
        self.assertEqual(reset.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        response = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'token': raw, 'new_password1': 'BetterPassword!4682',
            'new_password2': 'BetterPassword!4682',
        })
        self.assertContains(response, 'Your password was changed')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BetterPassword!4682'))
        reused = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'token': raw, 'new_password1': 'AgainPassword!4682',
            'new_password2': 'AgainPassword!4682',
        })
        self.assertContains(reused, 'invalid, expired, or already used', status_code=400)

    def test_expired_and_invalid_reset_tokens_are_rejected(self):
        expired = PasswordResetToken.objects.create(
            user=self.user, token_hash=hashlib.sha256(b'old').hexdigest(),
            expires_at=timezone.now()-timedelta(minutes=1))
        response = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'token': 'old', 'new_password1': 'BetterPassword!4682',
            'new_password2': 'BetterPassword!4682',
        })
        self.assertContains(response, 'invalid, expired, or already used', status_code=400)
        self.assertIsNone(expired.used_at)

    @patch('notifications.email_service.urllib.request.urlopen')
    def test_brevo_request_uses_server_key_and_idempotency_uuid(self, urlopen):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"messageId":"mail-123"}'
        urlopen.return_value = response
        self.assertEqual(_brevo_send(
            to_email='guest@example.test', to_name='Guest', subject='Hello', html='<b>Hi</b>',
            text='Hi', idempotency_key='booking-confirmation:activities.booking:1'), 'mail-123')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(request.get_header('Api-key'), 'test-key')
        self.assertIn('Idempotency-Key', request.data.decode())

    @override_settings(BREVO_API_KEY='', BREVO_SENDER_EMAIL='', BREVO_SENDER_NAME='')
    def test_missing_brevo_configuration_is_handled_without_request(self):
        with self.assertRaisesRegex(RuntimeError, 'EMAIL_CONFIGURATION_MISSING'):
            _brevo_send(to_email='guest@example.test', to_name='', subject='Hello',
                        html='Hi', text='Hi', idempotency_key='test')
