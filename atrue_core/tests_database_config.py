import json
import os
import subprocess
import sys

from django.test import SimpleTestCase


class RenderDatabaseConfigTests(SimpleTestCase):
    def _probe_settings(self, database_url):
        env = os.environ.copy()
        for key in (
            "DATABASE_URL", "DB_ENGINE", "DB_NAME", "DB_USER", "DB_PASSWORD",
            "DB_HOST", "DB_PORT", "RENDER",
        ):
            env.pop(key, None)
        env.update({
            "DEBUG": "False",
            "RENDER": "true",
            "SECRET_KEY": "database-config-test-secret",
        })
        if database_url is not None:
            env["DATABASE_URL"] = database_url

        script = (
            "import json; from atrue_core import settings; "
            "db=settings.DATABASES['default']; "
            "print(json.dumps({'engine': db['ENGINE'], 'host': db.get('HOST'), "
            "'port': db.get('PORT'), 'sslmode': db.get('OPTIONS', {}).get('sslmode')}))"
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_render_requires_database_url_instead_of_localhost_fallback(self):
        result = self._probe_settings(None)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL must be set on Render", result.stderr)
        self.assertNotIn("localhost", result.stderr)

    def test_render_parses_internal_postgres_url_with_required_tls(self):
        result = self._probe_settings(
            "postgres://test-user:test-password@db.internal:5432/atrue"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(config, {
            "engine": "django.db.backends.postgresql",
            "host": "db.internal",
            "port": 5432,
            "sslmode": "require",
        })
