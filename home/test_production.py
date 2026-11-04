import os
import subprocess
import sys

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings


class ErrorPageTests(TestCase):
    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_404_uses_custom_template(self):
        response = self.client.get('/noticia/no-existe/')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, 'Página no encontrada', status_code=404)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
    def test_404_keeps_site_navigation(self):
        response = self.client.get('/nada/')
        self.assertContains(response, 'href="/"', status_code=404)


class ServerErrorTemplateTests(SimpleTestCase):
    def test_500_renders_without_request_or_context(self):
        html = render_to_string('500.html')
        self.assertIn('Error del servidor', html)
        self.assertNotIn('{%', html)

    def test_500_is_self_contained(self):
        # No extends/static/url tags: those can hit the database or a missing manifest.
        from django.template.loader import get_template
        source = get_template('500.html').template.source
        for tag in ('{% extends', '{% static', '{% url', '{% include'):
            self.assertNotIn(tag, source)


class SettingsDefaultsTests(SimpleTestCase):
    def run_settings(self, env_overrides, expression):
        env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        env.update({'DJANGO_SETTINGS_MODULE': 'canaco.settings', 'PYTHONDONTWRITEBYTECODE': '1'})
        env.update(env_overrides)
        code = f'from django.conf import settings; print({expression})'
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_debug_defaults_to_false(self):
        self.assertEqual(self.run_settings({'DJANGO_SECRET_KEY': 'x' * 60}, 'settings.DEBUG'), 'False')

    def test_debug_enabled_by_env(self):
        self.assertEqual(self.run_settings({'DJANGO_DEBUG': '1'}, 'settings.DEBUG'), 'True')

    def test_production_without_secret_key_refuses_to_start(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        env.update({'DJANGO_SETTINGS_MODULE': 'canaco.settings', 'PYTHONDONTWRITEBYTECODE': '1'})
        result = subprocess.run(
            [sys.executable, '-c', 'from django.conf import settings; settings.DEBUG'],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', result.stderr)

    def test_security_headers_in_production(self):
        env = {'DJANGO_SECRET_KEY': 'x' * 60}
        out = self.run_settings(env, (
            '(settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE, settings.X_FRAME_OPTIONS, '
            'settings.SECURE_REFERRER_POLICY, settings.SECURE_CONTENT_TYPE_NOSNIFF, '
            'settings.SECURE_PROXY_SSL_HEADER, settings.SECURE_SSL_REDIRECT, settings.SECURE_HSTS_SECONDS)'
        ))
        self.assertEqual(
            out,
            "(True, True, 'DENY', 'same-origin', True, ('HTTP_X_FORWARDED_PROTO', 'https'), False, 0)",
        )

    def test_security_headers_are_env_driven(self):
        out = self.run_settings(
            {
                'DJANGO_SECRET_KEY': 'x' * 60,
                'DJANGO_SECURE_SSL_REDIRECT': 'true',
                'DJANGO_SECURE_HSTS_SECONDS': '3600',
                'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://a.example,https://b.example',
            },
            'settings.SECURE_SSL_REDIRECT, settings.SECURE_HSTS_SECONDS, settings.CSRF_TRUSTED_ORIGINS',
        )
        self.assertEqual(out, "True 3600 ['https://a.example', 'https://b.example']")

    def test_production_uses_manifest_storage_and_whitenoise(self):
        out = self.run_settings(
            {'DJANGO_SECRET_KEY': 'x' * 60},
            "settings.STORAGES['staticfiles']['BACKEND'], "
            "'whitenoise.middleware.WhiteNoiseMiddleware' in settings.MIDDLEWARE",
        )
        self.assertEqual(out, 'whitenoise.storage.CompressedManifestStaticFilesStorage True')

    def test_debug_uses_plain_static_storage(self):
        out = self.run_settings({'DJANGO_DEBUG': '1'}, "settings.STORAGES['staticfiles']['BACKEND']")
        self.assertEqual(out, 'django.contrib.staticfiles.storage.StaticFilesStorage')

    def test_logging_sends_django_and_home_to_console(self):
        out = self.run_settings(
            {'DJANGO_SECRET_KEY': 'x' * 60},
            "settings.LOGGING['loggers']['django']['handlers'], settings.LOGGING['loggers']['home']['level']",
        )
        self.assertEqual(out, "['console'] INFO")
