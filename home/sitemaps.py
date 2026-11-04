from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Categoria, Publicacion


class PublicacionSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Publicacion.objects.filter(estado=Publicacion.ESTADO_PUBLICADO).order_by('-createdat')

    def lastmod(self, obj):
        return obj.updatedat


class CategoriaSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        return Categoria.objects.order_by('nombre')

    def lastmod(self, obj):
        return obj.updatedat


class StaticSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.3

    def items(self):
        return ['home:index', 'home:categoria', 'home:contactanos']

    def location(self, item):
        return reverse(item)


sitemaps = {
    'noticias': PublicacionSitemap,
    'categorias': CategoriaSitemap,
    'paginas': StaticSitemap,
}
