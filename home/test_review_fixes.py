"""Tests for the review-fix batch: URL sanitizing, slug retry, caching, signals."""
from unittest import mock

from django.contrib import admin
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings

from .context_processors import SIDEBAR_CACHE_KEY, SIDEBAR_CACHE_TTL
from .models import Archivo, Categoria, Publicacion
from .sanitize import clean_html, sanitize_queryset
from .test_seo import make_pub

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'review-fixes'}}


class UrlSanitizingTests(TestCase):
    def test_protocol_relative_urls_are_stripped(self):
        self.assertNotIn('evil.com', clean_html('<img src="//evil.com/x.png">'))
        self.assertNotIn('evil.com', clean_html('<a href="//evil.com">x</a>'))
        self.assertNotIn('evil.com', clean_html('<img src="/\\evil.com/x.png">'))

    def test_site_root_and_https_urls_are_kept(self):
        self.assertIn('src="/media/x.png"', clean_html('<img src="/media/x.png">'))
        self.assertIn('src="https://ok.com/x.png"', clean_html('<img src="https://ok.com/x.png">'))
        self.assertIn('href="https://ok.com"', clean_html('<a href="https://ok.com">x</a>'))


class SanitizeQuerysetTests(TestCase):
    def test_cleans_only_dirty_rows_and_returns_count(self):
        clean = make_pub('Limpia')
        dirty = make_pub('Sucia')
        Publicacion.objects.filter(pk=dirty.pk).update(contenido='<p>a</p><script>x</script>')
        self.assertEqual(sanitize_queryset(Publicacion.objects.all()), 1)
        dirty.refresh_from_db()
        clean.refresh_from_db()
        self.assertEqual(dirty.contenido, '<p>a</p>')
        self.assertEqual(clean.contenido, '<p>Contenido</p>')
        self.assertEqual(sanitize_queryset(Publicacion.objects.all()), 0)

    def test_command_invalidates_sidebar_cache(self):
        from django.core.management import call_command
        with mock.patch('home.management.commands.sanitize_publicaciones.invalidate_sidebar_cache') as inv:
            call_command('sanitize_publicaciones', verbosity=0)
        inv.assert_called_once()


class AdminSlugTests(TestCase):
    def test_slug_is_readonly(self):
        self.assertIn('slug', admin.site._registry[Publicacion].readonly_fields)


class SlugRetryTests(TestCase):
    def test_retries_once_on_slug_collision(self):
        from . import models
        real = models.generate_unique_slug
        calls = []

        def racy(model, source, fallback, start=1):
            calls.append(start)
            if len(calls) == 1:
                return 'carrera'  # stale candidate: another request takes it first
            return real(model, source, fallback, start)

        Publicacion.objects.create(titulo='Otra', slug='carrera', resumen='r', contenido='c')
        with mock.patch.object(models, 'generate_unique_slug', racy):
            pub = Publicacion.objects.create(titulo='Carrera', resumen='r', contenido='c')
        self.assertEqual(pub.slug, 'carrera-2')
        self.assertEqual(len(calls), 2)

    def test_unrelated_integrity_error_is_not_swallowed(self):
        with mock.patch('django.db.models.Model.save', side_effect=IntegrityError('boom')):
            with self.assertRaises(IntegrityError):
                Categoria(nombre='X').save()


class CanonicalTests(TestCase):
    def test_latest_noticia_canonicalizes_to_slug_url(self):
        make_pub('Ultima nota')
        html = self.client.get('/noticia/').content.decode()
        self.assertIn('<link rel="canonical" href="http://testserver/noticia/ultima-nota/">', html)
        self.assertIn('<meta property="og:url" content="http://testserver/noticia/ultima-nota/">', html)


class VaryHeaderTests(TestCase):
    def test_categoria_full_and_partial_vary_on_requested_with(self):
        make_pub('Una')
        full = self.client.get('/categoria/')
        partial = self.client.get('/categoria/', {'page': 1}, HTTP_X_REQUESTED_WITH='fetch')
        empty = self.client.get('/categoria/', {'page': 9}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertIn('X-Requested-With', empty['Vary'])
        self.assertIn('X-Requested-With', full['Vary'])
        self.assertIn('X-Requested-With', partial['Vary'])


class CacheConfigTests(TestCase):
    def test_sidebar_ttl_is_short(self):
        self.assertEqual(SIDEBAR_CACHE_TTL, 60)

    @override_settings(CACHES=LOCMEM)
    def test_archivo_changes_invalidate_sidebar_cache(self):
        cache.set(SIDEBAR_CACHE_KEY, {'x': 1})
        archivo = Archivo.objects.create(nombre='a', nombre_temporal='a', tipo='image/png', tamano=1)
        self.assertIsNone(cache.get(SIDEBAR_CACHE_KEY))
        cache.set(SIDEBAR_CACHE_KEY, {'x': 1})
        archivo.delete()
        self.assertIsNone(cache.get(SIDEBAR_CACHE_KEY))
