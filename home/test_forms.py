import io

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from . import roles
from .models import Archivo, Categoria, Comentario, MensajeContacto, Perfil, Publicacion
from .tests import make_user


def png_bytes(fmt='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buffer, fmt)
    return buffer.getvalue()


def png_upload(name='foto.png', content_type='image/png'):
    return SimpleUploadedFile(name, png_bytes(), content_type=content_type)


STRONG = 'Zq7!tR2#vLm9'


class PublicacionFormViewTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor', roles.EDITOR)
        self.client.force_login(self.editor)
        self.categoria = Categoria.objects.create(nombre='Economia')
        self.url = reverse('home:crear_publicacion')

    def _payload(self, **extra):
        data = {
            'titulo': 'Titulo', 'resumen': 'Resumen', 'contenido': '<p>x</p>',
            'categoria': self.categoria.pk, 'estado': 'borrador',
        }
        data.update(extra)
        return data

    def test_valid_payload_creates(self):
        response = self.client.post(self.url, self._payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Publicacion.objects.get().autor, self.editor)

    def test_empty_title_is_rejected(self):
        response = self.client.post(self.url, self._payload(titulo='   '))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())
        self.assertContains(response, 'alert')

    def test_invalid_estado_is_rejected(self):
        response = self.client.post(self.url, self._payload(estado='hackeado'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())

    def test_invalid_categoria_is_rejected(self):
        response = self.client.post(self.url, self._payload(categoria=99999))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())

    def test_text_file_disguised_as_png_is_rejected(self):
        fake = SimpleUploadedFile('x.png', b'not an image at all', content_type='image/png')
        response = self.client.post(self.url, {**self._payload(), 'imagen_portada': fake})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(Archivo.objects.exists())

    def test_wrong_content_type_is_rejected(self):
        gif = SimpleUploadedFile('x.png', png_bytes(), content_type='text/plain')
        response = self.client.post(self.url, {**self._payload(), 'imagen_portada': gif})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())

    def test_valid_png_cover_is_accepted_and_extension_comes_from_format(self):
        # Client claims .php; the stored extension must come from the real format.
        upload = SimpleUploadedFile('evil.php', png_bytes(), content_type='image/png')
        response = self.client.post(self.url, {**self._payload(), 'imagen_portada': upload})
        self.assertEqual(response.status_code, 302)
        archivo = Publicacion.objects.get().imagen_portada
        self.assertTrue(archivo.ruta.name.endswith('.png'), archivo.ruta.name)
        archivo.ruta.delete(save=False)

    def test_bad_gallery_image_is_rejected(self):
        fake = SimpleUploadedFile('x.png', b'nope', content_type='image/png')
        response = self.client.post(self.url, {**self._payload(), 'galeria': [fake]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())


class SignUpFormTests(TestCase):
    def _payload(self, password):
        return {
            'username': 'nueva', 'email': 'nueva@x.com', 'first_name': 'N',
            'apellido_paterno': 'Perez', 'apellido_materno': 'Lopez',
            'password1': password, 'password2': password,
        }

    def test_weak_password_is_rejected(self):
        response = self.client.post(reverse('home:sign_up'), self._payload('12345678'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nueva').exists())

    def test_strong_password_creates_user_with_role_and_profile(self):
        response = self.client.post(reverse('home:sign_up'), self._payload(STRONG))
        self.assertRedirects(response, reverse('home:verificacion_enviada'))
        user = User.objects.get(username='nueva')
        self.assertEqual(roles.get_user_role(user).value, roles.COLABORADOR)
        self.assertEqual(user.last_name, 'Perez Lopez')
        self.assertEqual(Perfil.objects.get(user=user).apellido_materno, 'Lopez')

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user('otro', 'NUEVA@x.com', STRONG)
        response = self.client.post(reverse('home:sign_up'), self._payload(STRONG))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nueva').exists())


class PasswordChangeFormTests(TestCase):
    def setUp(self):
        self.user = make_user('u1', roles.COLABORADOR)
        self.user.set_password('Old-Passw0rd!x')
        self.user.save()
        self.client.force_login(self.user)
        self.url = reverse('home:crud_cambiar_contrasena')

    def _payload(self, new):
        return {'old_password': 'Old-Passw0rd!x', 'new_password1': new, 'new_password2': new}

    def test_weak_password_is_rejected(self):
        response = self.client.post(self.url, self._payload('12345678'))
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Old-Passw0rd!x'))

    def test_wrong_old_password_is_rejected(self):
        data = self._payload(STRONG)
        data['old_password'] = 'wrong'
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Old-Passw0rd!x'))

    def test_strong_password_changes_and_keeps_session(self):
        response = self.client.post(self.url, self._payload(STRONG))
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG))
        self.assertEqual(self.client.get(reverse('home:perfil')).status_code, 200)


class ProfilePhotoTests(TestCase):
    def setUp(self):
        self.user = make_user('u2', roles.COLABORADOR)
        self.client.force_login(self.user)

    def test_fake_photo_is_rejected(self):
        fake = SimpleUploadedFile('x.png', b'nope', content_type='image/png')
        response = self.client.post(reverse('home:crud_perfil'), {'username': 'u2', 'foto': fake})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Archivo.objects.exists())

    def test_valid_photo_is_accepted(self):
        response = self.client.post(reverse('home:crud_perfil'), {'username': 'u2', 'foto': png_upload()})
        self.assertEqual(response.status_code, 302)
        archivo = Perfil.objects.get(user=self.user).foto_perfil
        self.assertTrue(archivo.ruta.name.endswith('.png'))
        archivo.ruta.delete(save=False)


