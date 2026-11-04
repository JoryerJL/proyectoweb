from django.contrib.auth.models import User
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .context_processors import invalidate_sidebar_cache
from .models import Archivo, Categoria, Perfil, Publicacion


@receiver(post_save, sender=User)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        Perfil.objects.create(user=instance)


@receiver([post_save, post_delete], sender=Archivo)  # covers can change
@receiver([post_save, post_delete], sender=Categoria)
@receiver([post_save, post_delete], sender=Publicacion)
def invalidar_cache_lateral(sender, **kwargs):
    """The sidebar shows categories, per-category counts and recent posts."""
    invalidate_sidebar_cache()
