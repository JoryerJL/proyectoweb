import importlib
import re
from datetime import timedelta
from unittest import mock

from django.apps import apps
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.mail import get_connection
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from canaco.env import validate_email_tls

from . import emails, roles
from .models import Perfil
from .tokens import email_verification_token

STRONG = 'Zq7!tR2#vLm9'
NEUTRAL_MESSAGE = 'Si el correo existe y no está verificado, te enviamos un nuevo enlace'


def signup_payload(**overrides):
    data = {
        'username': 'nueva', 'email': 'nueva@x.com', 'first_name': 'N',
        'apellido_paterno': 'Perez', 'apellido_materno': 'Lopez',
        'password1': STRONG, 'password2': STRONG,
    }
    data.update(overrides)
    return data


def extract_link(message):
    match = re.search(r'https?://testserver(/[^\s"<]*verificar_email/[^\s"<]+)', message.body)
    assert match, message.body
    return match.group(1)


class EmailSslSettingsTests(TestCase):
    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        EMAIL_USE_SSL=True, EMAIL_USE_TLS=False, EMAIL_PORT=465, EMAIL_TIMEOUT=7,
    )
    def test_connection_reflects_implicit_tls(self):
        connection = get_connection()
        self.assertTrue(connection.use_ssl)
        self.assertFalse(connection.use_tls)
        self.assertEqual(connection.port, 465)
        self.assertEqual(connection.timeout, 7)


class SignUpVerificationTests(TestCase):
    def sign_up(self, **overrides):
        return self.client.post(reverse('home:sign_up'), signup_payload(**overrides))

    def test_sign_up_sends_one_email_and_creates_unverified_profile(self):
        response = self.sign_up()
        self.assertRedirects(response, reverse('home:verificacion_enviada'))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['nueva@x.com'])
        self.assertEqual(message.subject, 'Confirma tu correo en Canaco')
        self.assertIn('/verificar_email/', message.body)
        self.assertTrue(message.alternatives)
        user = User.objects.get(username='nueva')
        self.assertFalse(user.perfil.email_verificado)
        self.assertIsNone(user.perfil.email_verificado_en)
        self.assertEqual(roles.get_user_role(user).value, roles.COLABORADOR)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_duplicate_email_with_different_case_is_rejected(self):
        User.objects.create_user('otro', 'NUEVA@X.com', STRONG)
        response = self.sign_up()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nueva').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_email_is_required(self):
        response = self.sign_up(email='')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nueva').exists())

    def test_send_failure_does_not_break_sign_up(self):
        with mock.patch('home.emails.send_verification_email', side_effect=OSError('smtp down')):
            response = self.sign_up()
        self.assertRedirects(response, reverse('home:verificacion_enviada'))
        self.assertTrue(User.objects.filter(username='nueva').exists())
        follow = self.client.get(reverse('home:verificacion_enviada'))
        self.assertContains(follow, 'reenv')

    def test_sent_page_offers_resend_form(self):
        response = self.client.get(reverse('home:verificacion_enviada'))
        self.assertContains(response, reverse('home:reenviar_verificacion'))


class VerifyLinkTests(TestCase):
    def setUp(self):
        self.client.post(reverse('home:sign_up'), signup_payload())
        self.link = extract_link(mail.outbox[0])
        self.user = User.objects.get(username='nueva')

    def test_link_verifies_and_redirects_to_login(self):
        response = self.client.get(self.link)
        self.assertRedirects(response, reverse('home:login'))
        perfil = Perfil.objects.get(user=self.user)
        self.assertTrue(perfil.email_verificado)
        self.assertIsNotNone(perfil.email_verificado_en)

    def test_same_link_second_time_redirects_to_login_with_info(self):
        self.client.get(self.link)
        response = self.client.get(self.link, follow=True)
        self.assertRedirects(response, reverse('home:login'))
        self.assertContains(response, 'Tu correo ya estaba verificado. Inicia sesión.')

    def test_tampered_token_on_verified_account_is_still_rejected(self):
        self.client.get(self.link)
        response = self.client.get(self.link[:-4] + 'xyz/')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, reverse('home:reenviar_verificacion'), status_code=400)

    def test_tampered_token_is_rejected(self):
        response = self.client.get(self.link[:-4] + 'xyz/')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Perfil.objects.get(user=self.user).email_verificado)

    def test_unknown_uid_is_rejected(self):
        uid = urlsafe_base64_encode(force_bytes(999999))
        token = email_verification_token.make_token(self.user)
        response = self.client.get(reverse('home:verificar_email', args=[uid, token]))
        self.assertEqual(response.status_code, 400)

    def test_changing_email_invalidates_link(self):
        self.user.email = 'otro@x.com'
        self.user.save()
        response = self.client.get(self.link)
        self.assertEqual(response.status_code, 400)