class CategoriaFormTests(TestCase):
    def setUp(self):
        self.admin = make_user('admin1', roles.ADMINISTRADOR)
        self.client.force_login(self.admin)
        Categoria.objects.create(nombre='Economia')

    def test_duplicate_name_case_insensitive_is_rejected(self):
        response = self.client.post(reverse('home:crud_categorias'), {'nombre': ' economia '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Categoria.objects.count(), 1)

    def test_valid_name_is_created(self):
        self.client.post(reverse('home:crud_categorias'), {'nombre': 'Cultura'})
        self.assertTrue(Categoria.objects.filter(nombre='Cultura', fk_user=self.admin).exists())

    def test_edit_to_duplicate_is_rejected_but_own_name_is_ok(self):
        otra = Categoria.objects.create(nombre='Deportes')
        url = reverse('home:editar_categoria', args=[otra.pk])
        self.assertEqual(self.client.post(url, {'nombre': 'ECONOMIA'}).status_code, 200)
        self.assertEqual(self.client.post(url, {'nombre': 'DEPORTES'}).status_code, 302)
        otra.refresh_from_db()
        self.assertEqual(otra.nombre, 'DEPORTES')

    def test_too_long_name_is_rejected(self):
        response = self.client.post(reverse('home:crud_categorias'), {'nombre': 'x' * 61})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Categoria.objects.count(), 1)


class ComentarioFormTests(TestCase):
    def setUp(self):
        self.user = make_user('u3', roles.COLABORADOR)
        self.client.force_login(self.user)
        self.pub = Publicacion.objects.create(
            titulo='t', resumen='r', contenido='c', estado=Publicacion.ESTADO_PUBLICADO,
        )
        self.url = self.pub.get_absolute_url()

    def test_empty_comment_is_rejected(self):
        response = self.client.post(self.url, {'contenido': '   '})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Comentario.objects.exists())

    def test_too_long_comment_is_rejected(self):
        self.client.post(self.url, {'contenido': 'x' * 2001})
        self.assertFalse(Comentario.objects.exists())

    def test_valid_comment_is_stripped_and_saved(self):
        self.client.post(self.url, {'contenido': '  hola  '})
        self.assertEqual(Comentario.objects.get().contenido, 'hola')


