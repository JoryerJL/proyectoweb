from django.contrib.auth.models import User
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils.text import slugify

from .sanitize import clean_html

SLUG_MAX_LENGTH = 220


def save_with_unique_slug(instance, model, source, fallback, save):
    """Run ``save`` and retry once if a concurrent insert took the same slug."""
    instance.slug = generate_unique_slug(model, source, fallback)
    try:
        with transaction.atomic():
            save()
    except IntegrityError:
        if not model.objects.filter(slug=instance.slug).exists():
            raise
        # Skip past the slug that just lost the race.
        n = int(instance.slug.rsplit('-', 1)[-1]) + 1 if instance.slug.rsplit('-', 1)[-1].isdigit() else 2
        instance.slug = generate_unique_slug(model, source, fallback, start=n)
        save()


def generate_unique_slug(model, source, fallback, start=1):
    """Return a slug for ``source`` that no other ``model`` row uses.

    Collisions get a ``-2``, ``-3``... suffix. A purely numeric slug would be
    swallowed by the legacy ``<int:pk>`` redirect routes, so it gets a suffix too.
    """
    base = slugify(source)[: SLUG_MAX_LENGTH - 10].strip('-') or fallback
    if base.isdigit():
        base = f'{base}-{fallback}'
    slug, n = base, start
    if n > 1:
        slug = f'{base}-{n}'
    while model.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    return slug


class Categoria(models.Model):
    id = models.BigAutoField(
        auto_created=True,
        primary_key=True,
        serialize=False,
        verbose_name='ID',
    )
    nombre = models.CharField(max_length=60)
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, unique=True, blank=True)
    createdat = models.DateTimeField(auto_now_add=True)
    updatedat = models.DateTimeField(null=True, blank=True)
    fk_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        managed = True
        db_table = 'categoria'
        verbose_name_plural = 'Categoria'

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        # Generated once: the slug never changes on edit so public URLs stay stable.
        if not self.slug:
            save_with_unique_slug(
                self, Categoria, self.nombre, 'categoria', lambda: super(Categoria, self).save(*args, **kwargs),
            )
        else:
            super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('home:categoria_detalle', kwargs={'slug': self.slug})


class Archivo(models.Model):
    nombre = models.CharField(max_length=255)
    nombre_temporal = models.CharField(max_length=255)
    ruta = models.FileField(upload_to='uploads/')
    tipo = models.CharField(max_length=100, blank=True)
    tamano = models.PositiveIntegerField(default=0)
    fk_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    createdat = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'archivo'
        verbose_name_plural = 'Archivo'

    def __str__(self):
        return self.nombre

    @property
    def display_url(self):
        ruta = str(self.ruta)
        if ruta.startswith(('images/', 'css/', 'js/', 'fonts/', 'uploads/profile-default')):
            return f'/static/{ruta}'
        return self.ruta.url


class Perfil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    foto_perfil = models.ForeignKey(Archivo, null=True, blank=True, on_delete=models.SET_NULL)
    apellido_paterno = models.CharField(max_length=80, blank=True)
    apellido_materno = models.CharField(max_length=80, blank=True)
    # Separate from User.is_active, which the panel uses to block accounts.
    # Defaults to True so profiles created by any path (get_or_create, admin, ORM) never lock anyone out;
    # only SignUpForm.save marks a self-registered account as unverified.
    email_verificado = models.BooleanField(default=True)
    email_verificado_en = models.DateTimeField(null=True, blank=True)
    verificacion_enviada_en = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Perfil de {self.user.username}'


class Publicacion(models.Model):
    ESTADO_BORRADOR = 'borrador'
    ESTADO_PUBLICADO = 'publicado'

    ESTADOS = [
        (ESTADO_BORRADOR, 'Borrador'),
        (ESTADO_PUBLICADO, 'Publicado'),
    ]

    titulo = models.CharField(max_length=180)
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, unique=True, blank=True)
    resumen = models.TextField()
    contenido = models.TextField()
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    imagen_portada = models.ForeignKey(
        Archivo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='portadas',
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ESTADO_BORRADOR)
    visitas = models.PositiveIntegerField(default=0)
    createdat = models.DateTimeField(auto_now_add=True)
    updatedat = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'publicacion'
        verbose_name_plural = 'Publicaciones'
        indexes = [
            models.Index(fields=['estado', '-createdat'], name='publicacion_estado_created_idx'),
            models.Index(fields=['categoria'], name='publicacion_categoria_idx'),
            models.Index(fields=['createdat'], name='publicacion_createdat_idx'),
        ]

    def __str__(self):
        return self.titulo

    def save(self, *args, **kwargs):
        # Quill HTML is rendered with |safe, so it is sanitized on every write.
        self.contenido = clean_html(self.contenido)
        # Generated once: the slug never changes on edit so public URLs stay stable.
        if not self.slug:
            save_with_unique_slug(
                self, Publicacion, self.titulo, 'noticia', lambda: super(Publicacion, self).save(*args, **kwargs),
            )
        else:
            super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('home:noticia_detalle', kwargs={'slug': self.slug})


class GaleriaPublicacion(models.Model):
    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='galeria')
    archivo = models.ForeignKey(Archivo, on_delete=models.CASCADE)
    createdat = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'galeria_publicacion'
        verbose_name_plural = 'Galeria de publicaciones'


class Comentario(models.Model):
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_APROBADO = 'aprobado'
    ESTADO_BLOQUEADO = 'bloqueado'

    ESTADOS = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_APROBADO, 'Aprobado'),
        (ESTADO_BLOQUEADO, 'Bloqueado'),
    ]

    publicacion = models.ForeignKey(Publicacion, on_delete=models.CASCADE, related_name='comentarios')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    contenido = models.TextField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ESTADO_PENDIENTE)
    createdat = models.DateTimeField(auto_now_add=True)
    updatedat = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = 'comentario'
        verbose_name_plural = 'Comentarios'
        indexes = [
            models.Index(fields=['estado'], name='comentario_estado_idx'),
        ]


class MensajeContacto(models.Model):
    nombre = models.CharField(max_length=100)
    email = models.EmailField()
    asunto = models.CharField(max_length=120)
    mensaje = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    atendido = models.BooleanField(default=False)

    class Meta:
        db_table = 'mensaje_contacto'
        verbose_name_plural = 'Mensajes de contacto'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.asunto} - {self.nombre}'
