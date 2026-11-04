from django.db import migrations
from django.utils import timezone


def mark_existing_verified(apps, schema_editor):
    """Profiles that predate email verification are trusted, so nobody is locked out on deploy."""
    Perfil = apps.get_model('home', 'Perfil')
    Perfil.objects.filter(email_verificado=False).update(
        email_verificado=True,
        email_verificado_en=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [
        ('home', '0009_perfil_email_verification'),
    ]

    operations = [
        migrations.RunPython(mark_existing_verified, migrations.RunPython.noop),
    ]
