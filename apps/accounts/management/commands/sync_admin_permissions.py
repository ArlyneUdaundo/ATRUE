"""Re-derive Django admin permissions from platform roles.

Staff accounts created outside ``seed_roles`` (or accounts whose role changed
since) can hold ``is_staff`` with no ``auth`` permissions, which makes every
``/admin/`` changelist answer 403. This walks every account and re-applies the
mapping in ``accounts.roles.admin_app_labels``.

Usage:
    python manage.py sync_admin_permissions            # report and apply
    python manage.py sync_admin_permissions --dry-run  # report only
    python manage.py sync_admin_permissions --username Admin_Eula
"""

from django.core.management.base import BaseCommand

from accounts.models import User
from accounts.roles import admin_permission_diff, sync_admin_permissions


class Command(BaseCommand):
    help = "Align Django admin permissions with each account's platform role."

    def add_arguments(self, parser):
        parser.add_argument('--username', help="Only sync this account.")
        parser.add_argument('--dry-run', action='store_true',
                            help="Show what would change without writing.")

    def handle(self, *args, **options):
        users = User.objects.all().order_by('username')
        if options['username']:
            users = users.filter(username=options['username'])
            if not users.exists():
                self.stderr.write(self.style.ERROR(
                    f"No account named {options['username']!r}."))
                return

        total_granted = total_revoked = touched = 0
        for user in users:
            if options['dry_run']:
                granted, revoked = admin_permission_diff(user)
                granted, revoked = len(granted), len(revoked)
            else:
                granted, revoked = sync_admin_permissions(user)

            if granted or revoked:
                touched += 1
                total_granted += granted
                total_revoked += revoked
                self.stdout.write(
                    f"  {user.username} ({user.get_account_type_display()}): "
                    f"+{granted} / -{revoked}")

        verb = 'would change' if options['dry_run'] else 'changed'
        self.stdout.write(self.style.SUCCESS(
            f"{touched} account(s) {verb}: {total_granted} granted, {total_revoked} revoked."))
