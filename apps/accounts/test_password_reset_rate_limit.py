from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from notifications.models import PasswordResetRequest


@override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
class PasswordResetRateLimitTests(TestCase):
    def _create_user(self, suffix):
        return get_user_model().objects.create_user(
            username=f'reset{suffix}',
            email=f'reset{suffix}@example.test',
            password='InitialPass!879',
        )

    def _post(self, email, client_ip, spoofed_xff='198.51.100.250'):
        return self.client.post(
            reverse('accounts:forgot_password'), {'email': email},
            HTTP_X_ATRUE_RESET_MODAL='1',
            HTTP_CF_CONNECTING_IP=client_ip,
            HTTP_X_FORWARDED_FOR=spoofed_xff,
        )

    @patch('notifications.email_service.deliver_password_reset')
    def test_render_proxy_ip_does_not_rate_limit_distinct_clients(self, deliver):
        with self.assertLogs('accounts.views', level='WARNING') as captured:
            for number in range(1, 22):
                response = self._post(
                    f'unknown{number}@example.test', f'203.0.113.{number}')
                self.assertEqual(response.status_code, 200)

        self.assertEqual(PasswordResetRequest.objects.count(), 21)
        self.assertFalse(any('was rate-limited' in line for line in captured.output))
        deliver.assert_not_called()

    @patch('notifications.email_service.deliver_password_reset')
    def test_email_limit_remains_five_per_hour_and_logs_only_limit_reason(self, deliver):
        user = self._create_user('same')
        with self.assertLogs('accounts.views', level='WARNING') as captured:
            for number in range(1, 7):
                response = self._post(user.email, f'203.0.113.{number}')
                self.assertEqual(response.status_code, 200)

        self.assertEqual(deliver.call_count, 5)
        self.assertIn('email_limit_hit=True ip_limit_hit=False', captured.output[-1])
        self.assertNotIn(user.email, captured.output[-1])

    @patch('notifications.email_service.deliver_password_reset')
    def test_ip_limit_remains_twenty_per_hour(self, deliver):
        with self.assertLogs('accounts.views', level='WARNING') as captured:
            for number in range(1, 22):
                response = self._post(
                    f'unknown{number}@example.test', '203.0.113.42')
                self.assertEqual(response.status_code, 200)

        limited = [line for line in captured.output if 'was rate-limited' in line]
        self.assertEqual(len(limited), 1)
        self.assertIn('email_limit_hit=False ip_limit_hit=True', limited[0])
        deliver.assert_not_called()