class LoginGateTests(TestCase):
    def setUp(self):
        self.client.post(reverse('home:sign_up'), signup_payload())
        self.link = extract_link(mail.outbox[0])

    def login(self):
        return self.client.post(reverse('home:login'), {'username': 'nueva', 'password': STRONG})

    def test_login_blocked_until_verified(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Confirma tu correo')
        self.assertContains(response, reverse('home:reenviar_verificacion'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_works_after_verification(self):
        self.client.get(self.link)
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_inactive_verified_user_gets_generic_invalid_login(self):
        self.client.get(self.link)
        User.objects.filter(username='nueva').update(is_active=False)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        # ModelBackend rejects inactive users before confirm_login_allowed, so the generic text shows.
        self.assertContains(response, 'Por favor introduzca nombre de usuario y contraseña correctos')
        self.assertNotContains(response, 'Confirma tu correo')

    def test_login_page_links_to_resend(self):
        self.assertContains(self.client.get(reverse('home:login')), reverse('home:reenviar_verificacion'))


class ResendTests(TestCase):
    def setUp(self):
        self.url = reverse('home:reenviar_verificacion')

    def post(self, email):
        return self.client.post(self.url, {'email': email})

    def test_get_shows_form(self):
        self.assertContains(self.client.get(self.url), 'name="email"')

    def test_resend_for_unverified_sends_email(self):
        user = User.objects.create_user('u1', 'u1@x.com', STRONG)
        Perfil.objects.filter(user=user).update(email_verificado=False)
        response = self.post('u1@x.com')
        self.assertContains(response, NEUTRAL_MESSAGE)
        self.assertEqual(len(mail.outbox), 1)

    def test_responses_are_identical_and_no_mail_for_verified_or_unknown(self):
        unverified = User.objects.create_user('u1', 'u1@x.com', STRONG)
        Perfil.objects.filter(user=unverified).update(email_verificado=False)
        User.objects.create_user('u2', 'u2@x.com', STRONG)  # created verified

        bodies = []
        counts = []
        for email in ('u1@x.com', 'u2@x.com', 'nobody@x.com'):
            mail.outbox.clear()
            response = self.post(email)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, NEUTRAL_MESSAGE)
            body = response.content.decode()
            body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', '', body)
            body = re.sub(r'value="[^"]*@x\.com"', '', body)
            bodies.append(body)
            counts.append(len(mail.outbox))
        self.assertEqual(counts, [1, 0, 0])
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[1], bodies[2])

    def test_resend_within_60_seconds_is_throttled(self):
        user = User.objects.create_user('u1', 'u1@x.com', STRONG)
        Perfil.objects.filter(user=user).update(email_verificado=False)
        self.post('u1@x.com')
        response = self.post('u1@x.com')
        self.assertContains(response, NEUTRAL_MESSAGE)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_allowed_after_60_seconds(self):
        user = User.objects.create_user('u1', 'u1@x.com', STRONG)
        Perfil.objects.filter(user=user).update(
            email_verificado=False,
            verificacion_enviada_en=timezone.now() - timedelta(seconds=61),
        )
        self.post('u1@x.com')
        self.assertEqual(len(mail.outbox), 1)

    def test_send_failure_still_shows_neutral_message(self):
        user = User.objects.create_user('u1', 'u1@x.com', STRONG)
        Perfil.objects.filter(user=user).update(email_verificado=False)
        with mock.patch('home.emails.send_verification_email', side_effect=OSError('down')):
            response = self.post('u1@x.com')
        self.assertContains(response, NEUTRAL_MESSAGE)


class DefaultsAndMigrationTests(TestCase):
    def test_orm_created_user_is_verified(self):
        user = User.objects.create_user('plain', 'plain@x.com', STRONG)
        self.assertTrue(user.perfil.email_verificado)
        self.assertIsNotNone(user.perfil.email_verificado_en)

    def test_superuser_is_verified(self):
        user = User.objects.create_superuser('root', 'root@x.com', STRONG)
        self.assertTrue(user.perfil.email_verificado)

    def test_panel_created_user_is_verified(self):
        admin = User.objects.create_superuser('boss', 'boss@x.com', STRONG)
        self.client.force_login(admin)
        response = self.client.post(reverse('home:crear_usuario'), {
            'username': 'panelu', 'email': 'panelu@x.com', 'first_name': 'P',
            'apellido_paterno': '', 'apellido_materno': '',
            'password1': STRONG, 'password2': STRONG, 'rol': roles.COLABORADOR,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.get(username='panelu').perfil.email_verificado)

    def test_data_migration_marks_existing_profiles_verified(self):
        module = importlib.import_module('home.migrations.0010_mark_existing_verified')
        user = User.objects.create_user('old', 'old@x.com', STRONG)
        Perfil.objects.filter(user=user).update(email_verificado=False, email_verificado_en=None)
        module.mark_existing_verified(apps, None)
        user.perfil.refresh_from_db()
        self.assertTrue(user.perfil.email_verificado)
        self.assertIsNotNone(user.perfil.email_verificado_en)


class ProfileDefaultTests(TestCase):
    def test_user_without_profile_hitting_profile_view_gets_verified_profile(self):
        user = User.objects.create_user('noprof', 'noprof@x.com', STRONG)
        Perfil.objects.filter(user=user).delete()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('home:perfil')).status_code, 200)
        self.assertTrue(Perfil.objects.get(user=user).email_verificado)

    def test_model_default_is_verified(self):
        self.assertTrue(Perfil._meta.get_field('email_verificado').default)


