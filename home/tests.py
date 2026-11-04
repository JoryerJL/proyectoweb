from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import TestCase

from .management.commands.seed_news import PUBLICACIONES
from .models import Archivo, Categoria, Comentario, GaleriaPublicacion, Publicacion


class SeedNewsCommandTests(TestCase):
    def test_creates_sample_news_with_categories_and_covers(self):
        call_command('seed_news', verbosity=0)

        self.assertGreaterEqual(Categoria.objects.count(), 4)
        publicadas = Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO)
        self.assertGreaterEqual(publicadas.count(), 6)
        self.assertFalse(publicadas.filter(categoria__isnull=True).exists())
        self.assertFalse(publicadas.filter(imagen_portada__isnull=True).exists())
        self.assertTrue(Publicacion.objects.filter(estado=Publicacion.ESTADO_BORRADOR).exists())
        self.assertTrue(Comentario.objects.filter(estado=Comentario.ESTADO_APROBADO).exists())

    def test_is_idempotent(self):
        call_command('seed_news', verbosity=0)
        def counts():
            return (
                Categoria.objects.count(),
                Publicacion.objects.count(),
                Comentario.objects.count(),
                GaleriaPublicacion.objects.count(),
            )

        before = counts()
        call_command('seed_news', verbosity=0)

        self.assertEqual(before, counts())

    def test_published_news_have_gallery_photos_different_from_cover(self):
        call_command('seed_news', verbosity=0)

        for publicacion in Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO):
            archivos = [g.archivo_id for g in publicacion.galeria.all()]
            self.assertGreaterEqual(len(archivos), 2, publicacion.titulo)
            self.assertNotIn(publicacion.imagen_portada_id, archivos, publicacion.titulo)

    def test_every_seed_image_exists_in_static_and_is_unique_per_news(self):
        rutas = [ruta for data in PUBLICACIONES for ruta in [data['portada'], *data.get('galeria', [])]]

        self.assertEqual(len(rutas), len(set(rutas)))
        for ruta in rutas:
            self.assertTrue(ruta.startswith('images/news/'), ruta)
            self.assertIsNotNone(finders.find(ruta), ruta)

    def test_rerun_syncs_photos_of_existing_news(self):
        call_command('seed_news', verbosity=0)
        publicacion = Publicacion.objects.get(titulo=PUBLICACIONES[0]['titulo'])
        vieja = Archivo.objects.create(nombre='old.jpg', nombre_temporal='old.jpg', ruta='images/hero_1.jpg')
        publicacion.imagen_portada = vieja
        publicacion.save()
        publicacion.galeria.create(archivo=vieja)

        call_command('seed_news', verbosity=0)

        publicacion.refresh_from_db()
        self.assertEqual(str(publicacion.imagen_portada.ruta), PUBLICACIONES[0]['portada'])
        self.assertEqual(
            sorted(str(g.archivo.ruta) for g in publicacion.galeria.all()),
            sorted(PUBLICACIONES[0]['galeria']),
        )

    def test_publication_dates_are_spread_out(self):
        call_command('seed_news', verbosity=0)

        fechas = set(Publicacion.objects.values_list('createdat__date', flat=True))
        self.assertGreater(len(fechas), 1)


# Roles (auth.Group based)

from django.contrib.auth.models import Group, User  # noqa: E402
from django.urls import reverse  # noqa: E402

from . import roles  # noqa: E402


def make_user(username, role=None, **extra):
    user = User.objects.create_user(username=username, password='Zq7!tR2#vLm9', **extra)
    if role:
        roles.assign_role(user, role)
    return user


class RoleGroupsMigrationTests(TestCase):
    def test_groups_exist_with_expected_permissions(self):
        self.assertEqual(
            set(Group.objects.values_list('name', flat=True)),
            {'Colaborador', 'Editor', 'Administrador'},
        )
        perms = lambda name: set(  # noqa: E731
            Group.objects.get(name=name).permissions.values_list('content_type__app_label', 'codename')
        )
        colaborador, editor, admin = perms('Colaborador'), perms('Editor'), perms('Administrador')
        self.assertIn(('home', 'add_comentario'), colaborador)
        self.assertNotIn(('home', 'add_publicacion'), colaborador)
        self.assertNotIn(('home', 'change_comentario'), colaborador)
        for codename in ('add_publicacion', 'change_publicacion', 'delete_publicacion', 'view_publicacion',
                         'add_categoria', 'change_categoria', 'delete_categoria',
                         'change_comentario', 'delete_comentario'):
            self.assertIn(('home', codename), editor)
        self.assertFalse({p for p in editor if p[0] == 'auth'})
        self.assertTrue(editor < admin)
        for codename in ('add_user', 'change_user', 'delete_user', 'view_user'):
            self.assertIn(('auth', codename), admin)


