from django.db import migrations
from django.db.models import Q
from django.utils.text import slugify

MAX_LENGTH = 220


def _backfill(model, source_field, fallback):
    used = set(model.objects.exclude(slug__isnull=True).exclude(slug='').values_list('slug', flat=True))
    for obj in model.objects.filter(Q(slug__isnull=True) | Q(slug='')).order_by('pk'):
        base = slugify(getattr(obj, source_field))[: MAX_LENGTH - 10].strip('-') or fallback
        if base.isdigit():
            base = f'{base}-{fallback}'
        slug, n = base, 1
        while slug in used:
            n += 1
            slug = f'{base}-{n}'
        used.add(slug)
        model.objects.filter(pk=obj.pk).update(slug=slug)


def backfill_slugs(apps, schema_editor):
    _backfill(apps.get_model('home', 'Categoria'), 'nombre', 'categoria')
    _backfill(apps.get_model('home', 'Publicacion'), 'titulo', 'noticia')


class Migration(migrations.Migration):
    """Step 2/3: fill slugs for existing rows (de-duplicated, oldest row keeps the clean slug)."""

    dependencies = [
        ('home', '0005_add_slug_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
    ]
