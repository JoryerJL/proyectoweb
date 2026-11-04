from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = (
        'Delete self-registered accounts that never verified their email and never logged in, '
        'once they are older than --days.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7, help='Minimum account age in days (default: 7).')

    def handle(self, *args, **options):
        days = options['days']
        if days < 0:
            raise CommandError('--days must be zero or greater.')
        cutoff = timezone.now() - timedelta(days=days)
        stale = User.objects.filter(
            perfil__email_verificado=False,
            date_joined__lt=cutoff,
            last_login__isnull=True,
        )
        count = stale.count()
        stale.delete()
        self.stdout.write(self.style.SUCCESS(f'Removed {count} unverified account(s) older than {days} day(s).'))