class RoleHelpersTests(TestCase):
    def test_choices_expose_value_label_description(self):
        self.assertEqual([r.value for r in roles.ROLES], ['colaborador', 'editor', 'administrador'])
        self.assertEqual(roles.ROLES[0].label, 'Colaborador')
        self.assertEqual(roles.ROLES[0].description, 'comenta noticias')

    def test_assign_role_sets_single_group_and_flags(self):
        user = make_user('ana')
        for role, staff, superuser in [('editor', True, False), ('administrador', True, True),
                                       ('colaborador', False, False)]:
            roles.assign_role(user, role)
            user.refresh_from_db()
            self.assertEqual(user.groups.count(), 1)
            self.assertEqual(roles.get_user_role(user).value, role)
            self.assertEqual((user.is_staff, user.is_superuser), (staff, superuser))

    def test_assign_role_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            roles.assign_role(make_user('bob'), 'root')

    def test_get_user_role_anonymous_is_none(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIsNone(roles.get_user_role(AnonymousUser()))

    def test_user_without_group_defaults_to_colaborador(self):
        self.assertEqual(roles.get_user_role(make_user('sin_grupo')).value, 'colaborador')


class UserRoleManagementViewsTests(TestCase):
    def setUp(self):
        self.admin = make_user('admin1', 'administrador')
        self.client.force_login(self.admin)

    def _payload(self, **extra):
        data = {'username': 'nuevo', 'email': 'n@x.com', 'first_name': 'Nu',
                'password1': 'Zq7!tR2#vLm9', 'password2': 'Zq7!tR2#vLm9', 'rol': 'editor'}
        data.update(extra)
        return data

    def test_create_user_assigns_group(self):
        self.client.post(reverse('home:crear_usuario'), self._payload())
        user = User.objects.get(username='nuevo')
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Editor'])
        self.assertTrue(user.is_staff)

    def test_create_user_without_role_defaults_to_colaborador(self):
        self.client.post(reverse('home:crear_usuario'), self._payload(rol=''))
        self.assertEqual(roles.get_user_role(User.objects.get(username='nuevo')).value, 'colaborador')

    def test_edit_user_changes_group(self):
        target = make_user('t1', 'colaborador')
        self.client.post(reverse('home:editar_usuario', args=[target.pk]),
                         {'username': 't1', 'email': '', 'first_name': '', 'rol': 'administrador'})
        target.refresh_from_db()
        self.assertEqual(list(target.groups.values_list('name', flat=True)), ['Administrador'])

    def test_form_renders_roles_from_central_choices(self):
        html = self.client.get(reverse('home:crear_usuario')).content.decode()
        for role in roles.ROLES:
            self.assertIn(f'value="{role.value}"', html)
            self.assertIn(f'{role.label}: {role.description}', html)

    def test_edit_form_preselects_current_role(self):
        target = make_user('t2', 'editor')
        html = self.client.get(reverse('home:editar_usuario', args=[target.pk])).content.decode()
        self.assertRegex(html, r'value="editor"\s+selected')

    def test_user_list_shows_role_label(self):
        make_user('t3', 'editor')
        self.assertContains(self.client.get(reverse('home:crud_usuarios')), 'Editor')


class SignUpRoleTests(TestCase):
    def test_sign_up_assigns_colaborador(self):
        self.client.post(reverse('home:sign_up'), {
            'username': 'nueva', 'email': 'nueva@x.com', 'first_name': 'N',
            'password1': 'Zq7!tR2#vLm9', 'password2': 'Zq7!tR2#vLm9',
        })
        user = User.objects.get(username='nueva')
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Colaborador'])
        self.assertFalse(user.is_staff)

    def test_seed_users_get_roles(self):
        call_command('seed_news', verbosity=0)
        self.assertEqual(roles.get_user_role(User.objects.get(username='lector_demo')).value, 'colaborador')


class SidebarByRoleTests(TestCase):
    def _sidebar(self, role):
        self.client.force_login(make_user(f'u_{role}', role))
        return self.client.get(reverse('home:perfil')).content.decode()

    def test_colaborador_sees_no_management_links(self):
        html = self._sidebar('colaborador')
        for name in ('crud_noticias', 'crud_comentarios', 'crud_categorias', 'crud_usuarios'):
            self.assertNotIn(reverse(f'home:{name}'), html)
        self.assertIn(reverse('home:crud_cambiar_contrasena'), html)

    def test_editor_sees_content_but_not_users(self):
        html = self._sidebar('editor')
        for name in ('crud_noticias', 'crud_comentarios', 'crud_categorias'):
            self.assertIn(reverse(f'home:{name}'), html)
        self.assertNotIn(reverse('home:crud_usuarios'), html)

    def test_administrador_sees_everything(self):
        html = self._sidebar('administrador')
        for name in ('crud_noticias', 'crud_comentarios', 'crud_categorias', 'crud_usuarios'):
            self.assertIn(reverse(f'home:{name}'), html)


class ProtectedViewsTests(TestCase):
    CONTENT_URLS = [
        ('home:crud_noticias', []), ('home:crear_publicacion', []),
        ('home:crud_comentarios', []), ('home:crud_categorias', []),
    ]
    USER_URLS = [('home:crud_usuarios', []), ('home:crear_usuario', [])]

    def _status(self, url_name, args=()):
        return self.client.get(reverse(url_name, args=args)).status_code

    def test_anonymous_is_redirected_to_login(self):
        for name, args in self.CONTENT_URLS + self.USER_URLS:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse('home:login'), response['Location'])

    def test_colaborador_gets_403_everywhere(self):
        self.client.force_login(make_user('c', 'colaborador'))
        for name, args in self.CONTENT_URLS + self.USER_URLS:
            self.assertEqual(self._status(name, args), 403, name)

    def test_colaborador_cannot_mutate(self):
        self.client.force_login(make_user('c', 'colaborador'))
        victim = make_user('v', 'colaborador')
        self.assertEqual(self.client.post(reverse('home:eliminar_usuario', args=[victim.pk])).status_code, 403)
        self.assertTrue(User.objects.filter(pk=victim.pk).exists())
        self.assertEqual(self.client.post(reverse('home:crud_categorias'), {'nombre': 'X'}).status_code, 403)
        self.assertFalse(Categoria.objects.filter(nombre='X').exists())

    def test_editor_manages_content_but_not_users(self):
        self.client.force_login(make_user('e', 'editor'))
        for name, args in self.CONTENT_URLS:
            self.assertEqual(self._status(name, args), 200, name)
        for name, args in self.USER_URLS:
            self.assertEqual(self._status(name, args), 403, name)
        target = make_user('t', 'colaborador')
        self.assertEqual(self._status('home:editar_usuario', [target.pk]), 403)
        self.assertEqual(self.client.post(reverse('home:eliminar_usuario', args=[target.pk])).status_code, 403)

    def test_administrador_accesses_everything(self):
        self.client.force_login(make_user('a', 'administrador'))
        for name, args in self.CONTENT_URLS + self.USER_URLS:
            self.assertEqual(self._status(name, args), 200, name)

    def test_staff_flag_without_permissions_is_not_enough(self):
        self.client.force_login(User.objects.create_user('s', password='x', is_staff=True))
        self.assertEqual(self._status('home:crud_noticias'), 403)


