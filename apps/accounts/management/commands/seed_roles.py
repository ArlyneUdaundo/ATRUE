"""Create one demo account per user role so every role dashboard can be tested.

Usage:
    # Set ATRUE_DEMO_PASSWORD in the environment first.
    python manage.py seed_roles
    python manage.py seed_roles --password <private-demo-password>
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from accounts.roles import ROLE_DEFS

ALL_TYPES = [
    ('STUDENT', 'Student'),
    ('INSTRUCTOR', 'Instructor/Trainer'),
    ('ADMIN', 'Administrator'),
    ('SYSTEM_ADMIN', 'System Administrator'),
] + [(key, ROLE_DEFS[key]['label']) for key in ROLE_DEFS if key != 'SYSTEM_ADMIN']


class Command(BaseCommand):
    help = "Seed one demo account per user role for testing role dashboards."

    def add_arguments(self, parser):
        parser.add_argument('--password', default=os.getenv('ATRUE_DEMO_PASSWORD'),
                            help="Password for new demo accounts (or set ATRUE_DEMO_PASSWORD).")

    @transaction.atomic
    def handle(self, *args, **options):
        password = options['password']
        if not password:
            raise CommandError('Set ATRUE_DEMO_PASSWORD or pass --password to create demo accounts.')
        created = []
        aligned = []
        for value, label in ALL_TYPES:
            username = value.lower()
            defaults = {
                'email': f'{username}@atrue.edu.ph',
                'first_name': label,
                'last_name': 'Demo',
                'account_type': value,
                'status': User.Status.ACTIVE,
                'is_staff': value == 'SYSTEM_ADMIN',
                'is_superuser': value == 'SYSTEM_ADMIN',
            }
            user, is_new = User.objects.get_or_create(username=username, defaults=defaults)
            if is_new:
                user.set_password(password)
                user.save()
                created.append(username)
            elif user.account_type != value:
                user.account_type = value
                user.save(update_fields=['account_type'])
                aligned.append(username)
            elif value == 'SYSTEM_ADMIN' and (not user.is_staff or not user.is_superuser):
                user.is_staff = True
                user.is_superuser = True
                user.save(update_fields=['is_staff', 'is_superuser'])
                aligned.append(username)

        self.stdout.write(self.style.SUCCESS(
            f"Created {len(created)} demo account(s): {', '.join(created) or 'none'}"))
        if aligned:
            self.stdout.write(self.style.WARNING(
                f"Re-aligned {len(aligned)} existing account(s): {', '.join(aligned)}"))
        self.stdout.write("")
        self.stdout.write("Demo account usernames:")
        for value, label in ALL_TYPES:
            self.stdout.write(f"  {value.lower():24} -> {label}")
