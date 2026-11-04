from django.contrib.sites.models import Site
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Categoria, Publicacion


def make_pub(titulo='Feria del comercio', estado=Publicacion.ESTADO_PUBLICADO, **kwargs):
    kwargs.setdefault('resumen', 'Resumen de la nota')
    kwargs.setdefault('contenido', '<p>Contenido</p>')
    return Publicacion.objects.create(titulo=titulo, estado=estado, **kwargs)


class SlugTests(TestCase):
    def test_slug_generated_from_title(self):
        pub = make_pub('Feria del Comercio 2026')
        self.assertEqual(pub.slug, 'feria-del-comercio-2026')

    def test_duplicate_titles_get_numeric_suffix(self):
        first = make_pub('Mismo titulo')
        second = make_pub('Mismo titulo')
        third = make_pub('Mismo titulo')
        self.assertEqual([first.slug, second.slug, third.slug], ['mismo-titulo', 'mismo-titulo-2', 'mismo-titulo-3'])

    def test_editing_title_keeps_slug(self):
        pub = make_pub('Titulo original')
        pub.titulo = 'Titulo totalmente distinto'
        pub.save()
        pub.refresh_from_db()
        self.assertEqual(pub.slug, 'titulo-original')

    def test_purely_numeric_title_does_not_collide_with_pk_route(self):
        pub = make_pub('2026')
        self.assertFalse(pub.slug.isdigit())

    def test_title_without_sluggable_chars_gets_fallback(self):
        pub = make_pub('???')
        self.assertTrue(pub.slug)

    def test_categoria_slug_generated_and_stable(self):
        cat = Categoria.objects.create(nombre='Economía Local')
        other = Categoria.objects.create(nombre='Economia local')
        self.assertEqual(cat.slug, 'economia-local')
        self.assertEqual(other.slug, 'economia-local-2')
        cat.nombre = 'Otro nombre'
        cat.save()
        cat.refresh_from_db()
        self.assertEqual(cat.slug, 'economia-local')


class RoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.create(nombre='Eventos')
        cls.pub = make_pub('Gran evento', categoria=cls.cat)
        cls.draft = make_pub('Borrador secreto', estado=Publicacion.ESTADO_BORRADOR)

    def test_get_absolute_url(self):
        self.assertEqual(self.pub.get_absolute_url(), '/noticia/gran-evento/')
        self.assertEqual(self.cat.get_absolute_url(), '/categoria/eventos/')

    def test_slug_urls_return_200(self):
        self.assertEqual(self.client.get('/noticia/gran-evento/').status_code, 200)
        self.assertEqual(self.client.get('/categoria/eventos/').status_code, 200)

    def test_old_pk_urls_redirect_permanently(self):
        response = self.client.get(f'/noticia/{self.pub.pk}/')
        self.assertRedirects(response, '/noticia/gran-evento/', status_code=301)
        response = self.client.get(f'/categoria/{self.cat.pk}/')
        self.assertRedirects(response, '/categoria/eventos/', status_code=301)

    def test_old_pk_url_of_unknown_or_draft_is_404(self):
        self.assertEqual(self.client.get('/noticia/999999/').status_code, 404)
        self.assertEqual(self.client.get(f'/noticia/{self.draft.pk}/').status_code, 404)
        self.assertEqual(self.client.get('/categoria/999999/').status_code, 404)

    def test_draft_slug_is_404_for_visitors(self):
        self.assertEqual(self.client.get('/noticia/borrador-secreto/').status_code, 404)

    def test_comment_post_redirects_to_slug_url(self):
        response = self.client.post('/noticia/gran-evento/', {'contenido': 'hola'})
        self.assertRedirects(response, reverse('home:login'), fetch_redirect_response=False)

    def test_category_select_has_no_inline_js(self):
        html = self.client.get('/categoria/eventos/').content.decode()
        self.assertNotIn('onchange=', html)
        self.assertIn('data-category-select', html)
        self.assertIn('value="/categoria/eventos/" selected', html)


class SeoTagsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pub = make_pub('Nota con SEO', resumen='<script>alert(1)</script><b>Texto</b> del resumen')

    def test_noticia_has_canonical_and_open_graph(self):
        html = self.client.get('/noticia/nota-con-seo/').content.decode()
        self.assertIn('<link rel="canonical" href="http://testserver/noticia/nota-con-seo/">', html)
        self.assertIn('<meta property="og:title" content="Nota con SEO">', html)
        self.assertIn('<meta property="og:type" content="article">', html)
        self.assertIn('<meta property="og:url" content="http://testserver/noticia/nota-con-seo/">', html)
        self.assertIn('<meta name="twitter:card"', html)

    def test_meta_description_has_no_html(self):
        html = self.client.get('/noticia/nota-con-seo/').content.decode()
        description = next(line for line in html.splitlines() if 'name="description"' in line)
        self.assertNotIn('<b>', description)
        self.assertNotIn('<script', description)
        self.assertIn('Texto', description)

    def test_og_image_only_when_cover_exists(self):
        html = self.client.get('/noticia/nota-con-seo/').content.decode()
        self.assertNotIn('og:image', html)

    def test_index_and_categoria_have_canonical(self):
        for path in ['/', '/categoria/']:
            html = self.client.get(path).content.decode()
            self.assertIn(f'<link rel="canonical" href="http://testserver{path}">', html)
            self.assertIn('property="og:title"', html)


class SitemapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.create(nombre='Cultura')
        make_pub('Nota publicada', categoria=cls.cat)
        make_pub('Nota borrador', estado=Publicacion.ESTADO_BORRADOR)

    def test_sitemap_lists_published_posts_only(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('/noticia/nota-publicada/', body)
        self.assertNotIn('nota-borrador', body)

    def test_sitemap_lists_categories_and_static_pages(self):
        body = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('/categoria/cultura/', body)
        self.assertIn('/contactanos/', body)

    def test_set_site_domain_command(self):
        call_command('set_site_domain', 'canaco.example.org')
        self.assertEqual(Site.objects.get_current().domain, 'canaco.example.org')
        self.assertIn('canaco.example.org', self.client.get('/sitemap.xml').content.decode())


class RobotsTests(TestCase):
    def test_robots_txt(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/plain'))
        body = response.content.decode()
        self.assertIn('User-agent: *', body)
        self.assertIn('Disallow: /panel/', body)
        self.assertIn('Disallow: /admin/', body)
        self.assertIn('Sitemap: http://testserver/sitemap.xml', body)
