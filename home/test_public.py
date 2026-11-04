"""Tests for the public site and the POST-only delete actions."""
import re

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from . import roles
from .models import Categoria, Comentario, Publicacion
from .tests import make_user


def publish(titulo, resumen='resumen', estado=Publicacion.ESTADO_PUBLICADO, **extra):
    autor, _ = User.objects.get_or_create(username='autor')
    return Publicacion.objects.create(
        titulo=titulo, resumen=resumen, contenido='<p>c</p>', estado=estado, autor=autor, **extra,
    )


def listed_titles(response):
    # The footer also lists recent posts, so only look at the list rows.
    return re.findall(r'<h2><a href="[^"]*">([^<]*)</a></h2>', response.content.decode())


class IndexTests(TestCase):
    def test_renders_published_only(self):
        publish('Visible uno')
        publish('Oculta', estado=Publicacion.ESTADO_BORRADOR)
        response = self.client.get(reverse('home:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Visible uno')
        self.assertNotContains(response, 'Oculta')

    def test_renders_without_content(self):
        self.assertEqual(self.client.get(reverse('home:index')).status_code, 200)


class NoticiaDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pub = publish('Detalle publicado')
        cls.draft = publish('Detalle borrador', estado=Publicacion.ESTADO_BORRADOR)
        cls.user = make_user('lector')

    def url(self, pk=None):
        if pk:
            return reverse('home:noticia_pk', args=[pk])
        return self.pub.get_absolute_url()

    def test_published_detail_is_ok(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detalle publicado')

    def test_missing_and_draft_are_404(self):
        self.assertEqual(self.client.get(self.url(999999)).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.draft.pk)).status_code, 404)

    def test_get_increments_visits(self):
        before = Publicacion.objects.get(pk=self.pub.pk).visitas
        self.client.get(self.url())
        self.assertGreater(Publicacion.objects.get(pk=self.pub.pk).visitas, before)

    def test_visits_increment_once_per_get(self):
        before = Publicacion.objects.get(pk=self.pub.pk).visitas
        self.client.get(self.url())
        self.assertEqual(Publicacion.objects.get(pk=self.pub.pk).visitas, before + 1)

    def test_comment_is_pending_and_hidden_until_approved(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url(), {'contenido': 'Mi comentario pendiente'})
        self.assertRedirects(response, self.url())
        comment = Comentario.objects.get()
        self.assertEqual(comment.estado, Comentario.ESTADO_PENDIENTE)
        self.assertEqual(comment.user, self.user)
        self.assertNotContains(self.client.get(self.url()), 'Mi comentario pendiente')

        comment.estado = Comentario.ESTADO_APROBADO
        comment.save()
        self.assertContains(self.client.get(self.url()), 'Mi comentario pendiente')

    def test_blocked_comment_is_hidden(self):
        Comentario.objects.create(publicacion=self.pub, user=self.user, contenido='Bloqueado ya',
                                  estado=Comentario.ESTADO_BLOQUEADO)
        self.assertNotContains(self.client.get(self.url()), 'Bloqueado ya')

    def test_anonymous_cannot_comment(self):
        self.client.post(self.url(), {'contenido': 'anon'})
        self.assertEqual(Comentario.objects.count(), 0)


class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        publish('Feria del Libro', resumen='Evento cultural')
        publish('Otra cosa', resumen='Hablamos de FERIA en el resumen')
        publish('Sin relacion', resumen='nada')
        publish('Feria borrador', estado=Publicacion.ESTADO_BORRADOR)

    def test_matches_title_and_summary_icontains(self):
        response = self.client.get(reverse('home:categoria'), {'q': 'feria'})
        self.assertEqual(sorted(listed_titles(response)), ['Feria del Libro', 'Otra cosa'])


class HealthzTests(TestCase):
    def test_ok(self):
        self.assertEqual(self.client.get(reverse('home:healthz')).status_code, 200)


class DeleteActionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user('admin', roles.ADMINISTRADOR)
        cls.cat = Categoria.objects.create(nombre='Borrar')
        cls.pub = publish('Borrar pub')
        cls.victim = make_user('victima')
        cls.comment = Comentario.objects.create(publicacion=cls.pub, user=cls.victim, contenido='x')

    def targets(self):
        return [
            ('home:eliminar_publicacion', self.pub, Publicacion),
            ('home:eliminar_comentario', self.comment, Comentario),
            ('home:eliminar_categoria', self.cat, Categoria),
            ('home:eliminar_usuario', self.victim, type(self.victim)),
        ]

    def test_get_is_not_allowed_and_deletes_nothing(self):
        self.client.force_login(self.admin)
        for name, obj, model in self.targets():
            self.assertEqual(self.client.get(reverse(name, args=[obj.pk])).status_code, 405, name)
            self.assertTrue(model.objects.filter(pk=obj.pk).exists(), name)

    def test_post_without_csrf_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        for name, obj, _ in self.targets():
            self.assertEqual(client.post(reverse(name, args=[obj.pk])).status_code, 403, name)

    def test_post_deletes(self):
        self.client.force_login(self.admin)
        for name, obj, model in self.targets():
            self.client.post(reverse(name, args=[obj.pk]))
            self.assertFalse(model.objects.filter(pk=obj.pk).exists(), name)
