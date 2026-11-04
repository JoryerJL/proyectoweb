from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 3/3: every row has a slug now, so make the column required and unique."""

    dependencies = [
        ('home', '0006_backfill_slugs'),
    ]

    operations = [
        migrations.AlterField(
            model_name='categoria',
            name='slug',
            field=models.SlugField(max_length=220, unique=True, blank=True),
        ),
        migrations.AlterField(
            model_name='publicacion',
            name='slug',
            field=models.SlugField(max_length=220, unique=True, blank=True),
        ),
    ]