# --- Deployment: health endpoint and env-driven settings helpers ---------------------------------
from unittest import mock  # noqa: E402

from django.core.exceptions import ImproperlyConfigured  # noqa: E402
from django.db.utils import OperationalError  # noqa: E402

from canaco import env  # noqa: E402


class HealthCheckTests(TestCase):
    def test_healthz_returns_ok_when_db_is_reachable(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_healthz_returns_503_when_db_is_down(self):
        with mock.patch('home.views.connection.cursor', side_effect=OperationalError('down')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'error'})

    def test_healthz_does_not_require_login(self):
        self.assertEqual(self.client.get('/healthz/').status_code, 200)


class EnvHelpersTests(TestCase):
    def test_env_bool_parses_truthy_and_falsy_values(self):
        for raw in ('1', 'true', 'True', 'YES', 'on'):
            with mock.patch.dict('os.environ', {'X_FLAG': raw}):
                self.assertTrue(env.env_bool('X_FLAG', False), raw)
        for raw in ('0', 'false', 'no', 'off', ''):
            with mock.patch.dict('os.environ', {'X_FLAG': raw}):
                self.assertFalse(env.env_bool('X_FLAG', True), raw)

    def test_env_bool_uses_default_when_unset(self):
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertTrue(env.env_bool('X_FLAG', True))
            self.assertFalse(env.env_bool('X_FLAG', False))

    def test_env_list_splits_and_strips(self):
        with mock.patch.dict('os.environ', {'X_LIST': ' a.com, b.com ,,c.com '}):
            self.assertEqual(env.env_list('X_LIST'), ['a.com', 'b.com', 'c.com'])

    def test_env_list_default_when_unset_or_empty(self):
        with mock.patch.dict('os.environ', {'X_LIST': ''}):
            self.assertEqual(env.env_list('X_LIST', ['d']), ['d'])
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertEqual(env.env_list('X_LIST'), [])

    def test_production_rejects_insecure_secret_key(self):
        with self.assertRaises(ImproperlyConfigured):
            env.validate_production(debug=False, secret_key=env.INSECURE_SECRET_KEY)

    def test_production_rejects_empty_secret_key(self):
        with self.assertRaises(ImproperlyConfigured):
            env.validate_production(debug=False, secret_key='')

    def test_production_accepts_custom_secret_key(self):
        env.validate_production(debug=False, secret_key='x' * 60)

    def test_debug_allows_insecure_secret_key(self):
        env.validate_production(debug=True, secret_key=env.INSECURE_SECRET_KEY)
