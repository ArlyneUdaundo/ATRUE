"""Copy existing local media to Supabase without changing DB paths."""

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Copy existing local media to Supabase without changing database paths.'

    def handle(self, *args, **options):
        if not settings.SUPABASE_STORAGE_CONFIGURED:
            raise CommandError(
                'Supabase Storage is not configured. Set all Supabase S3 '
                'credentials, endpoint, region, project URL, and bucket names first.'
            )
        root = Path(settings.MEDIA_ROOT)
        if not root.exists():
            raise CommandError(f'MEDIA_ROOT does not exist: {root}')
        public = storages['default']
        private = storages['profile_private']
        copied = skipped = 0
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            name = path.relative_to(root).as_posix()
            target = private if name.startswith('profile_pictures/') else public
            if target.exists(name):
                skipped += 1
                continue
            try:
                with path.open('rb') as source:
                    target.save(name, File(source, name=path.name))
            except Exception as exc:
                raise CommandError(f'Upload failed for {name}: {exc}') from exc
            copied += 1
        self.stdout.write(self.style.SUCCESS(
            f'Media migration finished: {copied} copied, {skipped} already present.'
        ))
