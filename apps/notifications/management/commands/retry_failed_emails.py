from django.core.management.base import BaseCommand

from notifications.email_service import _send_and_record
from notifications.models import EmailDelivery


class Command(BaseCommand):
    help = 'Retry failed booking confirmation emails through Brevo.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        limit = max(1, min(options['limit'], 1000))
        ids = list(EmailDelivery.objects.filter(
            status=EmailDelivery.Status.FAILED,
            event='BOOKING_CONFIRMATION',
        ).order_by('created_at').values_list('pk', flat=True)[:limit])
        for delivery_id in ids:
            _send_and_record(delivery_id)
        self.stdout.write(self.style.SUCCESS(f'Retried {len(ids)} failed booking email(s).'))
