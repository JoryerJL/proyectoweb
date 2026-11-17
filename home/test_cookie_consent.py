"""Cookie consent banner gating Google Analytics 4 (opt-in, Consent Mode v2 basic)."""
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from . import roles
from .tests import make_user

GTAG_SCRIPT = 'googletagmanager.com/gtag/js'


@override_settings(GA_MEASUREMENT_ID='G-TEST123')
class ConsentEnabledTests(TestCase):
    def setUp(self):
        make_user('admin1', roles.ADMINISTRADOR, email='admin1@example.com')

    def _public(self):
        return self.client.get(reverse('home:index')).content.decode()

    def _panel(self):
        self.client.login(username='admin1', password='Zq7!tR2#vLm9')
        return self.client.get(reverse('home:crud_categorias')).content.decode()

    def test_default_consent_is_denied_before_anything_else(self):
        for html in (self._public(), self._panel()):
            self.assertIn("gtag('consent', 'default'", html)
            for key in ('analytics_storage', 'ad_storage', 'ad_user_data', 'ad_personalization'):
                self.assertIn(f"'{key}': 'denied'", html)
            self.assertLess(html.index('window.dataLayer'), html.index("'consent', 'default'"))

    def test_gtag_script_not_rendered_server_side(self):
        for html in (self._public(), self._panel()):
            self.assertNotIn(GTAG_SCRIPT, html)
            self.assertNotIn("gtag('config'", html)
            self.assertNotIn("gtag('js'", html)

    def test_id_exposed_to_js(self):
        for html in (self._public(), self._panel()):
            self.assertIn('data-ga-id="G-TEST123"', html)

    def test_banner_present_and_hidden_by_default(self):
        for html in (self._public(), self._panel()):
            self.assertIn('data-cookie-banner', html)
            self.assertIn('role="region"', html)
            self.assertIn('data-cookie-accept', html)
            self.assertIn('data-cookie-reject', html)
            self.assertIn('Aceptar', html)
            self.assertIn('Rechazar', html)
            self.assertIn(reverse('home:cookies'), html)
            banner = html[html.index('data-cookie-banner'):]
            self.assertIn('hidden', banner[:200])

    def test_footer_has_preferences_button(self):
        for html in (self._public(), self._panel()):
            self.assertIn('data-cookie-preferences', html)
            self.assertIn('Preferencias de cookies', html)

    def test_cookies_page_in_404_page_too(self):
        response = self.client.get('/no-existe-xyz/')
        self.assertIn('data-cookie-banner', response.content.decode())


@override_settings(GA_MEASUREMENT_ID='')
class ConsentDisabledTests(TestCase):
    def test_no_banner_no_consent_script_when_ga_disabled(self):
        html = self.client.get(reverse('home:index')).content.decode()
        self.assertNotIn('data-cookie-banner', html)
        self.assertNotIn('consent', html.replace('canaco.js', ''))
        self.assertNotIn('data-ga-id', html)
        self.assertNotIn('gtag', html)

    def test_footer_button_absent_when_ga_disabled(self):
        html = self.client.get(reverse('home:index')).content.decode()
        self.assertNotIn('data-cookie-preferences', html)


@override_settings(GA_MEASUREMENT_ID='G-TEST123')
class VerificationPageTests(TestCase):
    def test_invalid_verification_page_exposes_nothing_ga_related(self):
        response = self.client.get(reverse('home:verificar_email', args=['xx', 'bad-token']))
        html = response.content.decode()
        self.assertEqual(response.status_code, 400)
        for needle in ('data-ga-id', 'data-cookie-banner', 'gtag', 'googletagmanager', 'G-TEST123'):
            self.assertNotIn(needle, html)


class CookiesPageTests(TestCase):
    def test_page_ok_and_documents_cookies(self):
        response = self.client.get(reverse('home:cookies'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reverse('home:cookies'), '/cookies/')
        html = response.content.decode()
        self.assertIn('_ga', html)
        self.assertIn('_ga_', html)
        self.assertIn('2 años', html)

    @override_settings(GA_MEASUREMENT_ID='G-TEST123')
    def test_page_mentions_preferences_button_when_enabled(self):
        html = self.client.get(reverse('home:cookies')).content.decode()
        self.assertIn('Preferencias de cookies', html)

    def test_in_sitemap(self):
        self.assertIn('/cookies/', self.client.get('/sitemap.xml').content.decode())


class ConsentScriptTests(TestCase):
    def setUp(self):
        self.js = (Path(settings.BASE_DIR) / 'static/js/canaco.js').read_text()

    def test_storage_key_and_values(self):
        self.assertIn('canaco.cookieConsent', self.js)
        self.assertIn('"granted"', self.js)
        self.assertIn('"denied"', self.js)

    def test_ads_signals_never_granted(self):
        self.assertNotIn('ad_storage: "granted"', self.js)
        self.assertNotIn('ad_user_data: "granted"', self.js)
        self.assertNotIn('ad_personalization: "granted"', self.js)

    def test_panel_action_checks_consent(self):
        body = self.js[self.js.index('const trackPanelAction'):]
        body = body[:body.index('const submitAjax')]
        self.assertIn('gaLoaded', body)


class ConsentRobustnessTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        self.js = (base / 'static/js/canaco.js').read_text()
        self.css = (base / 'static/css/canaco.css').read_text()

    def test_ga_disable_flag_toggled(self):
        self.assertIn('window["ga-disable-" + id] = true', self.js)
        self.assertIn('window["ga-disable-" + id] = false', self.js)

    def test_cross_tab_and_bfcache_resync(self):
        self.assertIn('addEventListener("storage"', self.js)
        self.assertIn('addEventListener("pageshow"', self.js)
        self.assertIn('event.persisted', self.js)

    def test_banner_offsets_flash_region_and_body(self):
        self.assertIn('has-cookie-banner', self.js)
        self.assertIn('--cookie-banner-height', self.js)
        self.assertIn('body.has-cookie-banner .flash-region', self.css)
        self.assertIn('body.has-cookie-banner { padding-bottom', self.css)

    def test_focus_restored_to_opener(self):
        self.assertIn('opener.focus()', self.js)
