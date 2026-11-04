"""Tests for the hardening batch: sanitizing, POST-only actions, admin, queries."""
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import roles
from .context_processors import global_categorias
from .models import Archivo, Categoria, Comentario, GaleriaPublicacion, Perfil, Publicacion
from .sanitize import clean_html
from .tests import make_user

MALICIOUS = (
    '<p class="ql-align-center"><strong>ok</strong></p>'
    '<script>alert(1)</script>'
    '<img src=x onerror=alert(1)>'
    '<a href="javascript:alert(1)">click</a>'
)


def assert_clean(testcase, html):
    lowered = html.lower()
    for needle in ('<script', 'onerror', 'javascript:'):
        testcase.assertNotIn(needle, lowered)
    testcase.assertIn('<p class="ql-align-center"><strong>ok</strong></p>', html)


class CleanHtmlTests(TestCase):
    def test_strips_dangerous_markup_and_keeps_quill_output(self):
        assert_clean(self, clean_html(MALICIOUS))

    def test_keeps_allowed_attributes(self):
        html = '<ol><li data-list="bullet" class="ql-indent-1">x</li></ol>'
        self.assertEqual(clean_html(html), html)
        self.assertIn('src="https://a.test/i.png"', clean_html('<img src="https://a.test/i.png" alt="a">'))

    def test_links_get_rel_noopener(self):
        out = clean_html('<a href="https://a.test" target="_blank">x</a>')
        self.assertIn('rel="noopener noreferrer"', out)

    def test_is_idempotent(self):
        once = clean_html(MALICIOUS)
        self.assertEqual(clean_html(once), once)


class PublicationSanitizingTests(TestCase):
    def setUp(self):
        self.editor = make_user('editor', roles.EDITOR)
        self.client.force_login(self.editor)

    def _payload(self, contenido):
        return {'titulo': 't', 'resumen': 'r', 'contenido': contenido, 'estado': 'borrador'}

    def test_create_sanitizes_content(self):
        self.client.post(reverse('home:crear_publicacion'), self._payload(MALICIOUS))
        assert_clean(self, Publicacion.objects.get().contenido)

    def test_edit_sanitizes_content(self):
        pub = Publicacion.objects.create(titulo='t', resumen='r', contenido='x')
        self.client.post(reverse('home:editar_publicacion', args=[pub.pk]), self._payload(MALICIOUS))
        pub.refresh_from_db()
        assert_clean(self, pub.contenido)


class SanitizeCommandTests(TestCase):
    def test_cleans_existing_rows_and_is_idempotent(self):
        pub = Publicacion.objects.create(titulo='t', resumen='r', contenido='x')
        Publicacion.objects.filter(pk=pub.pk).update(contenido=MALICIOUS)

        call_command('sanitize_publicaciones', verbosity=0)
        pub.refresh_from_db()
        assert_clean(self, pub.contenido)
        first = pub.contenido

        call_command('sanitize_publicaciones', verbosity=0)
        pub.refresh_from_db()
        self.assertEqual(pub.contenido, first)


class PostOnlyActionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('boss', roles.ADMINISTRADOR)
        cls.victim = make_user('victim')
        cls.pub = Publicacion.objects.create(titulo='t', resumen='r', contenido='c')
        cls.comment = Comentario.objects.create(publicacion=cls.pub, user=cls.victim, contenido='hi')

    def endpoints(self):
        return [
            reverse('home:publicar_publicacion', args=[self.pub.pk]),
            reverse('home:aprobar_comentario', args=[self.comment.pk]),
            reverse('home:bloquear_comentario', args=[self.comment.pk]),
            reverse('home:bloquear_usuario', args=[self.victim.pk]),
        ]

    def test_get_is_not_allowed(self):
        self.client.force_login(self.admin)
        for url in self.endpoints():
            self.assertEqual(self.client.get(url).status_code, 405, url)

    def test_post_without_csrf_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for url in self.endpoints():
            self.assertEqual(client.post(url).status_code, 403, url)

    def test_post_changes_state(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('home:publicar_publicacion', args=[self.pub.pk]))
        self.pub.refresh_from_db()
        self.assertEqual(self.pub.estado, Publicacion.ESTADO_PUBLICADO)

        self.client.post(reverse('home:aprobar_comentario', args=[self.comment.pk]))
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.estado, Comentario.ESTADO_APROBADO)

        self.client.post(reverse('home:bloquear_comentario', args=[self.comment.pk]))
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.estado, Comentario.ESTADO_BLOQUEADO)

        self.client.post(reverse('home:bloquear_usuario', args=[self.victim.pk]))
        self.victim.refresh_from_db()
        self.assertFalse(self.victim.is_active)

    def test_post_requires_permission(self):
        self.client.force_login(self.victim)
        for url in self.endpoints():
            self.assertEqual(self.client.post(url).status_code, 403, url)

    def test_panel_renders_forms_not_links(self):
        self.client.force_login(self.admin)
        for name, url in [('publicar', 'home:crud_noticias'), ('aprobar', 'home:crud_comentarios'),
                          ('bloquear', 'home:crud_usuarios')]:
            html = self.client.get(reverse(url)).content.decode()
            self.assertRegex(html, rf'<form method="post" action="[^"]*{name}/"', name)
            self.assertNotRegex(html, rf'<a href="[^"]*{name}/"', name)


