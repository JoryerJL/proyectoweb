from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from home.sitemaps import sitemaps

urlpatterns = [
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots'),
    path('', include('home.urls')),
    path('admin/', admin.site.urls),
    # In production /media/ is served by nginx from a shared volume; this helper only works with DEBUG on.
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

