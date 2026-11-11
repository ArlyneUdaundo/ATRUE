"""Temporary read-only page audit. Not part of the project."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'atrue_core.settings')
django.setup()

from django.test import Client
from django.urls import get_resolver, URLPattern, URLResolver
from accounts.models import User

CONV = ('<', '>')


def walk(patterns, prefix=''):
    out = []
    for p in patterns:
        if isinstance(p, URLPattern):
            route = p.pattern._route if hasattr(p.pattern, '_route') else str(p.pattern)
            if any(c in route for c in CONV):
                continue
            out.append((prefix + route, getattr(p, 'name', None)))
        elif isinstance(p, URLResolver):
            new = prefix + str(p.pattern)
            out.extend(walk(p.url_patterns, new))
    return out


paths = walk(get_resolver().url_patterns)
by_user = {
    'anon': None,
    'student': 1,
    'system_admin': 7,
    'frontdesk': 11,
    'instructor': 2,
}
results = {}
for label, uid in by_user.items():
    client = Client(HTTP_HOST='localhost')
    if uid:
        client.force_login(User.objects.get(pk=uid))
    for path, name in paths:
        if path.startswith('admin/') or path.startswith('media/') or path.startswith('static/'):
            continue
        try:
            r = client.get('/' + path.lstrip('/'), follow=True)
            results[(label, path)] = (r.status_code, len(r.content))
        except Exception as exc:
            results[(label, path)] = ('EXC', repr(exc)[:200])

for (label, path), val in sorted(results.items()):
    if val[0] != 200:
        print(label, path, val)
print('TOTAL', len(results), 'NON200', sum(1 for v in results.values() if v[0] != 200))
