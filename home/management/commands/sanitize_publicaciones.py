from django.core.management.base import BaseCommand

from home.context_processors import invalidate_sidebar_cache
from home.models import Publicacion
from home.sanitize import sanitize_queryset


class Command(BaseCommand):
    help = 'Re-sanitize the HTML content of every publication (idempotent).'

    def handle(self, *args, **options):
        changed = sanitize_queryset(Publicacion.objects.all())
        invalidate_sidebar_cache()
        self.stdout.write(self.style.SUCCESS(f'Sanitized {changed} publication(s).'))
