from django.core.management.base import BaseCommand, CommandError

from notifications.email_service import check_brevo_connection


class Command(BaseCommand):
    help = 'Check Brevo API credentials without sending an email.'

    def handle(self, *args, **options):
        try:
            check_brevo_connection()
        except RuntimeError as exc:
            reasons = {
                'EMAIL_CONFIGURATION_MISSING': (
                    'Set BREVO_API_KEY, BREVO_SENDER_EMAIL, and BREVO_SENDER_NAME.'
                ),
                'BREVO_CONNECTION_FAILED': (
                    'Could not reach api.brevo.com from this environment.'
                ),
            }
            message = reasons.get(str(exc), f'Brevo API check failed: {exc}')
            raise CommandError(message) from exc
        self.stdout.write(self.style.SUCCESS(
            'Brevo API credentials are valid. Sender configuration is present; '
            'confirm the sender or domain is verified in Brevo.'
        ))
