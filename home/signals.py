from django.contrib.auth.models import User
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .context_processors import invalidate_sidebar_cache
from .models import Archivo, Categoria, Perfil, Publicacion


@receiver(post_save, sender=User)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        # Every creation path except public sign-up (panel, admin, createsuperuser, ORM) is trusted;
        # the model default is verified. SignUpForm.save is the only place that flips it to unverified.
        Perfil.objects.create(user=instance, email_verificado_en=timezone.now())


@receiver([post_save, post_delete], sender=Archivo)  # covers can change
@receiver([post_save, post_delete], sender=Categoria)
@receiver([post_save, post_delete], sender=Publicacion)
def invalidar_cache_lateral(sender, **kwargs):
    """The sidebar shows categories, per-category counts and recent posts."""
    invalidate_sidebar_cache()