class AdminRegistrationTests(TestCase):
    def test_models_are_registered(self):
        for model in (Publicacion, Categoria, Comentario, Archivo, Perfil, GaleriaPublicacion):
            self.assertTrue(admin.site.is_registered(model), model.__name__)

    def test_changelists_render(self):
        superuser = User.objects.create_superuser('root', password='pass12345')
        self.client.force_login(superuser)
        for model in (Publicacion, Categoria, Comentario, Archivo, Perfil, GaleriaPublicacion):
            url = reverse(f'admin:home_{model._meta.model_name}_changelist')
            self.assertEqual(self.client.get(url).status_code, 200, model.__name__)


LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'hardening-tests'}}


@override_settings(CACHES=LOCMEM)
class GlobalCategoriasCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.request = RequestFactory().get('/')

    def test_second_call_hits_cache(self):
        Categoria.objects.create(nombre='A')
        global_categorias(self.request)
        with self.assertNumQueries(0):
            global_categorias(self.request)

    def test_category_changes_invalidate_cache(self):
        cat = Categoria.objects.create(nombre='A')
        self.assertEqual([c.nombre for c in global_categorias(self.request)['global_categorias']], ['A'])

        Categoria.objects.create(nombre='B')
        self.assertEqual([c.nombre for c in global_categorias(self.request)['global_categorias']], ['A', 'B'])

        cat.delete()
        self.assertEqual([c.nombre for c in global_categorias(self.request)['global_categorias']], ['B'])

    def test_publication_changes_invalidate_counts_and_recent(self):
        cat = Categoria.objects.create(nombre='A')
        self.assertEqual(global_categorias(self.request)['global_categorias'][0].total, 0)

        Publicacion.objects.create(titulo='t', resumen='r', contenido='c', categoria=cat,
                                   estado=Publicacion.ESTADO_PUBLICADO)
        ctx = global_categorias(self.request)
        self.assertEqual(ctx['global_categorias'][0].total, 1)
        self.assertEqual(len(ctx['global_recientes']), 1)


class QueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.create(nombre='Comercio')
        cls.user = make_user('autor')
        cls.pubs = []
        for i in range(4):
            portada = Archivo.objects.create(nombre=f'p{i}.jpg', nombre_temporal=f'p{i}.jpg', ruta=f'images/p{i}.jpg')
            pub = Publicacion.objects.create(
                titulo=f'T{i}', resumen='r', contenido='<p>c</p>', categoria=cls.cat, autor=cls.user,
                imagen_portada=portada, estado=Publicacion.ESTADO_PUBLICADO,
            )
            for j in range(3):
                arch = Archivo.objects.create(nombre=f'g{i}{j}.jpg', nombre_temporal='g', ruta=f'images/g{i}{j}.jpg')
                GaleriaPublicacion.objects.create(publicacion=pub, archivo=arch)
            Comentario.objects.create(publicacion=pub, user=cls.user, contenido='x',
                                      estado=Comentario.ESTADO_APROBADO)
            cls.pubs.append(pub)

    def _queries_for(self, url):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx)

    def test_noticia_detail_has_no_n_plus_one(self):
        url = self.pubs[0].get_absolute_url()
        with self.assertNumQueries(NOTICIA_QUERIES):
            self.client.get(url)

    def test_noticia_queries_do_not_grow_with_gallery(self):
        url = self.pubs[0].get_absolute_url()
        before = self._queries_for(url)
        for j in range(5):
            arch = Archivo.objects.create(nombre=f'x{j}.jpg', nombre_temporal='g', ruta=f'images/x{j}.jpg')
            GaleriaPublicacion.objects.create(publicacion=self.pubs[0], archivo=arch)
        self.assertEqual(self._queries_for(url), before)

    def test_categoria_list_has_no_n_plus_one(self):
        url = self.cat.get_absolute_url()
        with self.assertNumQueries(CATEGORIA_QUERIES):
            self.client.get(url)

    def test_crud_usuarios_queries_do_not_grow_with_users(self):
        self.client.force_login(make_user('boss', roles.ADMINISTRADOR))
        url = reverse('home:crud_usuarios')
        before = self._queries_for(url)
        for i in range(5):
            make_user(f'extra{i}', roles.EDITOR)
        self.assertEqual(self._queries_for(url), before)

    def test_crud_usuarios_creates_missing_profiles(self):
        self.client.force_login(make_user('boss', roles.ADMINISTRADOR))
        Perfil.objects.all().delete()
        self.client.get(reverse('home:crud_usuarios'))
        self.assertEqual(Perfil.objects.count(), User.objects.count())


# Detail: publication+gallery (2), visit counter (1), comments (1), sidebar (2), recent posts (1).
NOTICIA_QUERIES = 7
# List: category (1), posts (1), sidebar (2); the cache is disabled under tests.
CATEGORIA_QUERIES = 5  # includes the COUNT(*) issued by the paginator


class IndexesTests(TestCase):
    def test_model_indexes_declared(self):
        pub_fields = [tuple(i.fields) for i in Publicacion._meta.indexes]
        self.assertIn(('estado', '-createdat'), pub_fields)
        self.assertIn(('categoria',), pub_fields)
        self.assertIn(('estado',), [tuple(i.fields) for i in Comentario._meta.indexes])
