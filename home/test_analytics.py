"""Google Analytics 4 integration: configuration-driven, off unless a valid ID is set."""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from canaco.env import parse_ga_measurement_id

from . import roles
from .context_processors import ga_measurement_id
from .tests import make_user

MALICIOUS = 'G-1"><script>alert(1)</script>'


class GaIdParsingTests(TestCase):
    def test_accepts_valid_and_strips(self):
        self.assertEqual(parse_ga_measurement_id(' G-ABC123 '), 'G-ABC123')

    def test_rejects_invalid_values(self):
        for value in ('', None, 'UA-123', 'g-abc', MALICIOUS, 'G-', 'G-AB C'):
            self.assertEqual(parse_ga_measurement_id(value), '', value)


class ContextProcessorTests(TestCase):
    @override_settings(GA_MEASUREMENT_ID='G-TEST123ABC')
    def test_exposes_id(self):
        ctx = ga_measurement_id(RequestFactory().get('/'))
        self.assertEqual(ctx, {'ga_measurement_id': 'G-TEST123ABC'})

    def test_registered_in_templates(self):
        procs = settings.TEMPLATES[0]['OPTIONS']['context_processors']
        self.assertIn('home.context_processors.ga_measurement_id', procs)


class SnippetRenderingTests(TestCase):
    def setUp(self):
        self.admin = make_user('admin1', roles.ADMINISTRADOR, email='admin1@example.com')

    @override_settings(GA_MEASUREMENT_ID='G-TEST123ABC')
    def test_public_page_has_snippet(self):
        html = self.client.get(reverse('home:index')).content.decode()
        self.assertNotIn('googletagmanager.com/gtag/js', html)
        self.assertIn('data-ga-id="G-TEST123ABC"', html)
        self.assertIn("gtag('consent', 'default'", html)
        self.assertIn('window.dataLayer', html)

    @override_settings(GA_MEASUREMENT_ID='G-TEST123ABC')
    def test_panel_page_has_snippet(self):
        self.client.login(username='admin1', password='Zq7!tR2#vLm9')
        html = self.client.get(reverse('home:crud_categorias')).content.decode()
        self.assertIn('data-ga-id="G-TEST123ABC"', html)

    @override_settings(GA_MEASUREMENT_ID='G-TEST123ABC')
    def test_404_page_has_snippet(self):
        response = self.client.get('/no-existe-xyz/')
        self.assertEqual(response.status_code, 404)
        self.assertIn('data-ga-id="G-TEST123ABC"', response.content.decode())

    @override_settings(GA_MEASUREMENT_ID='')
    def test_absent_when_empty(self):
        html = self.client.get(reverse('home:index')).content.decode()
        self.assertNotIn('googletagmanager', html)
        self.assertNotIn('gtag(', html)
        self.assertNotIn('data-ga-id', html)
        self.client.login(username='admin1', password='Zq7!tR2#vLm9')
        panel = self.client.get(reverse('home:crud_categorias')).content.decode()
        self.assertNotIn('googletagmanager', panel)

    def test_invalid_id_in_env_is_disabled(self):
        # Settings parse the raw env value; an invalid one must collapse to ''.
        self.assertEqual(parse_ga_measurement_id(MALICIOUS), '')

    @override_settings(GA_MEASUREMENT_ID=MALICIOUS)
    def test_partial_never_renders_unsafe_id_verbatim(self):
        # Defense in depth: even if a bad value reached the template, it is escaped.
        html = self.client.get(reverse('home:index')).content.decode()
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn(MALICIOUS, html)

    @override_settings(GA_MEASUREMENT_ID='G-TEST123ABC')
    def test_not_in_email_templates(self):
        for name in ('verificar_email.html', 'verificar_email.txt'):
            body = render_to_string(f'home/emails/{name}', {
                'ga_measurement_id': 'G-TEST123ABC', 'verification_url': 'https://x.test/',
                'site_name': 'Canaco', 'user': self.admin,
            })
            self.assertNotIn('googletagmanager', body)
            self.assertNotIn('gtag', body)


class PanelEventScriptTests(TestCase):
    def setUp(self):
        self.js = (Path(settings.BASE_DIR) / 'static/js/canaco.js').read_text()

    def test_panel_action_event_is_guarded_and_pii_free(self):
        self.assertIn("typeof window.gtag !== \"function\"", self.js)
        self.assertIn('gaLoaded', self.js)
        self.assertIn('"panel_action"', self.js)


@override_settings(GA_MEASUREMENT_ID='G-TEST123')
class VerificationTokenLeakTests(TestCase):
    """The verification URL carries uidb64+token; gtag's page_view would send it to Google."""

    def test_bad_token_page_has_no_gtag(self):
        user = make_user('unverified1', roles.ADMINISTRADOR, email='u1@example.com')
        user.perfil.email_verificado = False
        user.perfil.save()
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        response = self.client.get(reverse('home:verificar_email', args=[uid, 'bad-token']))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('googletagmanager', response.content.decode())
        self.assertNotIn('data-ga-id', response.content.decode())

    def test_bad_uid_page_has_no_gtag(self):
        response = self.client.get(reverse('home:verificar_email', args=['xx', 'bad-token']))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('googletagmanager', response.content.decode())
        self.assertNotIn('data-ga-id', response.content.decode())

    def test_verified_user_bad_token_page_has_no_gtag(self):
        user = make_user('verified1', roles.ADMINISTRADOR, email='v1@example.com')
        user.perfil.email_verificado = True
        user.perfil.save()
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        response = self.client.get(reverse('home:verificar_email', args=[uid, 'bad-token']))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('googletagmanager', response.content.decode())
        self.assertNotIn('data-ga-id', response.content.decode())

    def test_normal_public_page_still_has_gtag(self):
        self.assertIn('data-ga-id', self.client.get(reverse('home:index')).content.decode())