class EmailContentTests(TestCase):
    def test_plain_text_body_is_not_html_escaped(self):
        user = User.objects.create_user('ob', 'ob@x.com', STRONG, first_name="O'Brien")
        self.client.post(reverse('home:reenviar_verificacion'), {'email': 'ob@x.com'})  # verified: no mail
        emails.send_verification_email('https://example.org', user)
        body = mail.outbox[-1].body
        self.assertIn("O'Brien", body)
        self.assertNotIn('&#x27;', body)

    @override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
    def test_link_is_https_behind_proxy(self):
        self.client.post(
            reverse('home:sign_up'), signup_payload(), HTTP_X_FORWARDED_PROTO='https', SERVER_PORT='443',
        )
        self.assertIn('https://testserver/verificar_email/', mail.outbox[0].body)


class AsyncSendTests(TestCase):
    @override_settings(EMAIL_SEND_ASYNC=True)
    def test_async_captures_base_url_and_uses_daemon_thread(self):
        user = User.objects.create_user('a1', 'a1@x.com', STRONG)
        request = self.client.get('/').wsgi_request
        with mock.patch('home.emails.threading.Thread') as thread:
            emails.send_verification_email_async(request, user)
        kwargs = thread.call_args.kwargs
        self.assertTrue(kwargs['daemon'])
        self.assertEqual(kwargs['args'], ('http://testserver', user))
        thread.return_value.start.assert_called_once()

    @override_settings(EMAIL_SEND_ASYNC=False)
    def test_sync_mode_sends_inline_and_swallows_errors(self):
        user = User.objects.create_user('a2', 'a2@x.com', STRONG)
        emails.send_verification_email_async('https://example.org', user)
        self.assertEqual(len(mail.outbox), 1)
        with mock.patch('home.emails.send_verification_email', side_effect=OSError('down')):
            emails.send_verification_email_async('https://example.org', user)

    def test_timestamp_is_written_before_sending(self):
        user = User.objects.create_user('a3', 'a3@x.com', STRONG)
        Perfil.objects.filter(user=user).update(email_verificado=False)
        seen = {}

        def fake_send(base, u):
            seen['ts'] = Perfil.objects.get(user=u).verificacion_enviada_en

        with mock.patch('home.emails.send_verification_email', side_effect=fake_send):
            self.client.post(reverse('home:reenviar_verificacion'), {'email': 'a3@x.com'})
        self.assertIsNotNone(seen['ts'])

    def test_claim_send_slot_is_single_use_within_cooldown(self):
        user = User.objects.create_user('a4', 'a4@x.com', STRONG)
        self.assertTrue(emails.claim_send_slot(user))
        self.assertFalse(emails.claim_send_slot(user))


class ResendLookupTests(TestCase):
    def test_unverified_account_wins_over_verified_duplicate(self):
        User.objects.create_user('verified', 'dup@x.com', STRONG)
        unverified = User.objects.create_user('unverified', 'DUP@x.com', STRONG)
        Perfil.objects.filter(user=unverified).update(email_verificado=False)
        self.client.post(reverse('home:reenviar_verificacion'), {'email': 'dup@x.com'})
        self.assertEqual(len(mail.outbox), 1)


class EmailTlsSettingsTests(TestCase):
    def test_both_tls_flags_are_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_email_tls(True, True)

    def test_single_flag_is_accepted(self):
        validate_email_tls(True, False)
        validate_email_tls(False, True)
        validate_email_tls(False, False)


class CleanupCommandTests(TestCase):
    def make(self, name, *, verified, days_old, last_login=None):
        user = User.objects.create_user(name, f'{name}@x.com', STRONG)
        Perfil.objects.filter(user=user).update(email_verificado=verified)
        User.objects.filter(pk=user.pk).update(
            date_joined=timezone.now() - timedelta(days=days_old), last_login=last_login,
        )
        return user

    def test_removes_only_old_unverified_never_logged_in(self):
        self.make('stale', verified=False, days_old=8)
        self.make('recent', verified=False, days_old=2)
        self.make('verified', verified=True, days_old=30)
        self.make('loggedin', verified=False, days_old=30, last_login=timezone.now())
        call_command('limpiar_no_verificados')
        remaining = set(User.objects.values_list('username', flat=True))
        self.assertEqual(remaining, {'recent', 'verified', 'loggedin'})

    def test_days_option(self):
        self.make('mid', verified=False, days_old=3)
        call_command('limpiar_no_verificados', '--days', '2')
        self.assertFalse(User.objects.filter(username='mid').exists())
