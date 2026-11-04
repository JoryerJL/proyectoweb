from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 1/3: add nullable, non-unique slug columns so existing rows stay valid."""

    dependencies = [
        ('home', '0004_mensajecontacto'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoria',
            name='slug',
            field=models.SlugField(max_length=220, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='publicacion',
            name='slug',
            field=models.SlugField(max_length=220, null=True, blank=True),
        ),
    ]
