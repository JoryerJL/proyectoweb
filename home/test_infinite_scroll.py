"""Tests for the paginated news list used by infinite scroll."""
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from .models import Categoria, Publicacion

PARTIAL = {'HTTP_X_REQUESTED_WITH': 'fetch'}


def article_count(response):
    return response.content.decode().count('<article class="post-row">')


class NewsPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.create(nombre='Comercio')
        cls.other = Categoria.objects.create(nombre='Otros')
        for i in range(20):
            Publicacion.objects.create(
                titulo=f'Noticia {i}', resumen='resumen', contenido='<p>c</p>',
                categoria=cls.cat, estado=Publicacion.ESTADO_PUBLICADO,
            )
        Publicacion.objects.create(titulo='Borrador oculto', resumen='r', contenido='c', categoria=cls.cat)
        cls.url = reverse('home:categoria')

    def test_page_size_setting(self):
        self.assertEqual(settings.NEWS_PAGE_SIZE, 9)

    def test_first_page_has_nine_and_next_link(self):
        response = self.client.get(self.url)
        self.assertEqual(article_count(response), 9)
        self.assertContains(response, 'data-infinite-more href="?page=2"')
        self.assertContains(response, 'data-infinite-scroll')
        self.assertContains(response, '20 noticias')

    def test_second_page(self):
        response = self.client.get(self.url, {'page': 2})
        self.assertEqual(article_count(response), 9)
        self.assertContains(response, 'href="?page=3"')

    def test_last_page_has_no_next_link(self):
        response = self.client.get(self.url, {'page': 3})
        self.assertEqual(article_count(response), 2)
        self.assertNotContains(response, 'data-infinite-more')
        self.assertNotContains(response, 'data-infinite-sentinel')

    def test_out_of_range_full_request_clamps(self):
        response = self.client.get(self.url, {'page': 99})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(article_count(response), 2)
        garbage = self.client.get(self.url, {'page': 'abc'})
        self.assertEqual(article_count(garbage), 9)

    def test_ordering_is_stable_newest_first(self):
        first = self.client.get(self.url).content.decode()
        self.assertLess(first.index('Noticia 19'), first.index('Noticia 11'))
        self.assertNotIn('Noticia 10<', first)

    def test_partial_returns_only_articles(self):
        response = self.client.get(self.url, {'page': 2}, **PARTIAL)
        body = response.content.decode()
        self.assertEqual(article_count(response), 9)
        self.assertNotIn('<html', body)
        self.assertNotIn('data-infinite-scroll', body)
        self.assertEqual(response['X-Has-Next'], 'true')
        self.assertEqual(response['X-Next-Url'], '?page=3')

    def test_partial_query_param_is_supported(self):
        response = self.client.get(self.url, {'page': 3, 'partial': 1})
        self.assertNotIn('<html', response.content.decode())
        self.assertEqual(article_count(response), 2)
        self.assertEqual(response['X-Has-Next'], 'false')
        self.assertNotIn('X-Next-Url', response)

    def test_partial_out_of_range_is_empty(self):
        response = self.client.get(self.url, {'page': 99}, **PARTIAL)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['X-Has-Next'], 'false')
        self.assertEqual(article_count(response), 0)
        self.assertEqual(self.client.get(self.url, {'page': 'abc'}, **PARTIAL).status_code, 204)

    def test_search_is_preserved_in_next_url(self):
        response = self.client.get(self.url, {'q': 'Noticia'})
        self.assertContains(response, 'href="?q=Noticia&amp;page=2"')
        partial = self.client.get(self.url, {'q': 'Noticia', 'page': 2}, **PARTIAL)
        self.assertEqual(partial['X-Next-Url'], '?q=Noticia&page=3')

    def test_search_is_urlencoded(self):
        response = self.client.get(self.url, {'q': 'a b&c'})
        self.assertEqual(response.status_code, 200)
        partial = self.client.get(self.url, {'q': 'Noticia 1', 'page': 1}, **PARTIAL)
        self.assertEqual(partial['X-Next-Url'], '?q=Noticia+1&page=2')

    def test_category_filter_is_preserved(self):
        url = self.cat.get_absolute_url()
        response = self.client.get(url)
        self.assertEqual(article_count(response), 9)
        self.assertContains(response, 'href="?page=2"')
        self.assertEqual(self.client.get(url, {'page': 2}, **PARTIAL)['X-Next-Url'], '?page=3')
        empty = self.other.get_absolute_url()
        self.assertNotContains(self.client.get(empty), 'data-infinite-more')

    def test_drafts_never_appear(self):
        for page in (1, 2, 3):
            response = self.client.get(self.url, {'page': page})
            self.assertNotContains(response, 'Borrador oculto')
        self.assertNotContains(self.client.get(self.url, {'q': 'Borrador'}), 'Borrador oculto')
