import os

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Set the django.contrib.sites domain used in sitemap.xml and robots.txt. '
        'Reads DJANGO_SITE_DOMAIN when no argument is given.'
    )

    def add_arguments(self, parser):
        parser.add_argument('domain', nargs='?', help='Public domain, e.g. canaco.example.org (no scheme).')

    def handle(self, *args, **options):
        domain = (options['domain'] or os.environ.get('DJANGO_SITE_DOMAIN', '')).strip()
        if not domain:
            self.stdout.write('No domain given and DJANGO_SITE_DOMAIN is empty; leaving the site unchanged.')
            return
        if '://' in domain or '/' in domain:
            raise CommandError('Pass only the domain (e.g. example.org), without scheme or path.')
        site, _ = Site.objects.update_or_create(
            pk=settings.SITE_ID, defaults={'domain': domain, 'name': domain},
        )
        self.stdout.write(self.style.SUCCESS(f'Site domain set to {site.domain}'))