@override_settings(CONTACT_EMAIL='contacto@canaco.test')
class ContactoTests(TestCase):
    url_name = 'home:contactanos'

    def _payload(self, **extra):
        data = {
            'nombre': 'Ana', 'email': 'ana@x.com', 'asunto': 'Tengo una duda',
            'mensaje': 'Hola, quisiera saber mas.', 'website': '',
        }
        data.update(extra)
        return data

    def test_valid_post_saves_and_sends_email(self):
        response = self.client.post(reverse(self.url_name), self._payload())
        self.assertRedirects(response, reverse(self.url_name))
        self.assertEqual(MensajeContacto.objects.get().email, 'ana@x.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['contacto@canaco.test'])
        self.assertIn('Hola, quisiera', mail.outbox[0].body)

    @override_settings(CONTACT_EMAIL='')
    def test_no_contact_email_skips_sending_but_saves(self):
        self.client.post(reverse(self.url_name), self._payload())
        self.assertEqual(MensajeContacto.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_failure_still_succeeds(self):
        from unittest import mock
        with mock.patch('home.views.send_mail', side_effect=OSError('smtp down')), \
                self.assertLogs('home.views', level='WARNING'):
            response = self.client.post(reverse(self.url_name), self._payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(MensajeContacto.objects.count(), 1)

    def test_honeypot_filled_creates_nothing(self):
        response = self.client.post(reverse(self.url_name), self._payload(website='http://spam'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MensajeContacto.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_shows_error_and_creates_nothing(self):
        response = self.client.post(reverse(self.url_name), self._payload(email='no-es-correo'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alert')
        self.assertFalse(MensajeContacto.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_message_is_rejected(self):
        response = self.client.post(reverse(self.url_name), self._payload(mensaje=' '))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MensajeContacto.objects.exists())


class PanelUserFormsTests(TestCase):
    def setUp(self):
        self.admin = make_user('admin_forms', 'administrador')
        self.client.force_login(self.admin)

    def _payload(self, **extra):
        data = {
            'username': 'nuevo_panel', 'email': 'np@example.com', 'first_name': 'Nu',
            'apellido_paterno': 'Perez', 'apellido_materno': 'Lopez',
            'password1': STRONG, 'password2': STRONG, 'rol': 'editor',
        }
        data.update(extra)
        return data

    def test_weak_password_is_rejected_on_create(self):
        response = self.client.post(reverse('home:crear_usuario'), self._payload(password1='12345678', password2='12345678'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nuevo_panel').exists())
        self.assertContains(response, 'alert')

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(reverse('home:crear_usuario'), self._payload(password2=STRONG + 'x'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nuevo_panel').exists())

    def test_duplicate_username_is_rejected(self):
        make_user('nuevo_panel', 'colaborador')
        response = self.client.post(reverse('home:crear_usuario'), self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username='nuevo_panel').count(), 1)

    def test_password_is_required_on_create(self):
        response = self.client.post(reverse('home:crear_usuario'), self._payload(password1='', password2=''))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nuevo_panel').exists())

    def test_valid_create_sets_role_profile_and_hashed_password(self):
        response = self.client.post(reverse('home:crear_usuario'), self._payload())
        self.assertRedirects(response, reverse('home:crud_usuarios'))
        user = User.objects.get(username='nuevo_panel')
        self.assertEqual(roles.get_user_role(user).value, 'editor')
        self.assertTrue(user.check_password(STRONG))
        self.assertEqual(user.last_name, 'Perez Lopez')
        self.assertEqual(user.perfil.apellido_materno, 'Lopez')

    def test_invalid_role_is_rejected(self):
        response = self.client.post(reverse('home:crear_usuario'), self._payload(rol='root'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='nuevo_panel').exists())

    def test_form_keeps_submitted_values_on_error(self):
        response = self.client.post(reverse('home:crear_usuario'), self._payload(password1='12345678', password2='12345678'))
        self.assertContains(response, 'value="nuevo_panel"')

    def test_weak_password_is_rejected_on_edit(self):
        target = make_user('objetivo', 'colaborador')
        old_hash = target.password
        response = self.client.post(
            reverse('home:editar_usuario', args=[target.pk]),
            self._payload(username='objetivo', password1='12345678', password2='12345678'),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.password, old_hash)

    def test_edit_without_password_keeps_it_and_updates_role(self):
        target = make_user('objetivo2', 'colaborador')
        old_hash = target.password
        response = self.client.post(
            reverse('home:editar_usuario', args=[target.pk]),
            self._payload(username='objetivo2', password1='', password2='', rol='administrador'),
        )
        self.assertRedirects(response, reverse('home:crud_usuarios'))
        target.refresh_from_db()
        self.assertEqual(target.password, old_hash)
        self.assertEqual(roles.get_user_role(target).value, 'administrador')

    def test_edit_with_strong_password_changes_it(self):
        target = make_user('objetivo3', 'colaborador')
        new = 'Xk4$wP8@nQz1'
        self.client.post(
            reverse('home:editar_usuario', args=[target.pk]),
            self._payload(username='objetivo3', password1=new, password2=new),
        )
        target.refresh_from_db()
        self.assertTrue(target.check_password(new))

    def test_edit_cannot_take_another_users_username(self):
        make_user('ocupado', 'colaborador')
        target = make_user('objetivo4', 'colaborador')
        response = self.client.post(
            reverse('home:editar_usuario', args=[target.pk]),
            self._payload(username='ocupado', password1='', password2=''),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.username, 'objetivo4')
