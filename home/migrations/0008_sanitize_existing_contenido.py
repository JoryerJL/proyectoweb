from django.db import migrations

from home.sanitize import sanitize_queryset


def sanitize_existing(apps, schema_editor):
    Publicacion = apps.get_model('home', 'Publicacion')
    sanitize_queryset(Publicacion.objects.all())


class Migration(migrations.Migration):
    """Rows written before sanitizing existed are cleaned once, on deploy."""

    dependencies = [
        ('home', '0007_slug_unique'),
    ]

    operations = [
        migrations.RunPython(sanitize_existing, migrations.RunPython.noop),
    ]
