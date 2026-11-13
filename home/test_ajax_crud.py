"""AJAX layer for the panel CRUDs: categorias, comentarios, usuarios and perfil.

AJAX requests are flagged with ``X-Requested-With: fetch`` (same convention as the
infinite scroll). Plain form posts must keep redirecting exactly as before.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import roles
from .models import Categoria, Comentario, Perfil, Publicacion
from .test_forms import png_upload
from .tests import make_user

PASSWORD = 'Zq7!tR2#vLm9'
AJAX = {'HTTP_X_REQUESTED_WITH': 'fetch'}


class AjaxCase(TestCase):
    def setUp(self):
        self.admin = make_user('admin1', roles.ADMINISTRADOR, email='admin1@example.com')
        self.client.login(username='admin1', password=PASSWORD)

    def post(self, name, data=None, args=(), **extra):
        return self.client.post(reverse(f'home:{name}', args=args), data or {}, **extra)

    def ajax(self, name, data=None, args=()):
        return self.post(name, data, args, **AJAX)

    def assertOkJson(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertTrue(payload['message'])
        return payload

    def assertErrorJson(self, response, field):
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertIn(field, payload['errors'])
        return payload


class CategoriaAjaxTests(AjaxCase):
    def test_create_returns_row_html(self):
        payload = self.assertOkJson(self.ajax('crud_categorias', {'nombre': 'Deportes'}))
        categoria = Categoria.objects.get(nombre='Deportes')
        self.assertEqual(payload['id'], categoria.pk)
        self.assertIn('Deportes', payload['html'])
        self.assertIn(f'id="categoria-{categoria.pk}"', payload['html'])
        self.assertIn('csrfmiddlewaretoken', payload['html'])

    def test_create_escapes_user_data_in_html(self):
        payload = self.assertOkJson(self.ajax('crud_categorias', {'nombre': '<b>x</b>'}))
        self.assertNotIn('<b>x</b>', payload['html'])
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', payload['html'])

    def test_create_duplicate_is_400(self):
        Categoria.objects.create(nombre='Deportes', fk_user=self.admin)
        self.assertErrorJson(self.ajax('crud_categorias', {'nombre': 'deportes'}), 'nombre')
        self.assertEqual(Categoria.objects.count(), 1)

    def test_create_without_ajax_still_redirects(self):
        response = self.post('crud_categorias', {'nombre': 'Deportes'})
        self.assertRedirects(response, reverse('home:crud_categorias'))

    def test_edit_returns_replacement_row(self):
        categoria = Categoria.objects.create(nombre='Viejo', fk_user=self.admin)
        payload = self.assertOkJson(self.ajax('editar_categoria', {'nombre': 'Nuevo'}, (categoria.pk,)))
        categoria.refresh_from_db()
        self.assertEqual(categoria.nombre, 'Nuevo')
        self.assertEqual(payload['id'], categoria.pk)
        self.assertIn('Nuevo', payload['html'])

    def test_edit_invalid_is_400(self):
        categoria = Categoria.objects.create(nombre='Viejo', fk_user=self.admin)
        self.assertErrorJson(self.ajax('editar_categoria', {'nombre': ''}, (categoria.pk,)), 'nombre')

    def test_edit_without_ajax_still_redirects(self):
        categoria = Categoria.objects.create(nombre='Viejo', fk_user=self.admin)
        response = self.post('editar_categoria', {'nombre': 'Nuevo'}, (categoria.pk,))
        self.assertRedirects(response, reverse('home:crud_categorias'))

    def test_delete_returns_removed(self):
        categoria = Categoria.objects.create(nombre='X', fk_user=self.admin)
        payload = self.assertOkJson(self.ajax('eliminar_categoria', args=(categoria.pk,)))
        self.assertTrue(payload['removed'])
        self.assertEqual(payload['id'], categoria.pk)
        self.assertFalse(Categoria.objects.filter(pk=categoria.pk).exists())

    def test_delete_without_ajax_still_redirects(self):
        categoria = Categoria.objects.create(nombre='X', fk_user=self.admin)
        response = self.post('eliminar_categoria', args=(categoria.pk,))
        self.assertRedirects(response, reverse('home:crud_categorias'))

    def test_list_renders_rows_from_partial(self):
        categoria = Categoria.objects.create(nombre='Cultura', fk_user=self.admin)
        response = self.client.get(reverse('home:crud_categorias'))
        self.assertContains(response, f'id="categoria-{categoria.pk}"')
        self.assertContains(response, 'data-ajax')

    def test_anonymous_ajax_is_not_served(self):
        categoria = Categoria.objects.create(nombre='X', fk_user=self.admin)
        response = Client().post(reverse('home:eliminar_categoria', args=(categoria.pk,)), **AJAX)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Categoria.objects.filter(pk=categoria.pk).exists())

    def test_wrong_role_ajax_is_403(self):
        make_user('colab', roles.COLABORADOR)
        self.client.login(username='colab', password=PASSWORD)
        categoria = Categoria.objects.create(nombre='X', fk_user=self.admin)
        self.assertEqual(self.ajax('eliminar_categoria', args=(categoria.pk,)).status_code, 403)
        self.assertEqual(self.ajax('crud_categorias', {'nombre': 'Y'}).status_code, 403)
        self.assertTrue(Categoria.objects.filter(pk=categoria.pk).exists())

    def test_csrf_still_required_for_ajax(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='admin1', password=PASSWORD)
        response = client.post(reverse('home:crud_categorias'), {'nombre': 'Z'}, **AJAX)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Categoria.objects.filter(nombre='Z').exists())

    def test_csrf_token_accepted_when_sent(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='admin1', password=PASSWORD)
        page = client.get(reverse('home:crud_categorias'))
        token = page.cookies['csrftoken'].value
        response = client.post(
            reverse('home:crud_categorias'),
            {'nombre': 'Z', 'csrfmiddlewaretoken': token},
            **AJAX,
        )
        self.assertEqual(response.status_code, 200)


class ComentarioAjaxTests(AjaxCase):
    def setUp(self):
        super().setUp()
        publicacion = Publicacion.objects.create(titulo='Titulo', contenido='<p>x</p>', autor=self.admin)
        self.comentario = Comentario.objects.create(
            publicacion=publicacion, user=self.admin, contenido='Hola <i>mundo</i>',
        )

    def test_approve_returns_updated_row(self):
        payload = self.assertOkJson(self.ajax('aprobar_comentario', args=(self.comentario.pk,)))
        self.comentario.refresh_from_db()
        self.assertEqual(self.comentario.estado, Comentario.ESTADO_APROBADO)
        self.assertEqual(payload['id'], self.comentario.pk)
        self.assertIn('Aprobado', payload['html'])
        self.assertIn(f'id="comentario-{self.comentario.pk}"', payload['html'])
        self.assertNotIn('<i>mundo</i>', payload['html'])

    def test_block_returns_updated_row(self):
        payload = self.assertOkJson(self.ajax('bloquear_comentario', args=(self.comentario.pk,)))
        self.comentario.refresh_from_db()
        self.assertEqual(self.comentario.estado, Comentario.ESTADO_BLOQUEADO)
        self.assertIn('Bloqueado', payload['html'])

    def test_delete_returns_removed(self):
        payload = self.assertOkJson(self.ajax('eliminar_comentario', args=(self.comentario.pk,)))
        self.assertTrue(payload['removed'])
        self.assertFalse(Comentario.objects.exists())

    def test_non_ajax_still_redirects(self):
        for name in ('aprobar_comentario', 'bloquear_comentario', 'eliminar_comentario'):
            response = self.post(name, args=(self.comentario.pk,))
            self.assertRedirects(response, reverse('home:crud_comentarios'), msg_prefix=name)
            self.comentario = Comentario.objects.create(
                publicacion=self.comentario.publicacion, user=self.admin, contenido='otro',
            )

    def test_anonymous_and_wrong_role_blocked(self):
        self.assertEqual(Client().post(reverse('home:aprobar_comentario', args=(self.comentario.pk,)), **AJAX).status_code, 302)
        make_user('colab', roles.COLABORADOR)
        self.client.login(username='colab', password=PASSWORD)
        self.assertEqual(self.ajax('eliminar_comentario', args=(self.comentario.pk,)).status_code, 403)
        self.assertTrue(Comentario.objects.filter(pk=self.comentario.pk).exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='admin1', password=PASSWORD)
        response = client.post(reverse('home:aprobar_comentario', args=(self.comentario.pk,)), **AJAX)
        self.assertEqual(response.status_code, 403)

    def test_list_renders_rows_from_partial(self):
        response = self.client.get(reverse('home:crud_comentarios'))
        self.assertContains(response, f'id="comentario-{self.comentario.pk}"')


class UsuarioAjaxTests(AjaxCase):
    def new_user_data(self, **extra):
        data = {
            'username': 'nuevo', 'email': 'nuevo@example.com', 'first_name': 'Nu',
            'apellido_paterno': 'A', 'apellido_materno': 'B', 'rol': roles.EDITOR,
            'password1': 'Zq7!tR2#vLm9x', 'password2': 'Zq7!tR2#vLm9x',
        }
        data.update(extra)
        return data

    def test_create_returns_row(self):
        payload = self.assertOkJson(self.ajax('crear_usuario', self.new_user_data()))
        user = User.objects.get(username='nuevo')
        self.assertEqual(payload['id'], user.pk)
        self.assertIn(f'id="usuario-{user.pk}"', payload['html'])
        self.assertIn('Editor', payload['html'])

    def test_create_invalid_is_400(self):
        response = self.ajax('crear_usuario', self.new_user_data(password2='distinta'))
        self.assertErrorJson(response, 'password2')
        self.assertFalse(User.objects.filter(username='nuevo').exists())

    def test_create_without_ajax_still_redirects(self):
        response = self.post('crear_usuario', self.new_user_data())
        self.assertRedirects(response, reverse('home:crud_usuarios'))

    def test_edit_returns_row(self):
        target = make_user('objetivo', roles.COLABORADOR, email='o@example.com')
        data = self.new_user_data(username='objetivo', first_name='Renombrado', password1='', password2='')
        payload = self.assertOkJson(self.ajax('editar_usuario', data, (target.pk,)))
        target.refresh_from_db()
        self.assertEqual(target.first_name, 'Renombrado')
        self.assertIn('Renombrado', payload['html'])
        self.assertEqual(payload['id'], target.pk)

    def test_edit_invalid_is_400(self):
        target = make_user('objetivo', roles.COLABORADOR)
        data = self.new_user_data(username='admin1', password1='', password2='')
        self.assertErrorJson(self.ajax('editar_usuario', data, (target.pk,)), 'username')

    def test_edit_without_ajax_still_redirects(self):
        target = make_user('objetivo', roles.COLABORADOR)
        data = self.new_user_data(username='objetivo', password1='', password2='')
        self.assertRedirects(self.post('editar_usuario', data, (target.pk,)), reverse('home:crud_usuarios'))

    def test_toggle_block_returns_row(self):
        target = make_user('objetivo', roles.COLABORADOR)
        payload = self.assertOkJson(self.ajax('bloquear_usuario', args=(target.pk,)))
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertIn('Bloqueado', payload['html'])
        self.assertIn('Desbloquear', payload['html'])

    def test_blocking_yourself_is_rejected_in_ajax(self):
        response = self.ajax('bloquear_usuario', args=(self.admin.pk,))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_delete_returns_removed(self):
        target = make_user('objetivo', roles.COLABORADOR)
        payload = self.assertOkJson(self.ajax('eliminar_usuario', args=(target.pk,)))
        self.assertTrue(payload['removed'])
        self.assertFalse(User.objects.filter(pk=target.pk).exists())

    def test_deleting_yourself_is_rejected_in_ajax(self):
        response = self.ajax('eliminar_usuario', args=(self.admin.pk,))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_block_and_delete_without_ajax_still_redirect(self):
        target = make_user('objetivo', roles.COLABORADOR)
        self.assertRedirects(self.post('bloquear_usuario', args=(target.pk,)), reverse('home:crud_usuarios'))
        self.assertRedirects(self.post('eliminar_usuario', args=(target.pk,)), reverse('home:crud_usuarios'))

    def test_anonymous_and_wrong_role_blocked(self):
        target = make_user('objetivo', roles.COLABORADOR)
        self.assertEqual(Client().post(reverse('home:eliminar_usuario', args=(target.pk,)), **AJAX).status_code, 302)
        make_user('editor1', roles.EDITOR)
        self.client.login(username='editor1', password=PASSWORD)
        self.assertEqual(self.ajax('crear_usuario', self.new_user_data()).status_code, 403)
        self.assertEqual(self.ajax('eliminar_usuario', args=(target.pk,)).status_code, 403)
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='admin1', password=PASSWORD)
        response = client.post(reverse('home:crear_usuario'), self.new_user_data(), **AJAX)
        self.assertEqual(response.status_code, 403)

    def test_list_renders_rows_and_dialog(self):
        response = self.client.get(reverse('home:crud_usuarios'))
        self.assertContains(response, f'id="usuario-{self.admin.pk}"')
        self.assertContains(response, 'data-ajax')
        self.assertContains(response, '<dialog')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='canaco-test-media-'))
class PerfilAjaxTests(AjaxCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def profile_data(self, **extra):
        data = {
            'username': 'admin1', 'email': 'admin1@example.com', 'first_name': 'Ada',
            'apellido_paterno': 'Lovelace', 'apellido_materno': '',
        }
        data.update(extra)
        return data

    def test_update_returns_bindings(self):
        payload = self.assertOkJson(self.ajax('crud_perfil', self.profile_data(username='ada')))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.username, 'ada')
        self.assertEqual(self.admin.first_name, 'Ada')
        self.assertEqual(payload['bind']['profile-username'], 'ada')
        self.assertEqual(payload['bind']['profile-first-name'], 'Ada')
        self.assertEqual(payload['bind']['profile-initial'], 'a')

    def test_update_with_image_returns_photo_url(self):
        data = self.profile_data(foto=png_upload())
        payload = self.assertOkJson(self.ajax('crud_perfil', data))
        perfil = Perfil.objects.get(user=self.admin)
        self.assertTrue(perfil.foto_perfil)
        self.assertEqual(payload['bind_src']['profile-photo'], perfil.foto_perfil.display_url)

    def test_invalid_image_is_400(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        self.assertErrorJson(self.ajax('crud_perfil', self.profile_data(foto=fake)), 'foto')

    def test_duplicate_username_is_400(self):
        make_user('otro', roles.COLABORADOR)
        self.assertErrorJson(self.ajax('crud_perfil', self.profile_data(username='otro')), 'username')

    def test_without_ajax_still_redirects(self):
        self.assertRedirects(self.post('crud_perfil', self.profile_data()), reverse('home:perfil'))

    def test_anonymous_ajax_is_not_served(self):
        self.assertEqual(Client().post(reverse('home:crud_perfil'), self.profile_data(), **AJAX).status_code, 302)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username='admin1', password=PASSWORD)
        self.assertEqual(client.post(reverse('home:crud_perfil'), self.profile_data(), **AJAX).status_code, 403)

    def test_change_password_keeps_session(self):
        data = {'old_password': PASSWORD, 'new_password1': 'Nw9$kLp2!xQz', 'new_password2': 'Nw9$kLp2!xQz'}
        self.assertOkJson(self.ajax('crud_cambiar_contrasena', data))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Nw9$kLp2!xQz'))
        # Session still valid: the profile page does not bounce to the login screen.
        self.assertEqual(self.client.get(reverse('home:perfil')).status_code, 200)

    def test_change_password_invalid_is_400(self):
        data = {'old_password': 'mala', 'new_password1': 'Nw9$kLp2!xQz', 'new_password2': 'Nw9$kLp2!xQz'}
        self.assertErrorJson(self.ajax('crud_cambiar_contrasena', data), 'old_password')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(PASSWORD))

    def test_change_password_without_ajax_still_redirects(self):
        data = {'old_password': PASSWORD, 'new_password1': 'Nw9$kLp2!xQz', 'new_password2': 'Nw9$kLp2!xQz'}
        self.assertRedirects(self.post('crud_cambiar_contrasena', data), reverse('home:crud_cambiar_contrasena'))

    def test_change_password_requires_login(self):
        self.assertEqual(Client().post(reverse('home:crud_cambiar_contrasena'), {}, **AJAX).status_code, 302)


class AjaxHooksInMarkupTests(AjaxCase):
    def test_panel_pages_mark_forms_for_ajax(self):
        for name in ('crud_perfil', 'crud_cambiar_contrasena'):
            self.assertContains(self.client.get(reverse(f'home:{name}')), 'data-ajax', msg_prefix=name)

    def test_flash_region_is_aria_live(self):
        self.assertContains(self.client.get(reverse('home:crud_categorias')), 'aria-live="polite"')


class AjaxNotFoundTests(AjaxCase):
    def assertNotFoundJson(self, response):
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['message'], 'El registro ya no existe.')

    def test_ajax_missing_records_return_json_404(self):
        self.assertNotFoundJson(self.ajax('eliminar_categoria', args=(99999,)))
        self.assertNotFoundJson(self.ajax('editar_categoria', {'nombre': 'x'}, (99999,)))
        self.assertNotFoundJson(self.ajax('aprobar_comentario', args=(99999,)))
        self.assertNotFoundJson(self.ajax('bloquear_comentario', args=(99999,)))
        self.assertNotFoundJson(self.ajax('eliminar_comentario', args=(99999,)))
        self.assertNotFoundJson(self.ajax('editar_usuario', {'username': 'x'}, (99999,)))
        self.assertNotFoundJson(self.ajax('bloquear_usuario', args=(99999,)))
        self.assertNotFoundJson(self.ajax('eliminar_usuario', args=(99999,)))

    def test_non_ajax_missing_records_still_404_html(self):
        response = self.post('eliminar_categoria', args=(99999,))
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(response['Content-Type'], 'application/json')
        self.assertEqual(self.post('editar_usuario', {}, (99999,)).status_code, 404)
