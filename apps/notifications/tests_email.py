import hashlib
import io
import json
import re
import smtplib
import urllib.error
from email import policy
from email.parser import BytesParser
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from activities.models import Activity, ActivityProvider, Booking
from notifications.email_service import queue_booking_confirmation
from notifications.email_service import _brevo_send, check_brevo_connection
from notifications.models import EmailDelivery, PasswordResetToken


class MockSMTPServer:
    instances = []

    def __init__(self, host, port, *, local_hostname=None, timeout=None, **kwargs):
        self.host = host
        self.port = port
        self.local_hostname = local_hostname
        self.timeout = timeout
        self.starttls_context = None
        self.auth = None
        self.sender = None
        self.recipients = None
        self.raw_message = None
        self.__class__.instances.append(self)

    def starttls(self, context=None):
        self.starttls_context = context

    def login(self, user, password):
        self.auth = (user, password)

    def sendmail(self, sender, recipients, message):
        self.sender = sender
        self.recipients = recipients
        self.raw_message = message
        return {}

    def quit(self):
        return 221, b'bye'


class RejectingMockSMTPServer(MockSMTPServer):
    def login(self, user, password):
        self.auth = (user, password)
        raise smtplib.SMTPAuthenticationError(535, b'private account detail')


@override_settings(APP_BASE_URL='https://example.test', BREVO_API_KEY='test-key',
                   BREVO_SENDER_EMAIL='noreply@example.test', BREVO_SENDER_NAME='ATRUE')
class BrevoEmailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='emailguest', email='guest@example.test', password='InitialPass!879')

    @patch('notifications.email_service._brevo_send', return_value='provider-message-1')
    @patch('notifications.email_service._build_ticket_pdf', return_value={
        'name': 'booking-test.pdf', 'content': b'%PDF-test',
    })
    def test_booking_email_is_saved_once_and_only_after_commit(self, build_pdf, send):
        provider = ActivityProvider.objects.create(name='Provider', location='Manila')
        activity = Activity.objects.create(provider=provider, name='Kayak', fee='100.00')
        booking = Booking.objects.create(customer=self.user, activity=activity,
                                         schedule_date=timezone.localdate(), participant_count=2,
                                         status='CONFIRMED')
        with self.captureOnCommitCallbacks(execute=True):
            queue_booking_confirmation(booking)
            queue_booking_confirmation(booking)
        self.assertEqual(EmailDelivery.objects.count(), 1)
        row = EmailDelivery.objects.get()
        self.assertEqual(row.status, EmailDelivery.Status.SENT)
        self.assertEqual(row.provider_message_id, 'provider-message-1')
        self.assertEqual(send.call_count, 1)
        self.assertIn('Payment pending', send.call_args.kwargs['text'])
        attachment = send.call_args.kwargs['attachments'][0]
        self.assertTrue(attachment['name'].endswith('.pdf'))
        self.assertTrue(attachment['content'].startswith(b'%PDF'))

    @patch('notifications.email_service._brevo_send', side_effect=OSError('offline'))
    def test_brevo_failure_does_not_remove_booking_and_is_recorded(self, send):
        provider = ActivityProvider.objects.create(name='Provider', location='Manila')
        activity = Activity.objects.create(provider=provider, name='Hike', fee='100.00')
        booking = Booking.objects.create(customer=self.user, activity=activity,
                                         schedule_date=timezone.localdate(), status='CONFIRMED')
        with self.captureOnCommitCallbacks(execute=True):
            queue_booking_confirmation(booking)
        booking.refresh_from_db()
        self.assertTrue(booking.pk)
        self.assertEqual(EmailDelivery.objects.get().status, EmailDelivery.Status.FAILED)

    @patch('notifications.email_service._brevo_send', return_value='reset-message')
    def test_forgot_password_response_is_generic_and_password_reset_is_single_use(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            known = self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                                     HTTP_X_ATRUE_RESET_MODAL='1')
        unknown = self.client.post(reverse('accounts:forgot_password'), {'email': 'missing@example.test'},
                                   HTTP_X_ATRUE_RESET_MODAL='1')
        self.assertEqual(known.json(), unknown.json())
        self.assertIn('If an account matches', known.json()['message'])
        self.assertIn('may be sent', known.json()['message'])
        self.assertNotIn('will be sent', known.json()['message'])
        self.assertEqual(send.call_count, 1)
        reset = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(reset.email_status, 'SENT')
        self.assertEqual(reset.provider_message_id, 'reset-message')
        html = send.call_args.kwargs['html']
        raw = re.search(r'reset-password/\d+/#([^"&]+)', html).group(1)
        self.assertEqual(reset.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        verify = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'action': 'verify', 'token': raw,
        })
        self.assertEqual(verify.status_code, 200)
        self.assertTrue(verify.json()['ok'])
        response = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'token': raw, 'new_password1': 'BetterPassword!4682',
            'new_password2': 'BetterPassword!4682',
        })
        self.assertContains(response, 'Your password has been changed successfully')
        logged_in = self.client.post(reverse('accounts:login'), {
            'username': self.user.email, 'password': 'BetterPassword!4682',
        }, HTTP_X_ATRUE_LOGIN_MODAL='1')
        self.assertEqual(logged_in.status_code, 200)
        self.assertTrue(logged_in.json()['ok'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BetterPassword!4682'))
        reused = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'token': raw, 'new_password1': 'AgainPassword!4682',
            'new_password2': 'AgainPassword!4682',
        })
        self.assertContains(reused, 'invalid, expired, or already used', status_code=400)

    @patch('notifications.email_service._brevo_send', side_effect=RuntimeError('BREVO_HTTP_401_UNAUTHORIZED'))
    def test_reset_api_failure_is_recorded_and_never_reported_as_sent(self, send):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            response = self.client.post(
                reverse('accounts:forgot_password'), {'email': self.user.email},
                HTTP_X_ATRUE_RESET_MODAL='1',
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertNotIn('will be sent', response.json()['message'])
        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'FAILED')
        self.assertEqual(row.provider_message_id, '')
        self.assertEqual(send.call_count, 1)
        self.assertIn('BREVO_HTTP_401_UNAUTHORIZED', captured.output[0])
        self.assertNotIn(self.user.email, captured.output[0])

    @patch('notifications.email_service._brevo_send')
    def test_invalid_email_does_not_call_brevo(self, send):
        response = self.client.post(
            reverse('accounts:forgot_password'), {'email': 'not-an-email'},
            HTTP_X_ATRUE_RESET_MODAL='1',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertFalse(PasswordResetToken.objects.filter(user=self.user).exists())
        send.assert_not_called()

    @patch('notifications.email_service._brevo_send')
    def test_unregistered_email_uses_generic_response_without_sending(self, send):
        response = self.client.post(
            reverse('accounts:forgot_password'), {'email': 'unknown@example.test'},
            HTTP_X_ATRUE_RESET_MODAL='1',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertIn('If an account matches', response.json()['message'])
        self.assertEqual(PasswordResetToken.objects.count(), 0)
        send.assert_not_called()

    def test_forgot_password_direct_route_redirects_to_shared_modal(self):
        response = self.client.get(reverse('accounts:forgot_password'))
        self.assertRedirects(response, '/?reset=1')

    @override_settings(APP_BASE_URL='', RENDER_EXTERNAL_URL='https://current-service.onrender.com')
    @patch('notifications.email_service._brevo_send', return_value='reset-message')
    def test_password_reset_link_uses_render_url_when_base_url_is_not_set(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        self.assertIn(
            'https://current-service.onrender.com/accounts/reset-password/',
            send.call_args.kwargs['html'],
        )

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
        verify = self.client.post(reverse('accounts:reset_password', args=[self.user.pk]), {
            'action': 'verify', 'token': 'old',
        })
        self.assertEqual(verify.status_code, 400)
        self.assertFalse(verify.json()['ok'])

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
        payload = json.loads(request.data.decode())
        self.assertIn('htmlContent', payload)
        self.assertNotIn('textContent', payload)
        self.assertIn('Idempotency-Key', payload['headers'])

    @override_settings(BREVO_API_KEY='', BREVO_SENDER_EMAIL='', BREVO_SENDER_NAME='')
    def test_missing_brevo_configuration_is_handled_without_request(self):
        with self.assertRaisesRegex(RuntimeError, 'EMAIL_CONFIGURATION_MISSING'):
            _brevo_send(to_email='guest@example.test', to_name='', subject='Hello',
                        html='Hi', text='Hi', idempotency_key='test')

    @override_settings(BREVO_SENDER_EMAIL='')
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_missing_sender_configuration_is_handled_without_request(self, urlopen):
        with self.assertRaisesRegex(RuntimeError, 'EMAIL_CONFIGURATION_MISSING'):
            _brevo_send(to_email='guest@example.test', to_name='', subject='Hello',
                        html='Hi', text='Hi', idempotency_key='test-missing-sender')
        urlopen.assert_not_called()

    @patch('notifications.email_service.urllib.request.urlopen', side_effect=TimeoutError())
    def test_brevo_timeout_is_reported_as_a_safe_failure(self, urlopen):
        with self.assertRaisesRegex(RuntimeError, 'BREVO_TIMEOUT') as raised:
            _brevo_send(to_email='guest@example.test', to_name='', subject='Hello',
                        html='Hi', text='Hi', idempotency_key='test-timeout')
        self.assertEqual(str(raised.exception), 'BREVO_TIMEOUT')
        urlopen.assert_called_once()

    @patch('notifications.email_service.urllib.request.urlopen')
    def test_brevo_http_error_exposes_safe_status_and_provider_code(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            'https://api.brevo.com/v3/smtp/email', 401, 'Unauthorized', {},
            io.BytesIO(b'{"code":"unauthorized","message":"sensitive detail"}'),
        )
        with self.assertRaisesRegex(RuntimeError, 'BREVO_HTTP_401_UNAUTHORIZED') as raised:
            _brevo_send(to_email='guest@example.test', to_name='', subject='Hello',
                        html='Hi', text='Hi', idempotency_key='test-http-error')
        self.assertNotIn('sensitive detail', str(raised.exception))

    @patch('notifications.email_service.urllib.request.urlopen')
    def test_brevo_check_confirms_configured_sender_is_active(self, urlopen):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = json.dumps({
            'senders': [{'email': 'noreply@example.test', 'active': True}],
        }).encode()
        urlopen.return_value = response

        self.assertTrue(check_brevo_connection())
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.brevo.com/v3/senders')
        self.assertEqual(request.get_header('Api-key'), 'test-key')

    @patch('notifications.email_service.urllib.request.urlopen')
    def test_brevo_check_rejects_unverified_sender(self, urlopen):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = json.dumps({
            'senders': [{'email': 'noreply@example.test', 'active': False}],
        }).encode()
        urlopen.return_value = response

        with self.assertRaisesRegex(RuntimeError, 'BREVO_SENDER_NOT_VERIFIED'):
            check_brevo_connection()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='resend', RESEND_API_KEY='test-resend-key',
        RESEND_SENDER_EMAIL='no-reply@example.test',
        RESEND_SENDER_NAME='ATRUE Simulation Portal',
    )
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_resend_reset_uses_official_api_and_records_message_id(self, urlopen):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id":"resend-message-123"}'
        urlopen.return_value = response

        self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                         HTTP_X_ATRUE_RESET_MODAL='1')

        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'SENT')
        self.assertEqual(row.provider_message_id, 'resend-message-123')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.resend.com/emails')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-resend-key')
        payload = json.loads(request.data.decode())
        self.assertEqual(payload['from'], 'ATRUE Simulation Portal <no-reply@example.test>')
        self.assertEqual(payload['to'], [self.user.email])
        self.assertIn(f'/accounts/reset-password/{self.user.pk}/#', payload['html'])
        self.assertTrue(request.get_header('Idempotency-key'))

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='resend', RESEND_API_KEY='test-resend-key',
        RESEND_SENDER_EMAIL='no-reply@example.test', RESEND_SENDER_NAME='ATRUE',
    )
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_resend_invalid_api_key_is_recorded_without_sensitive_response(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            'https://api.resend.com/emails', 401, 'Unauthorized', {},
            io.BytesIO(b'{"name":"invalid_api_key","message":"sensitive provider detail"}'),
        )
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'FAILED')
        self.assertEqual(row.provider_message_id, '')
        self.assertIn('RESEND_HTTP_401_INVALID_API_KEY', captured.output[0])
        self.assertNotIn('sensitive provider detail', captured.output[0])
        self.assertNotIn(self.user.email, captured.output[0])

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='resend', RESEND_API_KEY='',
        RESEND_SENDER_EMAIL='no-reply@example.test', RESEND_SENDER_NAME='ATRUE',
    )
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_resend_missing_api_key_fails_closed_without_sending(self, urlopen):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        self.assertEqual(PasswordResetToken.objects.get(user=self.user).email_status, 'FAILED')
        self.assertIn('RESEND_CONFIGURATION_MISSING', captured.output[0])
        urlopen.assert_not_called()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='resend', RESEND_API_KEY='test-resend-key',
        RESEND_SENDER_EMAIL='not-an-email', RESEND_SENDER_NAME='ATRUE',
    )
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_resend_invalid_sender_fails_closed_without_sending(self, urlopen):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        self.assertEqual(PasswordResetToken.objects.get(user=self.user).email_status, 'FAILED')
        self.assertIn('RESEND_SENDER_INVALID', captured.output[0])
        urlopen.assert_not_called()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='resend', RESEND_API_KEY='test-resend-key',
        RESEND_SENDER_EMAIL='no-reply@example.test', RESEND_SENDER_NAME='ATRUE',
    )
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_resend_rejects_unverified_domain_without_leaking_provider_detail(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            'https://api.resend.com/emails', 403, 'Forbidden', {},
            io.BytesIO(b'{"name":"domain_not_verified","message":"verify domain secret detail"}'),
        )
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        self.assertEqual(PasswordResetToken.objects.get(user=self.user).email_status, 'FAILED')
        self.assertIn('RESEND_HTTP_403_DOMAIN_NOT_VERIFIED', captured.output[0])
        self.assertNotIn('verify domain secret detail', captured.output[0])

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='disabled', RESEND_API_KEY='test-resend-key',
        RESEND_SENDER_EMAIL='no-reply@example.test', RESEND_SENDER_NAME='ATRUE',
    )
    @patch('notifications.email_service.urllib.request.urlopen')
    def test_disabled_reset_provider_fails_without_fallback(self, urlopen):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        self.assertEqual(PasswordResetToken.objects.get(user=self.user).email_status, 'FAILED')
        self.assertIn('PASSWORD_RESET_PROVIDER_UNSUPPORTED', captured.output[0])
        urlopen.assert_not_called()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='resend', RESEND_API_KEY='test-resend-key',
        RESEND_SENDER_EMAIL='no-reply@example.test', RESEND_SENDER_NAME='ATRUE',
    )
    @patch('notifications.email_service.urllib.request.urlopen', side_effect=TimeoutError())
    def test_resend_timeout_is_logged_as_safe_failure(self, urlopen):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(reverse('accounts:forgot_password'), {'email': self.user.email},
                             HTTP_X_ATRUE_RESET_MODAL='1')

        self.assertEqual(PasswordResetToken.objects.get(user=self.user).email_status, 'FAILED')
        self.assertIn('RESEND_TIMEOUT', captured.output[0])
        urlopen.assert_called_once()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='gmail_smtp',
        GMAIL_SMTP_USER='reset-owner@gmail.com',
        GMAIL_SMTP_APP_PASSWORD='abcd efgh ijkl mnop',
        GMAIL_SENDER_NAME='ATRUE Reset',
    )
    def test_gmail_smtp_reset_uses_the_authenticated_gmail_sender(self):
        MockSMTPServer.instances.clear()
        with patch(
            'django.core.mail.backends.smtp.EmailBackend.connection_class',
            MockSMTPServer,
        ):
            self.client.post(
                reverse('accounts:forgot_password'), {'email': self.user.email},
                HTTP_X_ATRUE_RESET_MODAL='1',
            )

        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'SENT')
        self.assertEqual(row.provider_message_id, '')
        smtp = MockSMTPServer.instances[-1]
        self.assertEqual((smtp.host, smtp.port, smtp.timeout), ('smtp.gmail.com', 587, 20))
        self.assertIsNotNone(smtp.starttls_context)
        self.assertEqual(smtp.auth, ('reset-owner@gmail.com', 'abcdefghijklmnop'))
        self.assertEqual(smtp.sender, 'ATRUE Reset <reset-owner@gmail.com>')
        self.assertEqual(smtp.recipients, [self.user.email])
        parsed = BytesParser(policy=policy.default).parsebytes(smtp.raw_message)
        self.assertEqual(parsed['From'].addresses[0].addr_spec, 'reset-owner@gmail.com')
        self.assertEqual(parsed['To'].addresses[0].addr_spec, self.user.email)
        html = next(
            part.get_content() for part in parsed.walk()
            if part.get_content_type() == 'text/html'
        )
        self.assertIn(
            f'/accounts/reset-password/{self.user.pk}/#',
            html,
        )

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='gmail_smtp',
        GMAIL_SMTP_USER='reset-owner@gmail.com',
        GMAIL_SMTP_APP_PASSWORD='',
        GMAIL_SENDER_NAME='ATRUE Reset',
    )
    @patch('django.core.mail.get_connection')
    def test_gmail_smtp_reset_fails_closed_without_app_password(self, get_connection):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(
                reverse('accounts:forgot_password'), {'email': self.user.email},
                HTTP_X_ATRUE_RESET_MODAL='1',
            )

        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'FAILED')
        self.assertEqual(row.provider_message_id, '')
        self.assertIn('GMAIL_SMTP_CONFIGURATION_MISSING', captured.output[0])
        get_connection.assert_not_called()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='gmail_smtp',
        GMAIL_SMTP_USER='unverified@example.test',
        GMAIL_SMTP_APP_PASSWORD='app-password',
        GMAIL_SENDER_NAME='ATRUE Reset',
    )
    @patch('django.core.mail.get_connection')
    def test_gmail_smtp_reset_rejects_non_gmail_from_addresses(self, get_connection):
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            self.client.post(
                reverse('accounts:forgot_password'), {'email': self.user.email},
                HTTP_X_ATRUE_RESET_MODAL='1',
            )

        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'FAILED')
        self.assertEqual(row.provider_message_id, '')
        self.assertIn('GMAIL_SMTP_SENDER_NOT_GMAIL', captured.output[0])
        get_connection.assert_not_called()

    @override_settings(
        PASSWORD_RESET_EMAIL_PROVIDER='gmail_smtp',
        GMAIL_SMTP_USER='reset-owner@gmail.com',
        GMAIL_SMTP_APP_PASSWORD='app-password',
        GMAIL_SENDER_NAME='ATRUE Reset',
    )
    def test_gmail_smtp_auth_failure_is_sanitized(self):
        RejectingMockSMTPServer.instances.clear()
        with self.assertLogs('notifications.email_service', level='WARNING') as captured:
            with patch(
                'django.core.mail.backends.smtp.EmailBackend.connection_class',
                RejectingMockSMTPServer,
            ):
                self.client.post(
                    reverse('accounts:forgot_password'), {'email': self.user.email},
                    HTTP_X_ATRUE_RESET_MODAL='1',
                )

        row = PasswordResetToken.objects.get(user=self.user)
        self.assertEqual(row.email_status, 'FAILED')
        self.assertEqual(row.provider_message_id, '')
        self.assertIn('GMAIL_SMTP_AUTH_FAILED', captured.output[0])
        self.assertNotIn('private account detail', captured.output[0])
        self.assertEqual(
            RejectingMockSMTPServer.instances[-1].auth,
            ('reset-owner@gmail.com', 'app-password'),
        )
